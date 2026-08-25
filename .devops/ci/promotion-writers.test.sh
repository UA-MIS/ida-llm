#!/usr/bin/env bash
# promotion-writers.test.sh — assert every environment promotion.yaml DECLARES is an
# environment some workflow can actually WRITE.
#
# ⚠ WHY THIS EXISTS. promotion.yaml is the canonical trigger->env->tag contract, and
# both the ApplicationSet and the CI seam read it. But declaring an env there does not
# CREATE its writer: something in .github/workflows/ has to invoke bump-image.sh (or
# promote.sh) for that env, or the declared rung is documentation fiction.
#
# That is exactly what shipped. `staging.trigger: "tag:v*"` was declared, the README
# documented "push tag vX.Y.Z -> staging", resolve-image.sh resolved the semver tag and
# the build pushed :X.Y.Z to Harbor — and NO job ever wrote staging's overlay, because
# bump-dev is gated on refs/heads/main. Staging stayed frozen at its first-deploy seed
# tag. Nobody noticed until the first real release tag (v0.1.0, 2026-08-25), because
# staging LOOKED healthy the whole time — it was running an old image, not a broken one.
#
# The existing suites could not catch it: bump-image.test.sh proves `bump-image.sh
# staging <tag>` WORKS, and chart-render.test.sh proves the overlay RENDERS. Both pass
# with flying colours while nothing calls the script. "Is it correct?" was tested; "is
# it wired?" was not. This suite tests the wiring.
#
# It matters beyond a stale env, because a missing writer is not fail-safe: promote.sh
# copies "whatever tag is live in <from>'s overlay" into prod, so an unwritten staging
# silently promotes a STALE tag to production — a pre-port image, or (for a component
# added after the seed) a tag that was never built, giving prod ImagePullBackOff.
#
# Requires: bash, python3 (PyYAML — already installed in the ci.yml job that runs this).
# Run: .devops/ci/promotion-writers.test.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVOPS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${DEVOPS_DIR}/.." && pwd)"
PASS=0; FAIL=0
assert_eq() { if [ "$2" = "$3" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL [$1]: got '$2' want '$3'"; fi; }

# writers_for <promotion.yaml> <workflows-dir>
# Prints one line per declared env: "<env> <writer|MISSING> <ref-gate|->".
#
# An env is WRITTEN if some workflow invokes `bump-image.sh <env>` or names it as
# promote.sh's <to> argument. The ref-gate column reports whether the writing job's
# `if:` mentions refs/tags or refs/heads, so a writer wired to the WRONG trigger is
# visible too (a staging writer gated on refs/heads/main would be just as broken).
writers_for() {
  python3 - "$1" "$2" <<'PY'
import os, re, sys, yaml

promotion, wfdir = sys.argv[1], sys.argv[2]
envs = list((yaml.safe_load(open(promotion)) or {}).get('environments', {}) or {})

blobs = {}
for root, _, files in os.walk(wfdir):
    for f in files:
        if f.endswith(('.yml', '.yaml')):
            p = os.path.join(root, f)
            blobs[p] = open(p, encoding='utf-8').read()

def find_writer(env):
    # bump-image.sh <env>  (quoted or bare)
    bump = re.compile(r'bump-image\.sh\s+["\']?' + re.escape(env) + r'["\']?(\s|$)')
    # promote.sh <from> <env>  — <env> is the TO argument, i.e. the overlay written.
    # <from> may be a GitHub expression CONTAINING SPACES ("${{ inputs.from }}"), so
    # this deliberately does not try to tokenise it: match promote.sh anywhere on the
    # line with <env> as the final argument.
    prom = re.compile(r'promote\.sh\b.*?["\']?' + re.escape(env) + r'["\']?\s*$')
    for path, text in sorted(blobs.items()):
        for line in text.splitlines():
            # ⚠ SKIP COMMENTED-OUT LINES. Without this the detector counts a
            # `#`-disabled invocation as a live writer — and "comment it out
            # temporarily" is the single most likely way a writer actually gets
            # disabled, far likelier than deleting the whole job. Caught in review
            # of PR #16: commenting out staging's real bump-image.sh line, leaving
            # the job and its `if:` intact, left this suite fully GREEN (5 passed,
            # 0 failed) while staging silently stopped advancing and promote.sh
            # would copy a stale tag into prod. A gate that reports all-clear on
            # the regression it exists to catch is worse than no gate.
            if line.lstrip().startswith('#'):
                continue
            if bump.search(line) or prom.search(line):
                return os.path.basename(path)
    return None

def ref_gate(path_base, env):
    """Best-effort: which ref does the job containing this env's writer gate on."""
    for path, text in sorted(blobs.items()):
        if os.path.basename(path) != path_base:
            continue
        # walk jobs, find the one whose body mentions the writer invocation
        try:
            doc = yaml.safe_load(text) or {}
        except Exception:
            return '-'
        for jname, job in (doc.get('jobs') or {}).items():
            body = yaml.safe_dump(job)
            if re.search(r'bump-image\.sh\s+["\']?' + re.escape(env), body) or \
               re.search(r'promote\.sh\b.*?["\']?' + re.escape(env) + r'["\']?\s*$', body, re.M):
                cond = str(job.get('if', ''))
                if 'refs/tags' in cond:
                    return 'refs/tags'
                if 'refs/heads' in cond:
                    return 'refs/heads'
                if 'pull_request' in cond:
                    return 'pull_request'
                # ⚠ YAML 1.1 parses the bare key `on:` as the BOOLEAN True, not the
                # string 'on' — so a workflow's trigger block lands under doc[True]
                # and doc.get('on') is None. Reading only 'on' reported every
                # dispatch-only workflow as ungated ('none'), which reads like a
                # DEFECT in a report whose whole job is spotting missing gates.
                triggers = doc.get(True, doc.get('on')) or {}
                if 'workflow_dispatch' in yaml.safe_dump(triggers):
                    return 'manual'
                return 'none'
    return '-'

for env in envs:
    w = find_writer(env)
    print(env, w or 'MISSING', ref_gate(w, env) if w else '-')
PY
}

# ---- 1) THE REGRESSION: every env this repo declares has a real writer ------
echo "== declared envs and their writers =="
REAL="$(writers_for "${DEVOPS_DIR}/promotion.yaml" "${REPO_DIR}/.github/workflows")"
echo "${REAL}"
MISSING="$(echo "${REAL}" | awk '$2=="MISSING"{printf "%s ", $1}')"
assert_eq "every declared env has a writer" "${MISSING}" ""

# ---- 2) a tag-triggered env must be written by a TAG-gated job --------------
# Catches the subtler variant: the writer exists but hangs off the wrong trigger,
# so the env still never advances on the event that is supposed to advance it.
TAG_ENVS="$(python3 - "${DEVOPS_DIR}/promotion.yaml" <<'PY'
import sys, yaml
d = (yaml.safe_load(open(sys.argv[1])) or {}).get('environments', {}) or {}
print(' '.join(e for e, c in d.items() if str((c or {}).get('trigger', '')).startswith('tag:')))
PY
)"
for env in ${TAG_ENVS}; do
  GATE="$(echo "${REAL}" | awk -v e="${env}" '$1==e{print $3}')"
  assert_eq "tag-triggered '${env}' writer is tag-gated" "${GATE}" "refs/tags"
done

# ---- 3) NEGATIVE CONTROL: the check must be able to FAIL --------------------
# A suite that cannot fail proves nothing. Synthesise a promotion.yaml declaring an
# env no workflow writes, and assert this detector reports it MISSING.
TMP="$(mktemp -d)"
mkdir -p "${TMP}/wf"
cat > "${TMP}/promotion.yaml" <<'YAML'
apiVersion: platform.capstone/v1
registry: harbor.example.com/team-sample
app: myapp
environments:
  dev:
    trigger: "branch:main"
    overlay: ".devops/chart/overlays/dev"
    gate: auto
  ghost:
    trigger: "tag:v*"
    overlay: ".devops/chart/overlays/ghost"
    gate: auto
YAML
cat > "${TMP}/wf/build.yaml" <<'YAML'
name: build
on:
  push:
    branches: [main]
jobs:
  bump-dev:
    if: ${{ github.ref == 'refs/heads/main' }}
    runs-on: ubuntu-latest
    steps:
      - run: COMMIT=1 bash .devops/ci/bump-image.sh dev "${TAG}"
YAML
SYNTH="$(writers_for "${TMP}/promotion.yaml" "${TMP}/wf")"
assert_eq "negative control: dev detected"    "$(echo "${SYNTH}" | awk '$1=="dev"{print $2}')"   "build.yaml"
assert_eq "negative control: ghost MISSING"   "$(echo "${SYNTH}" | awk '$1=="ghost"{print $2}')" "MISSING"
assert_eq "negative control: dev is head-gated" "$(echo "${SYNTH}" | awk '$1=="dev"{print $3}')" "refs/heads"

# ---- 4) COMMENTED-OUT WRITER must NOT count (regression test for M-1) ------
# The reviewer's exact repro from PR #16. Commenting a writer out — leaving the job,
# its `if:` and everything else intact — is how a writer gets disabled in practice,
# far likelier than deleting the whole job. Before the comment-skip in find_writer
# this tree reported "staging build-and-push.yaml refs/tags" and passed 5/0 GREEN
# while staging silently stopped advancing. Assert both halves: the disabled env is
# MISSING, and the suite's own top-level assertion actually fails on it.
TMP2="$(mktemp -d)"
mkdir -p "${TMP2}/wf"
cat > "${TMP2}/promotion.yaml" <<'YAML'
apiVersion: platform.capstone/v1
registry: harbor.example.com/team-sample
app: myapp
environments:
  staging:
    trigger: "tag:v*"
    overlay: ".devops/chart/overlays/staging"
    gate: auto
YAML
cat > "${TMP2}/wf/build.yaml" <<'YAML'
name: build
on:
  push:
    tags: ["v*"]
jobs:
  bump-staging:
    if: ${{ startsWith(github.ref, 'refs/tags/v') }}
    runs-on: ubuntu-latest
    steps:
      - run: |
          # TEMPORARILY DISABLED: COMMIT=1 bash .devops/ci/bump-image.sh staging "${TAG}"
          echo "noop"
YAML
COMMENTED="$(writers_for "${TMP2}/promotion.yaml" "${TMP2}/wf")"
assert_eq "commented-out writer is MISSING" "$(echo "${COMMENTED}" | awk '$1=="staging"{print $2}')" "MISSING"

# And the same shape with a YAML-level comment (whole line commented at lower indent).
cat > "${TMP2}/wf/build.yaml" <<'YAML'
name: build
on:
  push:
    tags: ["v*"]
jobs:
  bump-staging:
    if: ${{ startsWith(github.ref, 'refs/tags/v') }}
    runs-on: ubuntu-latest
    steps:
#      - run: COMMIT=1 bash .devops/ci/bump-image.sh staging "${TAG}"
      - run: echo noop
YAML
COMMENTED2="$(writers_for "${TMP2}/promotion.yaml" "${TMP2}/wf")"
assert_eq "yaml-commented writer is MISSING" "$(echo "${COMMENTED2}" | awk '$1=="staging"{print $2}')" "MISSING"

echo "== FINAL: $PASS passed, $FAIL failed =="
[ "${FAIL}" -eq 0 ]
