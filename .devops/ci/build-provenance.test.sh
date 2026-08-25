#!/usr/bin/env bash
# build-provenance.test.sh — assert the BOTH-HALVES wirings that make a deployed
# image able to say what it is.
#
# ⚠ WHY THIS EXISTS. Three of this platform's identity values only work if two
# separate files agree, and in every case the failure of one half is SILENT:
#
#   1. IDA_GIT_SHA — Dockerfile.python declares `ARG GIT_SHA` and exports it as
#      `ENV IDA_GIT_SHA`; build-and-push.yaml passes `--build-arg=GIT_SHA=`. Drop
#      the build-arg and the ARG defaults to "", so every deployed result records
#      `task_git_sha: null` and proves nothing. Nothing fails; the numbers just
#      stop being citable. Dockerfile.python's own comment says "without BOTH
#      halves of that wiring" — this suite is what makes that sentence enforced
#      rather than merely written down.
#
#   2. IDA_VERSION — the same shape, for the release string /healthz reports.
#      This half did not exist at all: /healthz read a hardcoded `__version__ =
#      "0.1.0"` that no release step ever wrote to, so the 0.1.1 image answered
#      "0.1.0". A health endpoint that disagrees with the release it is running
#      is what convinces someone a deploy did not land and gets a good release
#      rolled back.
#
#   3. The Harbor read credential — promote.sh refuses to write prod's overlay
#      unless it can CONFIRM every component's tag exists in the registry
#      (AB#34), and that check is fail-CLOSED: "I could not authenticate" is a
#      refusal, not a pass. promote-to-prod.yaml shipped with no registry
#      credential, so the guard would have blocked EVERY promotion with a
#      registry error instead of catching bad tags. A guard that cannot run is
#      not a weaker guard — it is a broken workflow.
#
# WHAT THIS SUITE CANNOT DO, stated so the guarantee is not overread: it does not
# build an image. These runners have no Docker daemon (Kaniko runs as a workflow
# step, not a nested build), so a real ARG->ENV round trip is out of reach here.
# It asserts the WIRING — that both halves are present and reference the same
# variable — which is the half that has actually broken. The runtime behaviour of
# the values themselves is covered by the Python suites (`TestBuildIdentity`,
# `TestHealthIdentifiesTheBuild`).
#
# Requires: bash, grep. Run: .devops/ci/build-provenance.test.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DOCKERFILE="${REPO_DIR}/Dockerfile.python"
BUILD_WF="${REPO_DIR}/.github/workflows/build-and-push.yaml"
PROMOTE_WF="${REPO_DIR}/.github/workflows/promote-to-prod.yaml"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); }
bad()  { FAIL=$((FAIL+1)); echo "FAIL [$1]: $2"; }

# assert_matches <name> <file> <extended-regex> <why-it-matters>
assert_matches() {
  # `-e` and `--` are load-bearing: two of the patterns below start with a dash
  # (`--build-arg=`). Without them grep reads that as an option, finds no pattern,
  # and silently BLOCKS reading stdin -- a hung suite, not a failing one.
  if grep -Eq -e "$3" -- "$2"; then ok; else bad "$1" "$4 (no match for /$3/ in ${2#"${REPO_DIR}"/})"; fi
}

# assert_absent <name> <file> <extended-regex> <why-it-matters>
assert_absent() {
  if grep -Eq -e "$3" -- "$2"; then bad "$1" "$4 (unexpected match for /$3/ in ${2#"${REPO_DIR}"/})"; else ok; fi
}

for f in "${DOCKERFILE}" "${BUILD_WF}" "${PROMOTE_WF}"; do
  [ -f "${f}" ] || { echo "FAIL: missing ${f}"; exit 1; }
done

# ── 1. IDA_GIT_SHA: the provenance half that already existed ────────────────
assert_matches "gitsha-arg" "${DOCKERFILE}" '^ARG GIT_SHA=' \
  "Dockerfile.python must declare ARG GIT_SHA"
assert_matches "gitsha-env" "${DOCKERFILE}" 'IDA_GIT_SHA=\$\{GIT_SHA\}' \
  "Dockerfile.python must export GIT_SHA as ENV IDA_GIT_SHA (ida_core.gitmeta reads it)"
assert_matches "gitsha-buildarg" "${BUILD_WF}" '--build-arg=GIT_SHA=' \
  "build-and-push.yaml must pass --build-arg=GIT_SHA, or every deployed result records task_git_sha: null"
assert_matches "gitsha-value" "${BUILD_WF}" 'GIT_SHA: \$\{\{ github\.sha \}\}' \
  "GIT_SHA must be github.sha -- gitmeta.is_sha() rejects anything that is not 40 lowercase hex"

# ── 2. IDA_VERSION: the release half /healthz reports ───────────────────────
assert_matches "version-arg" "${DOCKERFILE}" '^ARG IDA_VERSION=' \
  "Dockerfile.python must declare ARG IDA_VERSION"
assert_matches "version-env" "${DOCKERFILE}" 'IDA_VERSION=\$\{IDA_VERSION\}' \
  "Dockerfile.python must export it as ENV IDA_VERSION, or /healthz falls back to the packaging version forever"
assert_matches "version-buildarg" "${BUILD_WF}" '--build-arg=IDA_VERSION=' \
  "build-and-push.yaml must pass --build-arg=IDA_VERSION, or the ARG defaults to empty and the image cannot name its release"
# THE TAG, not a literal. Pinning the SOURCE is the point: the overlays pin
# `newTag: <TAG>`, so tying /healthz's version to the same value is what makes
# "what does /healthz say" and "what does prod's kustomization.yaml say"
# comparable. A hand-typed version string here would drift on the first release.
assert_matches "version-source-is-the-resolved-tag" "${BUILD_WF}" \
  'IDA_VERSION: \$\{\{ needs\.resolve\.outputs\.TAG \}\}' \
  "IDA_VERSION must be the resolved image TAG, so /healthz and the overlays name the same thing"

# ⚠ THE REGRESSION, PINNED BY VALUE. "0.1.0" is not merely one possible wrong
# answer: it is the exact string five packages hardcoded and every image served
# for the life of the platform. A well-meaning "give it a sensible default" edit
# reaches for precisely this.
assert_absent "version-is-never-hardcoded" "${BUILD_WF}" 'IDA_VERSION: *["'\'']?0\.1\.0' \
  "IDA_VERSION must never be a hardcoded release literal"
assert_absent "dockerfile-version-is-never-hardcoded" "${DOCKERFILE}" '^ARG IDA_VERSION="?0\.' \
  "ARG IDA_VERSION must default to empty (honest), never to a release-shaped literal"

# ── 3. The Harbor read credential the promote-time tag check needs ──────────
assert_matches "promote-docker-config" "${PROMOTE_WF}" 'DOCKER_CONFIG: */kaniko/\.docker' \
  "promote-to-prod.yaml must point promote.sh at the runner's mounted Harbor robot"
assert_matches "promote-explicit-secrets" "${PROMOTE_WF}" 'HARBOR_PASSWORD: \$\{\{ secrets\.HARBOR_PASSWORD \}\}' \
  "promote-to-prod.yaml must forward HARBOR_PASSWORD so an explicit read-only robot can override the mount"
assert_matches "promote-credential-preflight" "${PROMOTE_WF}" '::error::No Harbor read credential' \
  "a missing credential must fail LOUDLY before promote.sh, not as a confusing refusal inside it"
# ⚠ The escape hatch must not be on by default. An override that is always
# enabled is not an override -- it is the guard being switched off in writing.
assert_absent "promote-does-not-preset-the-escape-hatch" "${PROMOTE_WF}" \
  'ALLOW_UNVERIFIED_PROMOTE: *["'\'']?1' \
  "ALLOW_UNVERIFIED_PROMOTE must not be set by the workflow -- it is an operator decision"

echo "build-provenance.test.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
