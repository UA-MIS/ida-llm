#!/usr/bin/env bash
# promote.test.sh — unit tests for promote.sh (the click-to-promote seam).
# Builds a temp repo (promotion.yaml + staging/prod overlays), runs a
# promotion, and asserts the live staging tag lands in prod, mismatched
# components are refused, and COMMIT=1 produces the GitOps signal commit.
# Requires: bash, git (yq optional). Run: .devops/ci/promote.test.sh
#
# ⚠ ALLOW_UNVERIFIED_PROMOTE=1 ON THE LEGACY CASES, DELIBERATELY.
# promote.sh now verifies every component's tag against the REGISTRY before it
# writes anything (AB#34). The fixtures below point at `harbor.example.com`, a
# name that exists to be read, not resolved -- so the probe is inconclusive for
# them and promote.sh (fail-closed) would refuse. Setting the documented
# override keeps these cases testing what they were written to test (tag copy,
# quoting, commit shape) instead of silently becoming registry tests. The
# registry check itself is covered by cases 8-11, which stand up a REAL local
# registry and never set the override.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROMOTE="${SCRIPT_DIR}/promote.sh"
BUMP="${SCRIPT_DIR}/bump-image.sh"
PASS=0; FAIL=0

# Build a throwaway repo whose layout matches a rendered multi-component tenant
# with staging + prod overlays, staging already "live" at 1.2.3.
make_repo() {
  local root; root="$(mktemp -d)"
  mkdir -p "${root}/.devops/ci" "${root}/.devops/chart/overlays/staging" "${root}/.devops/chart/overlays/prod"
  cp "${BUMP}" "${root}/.devops/ci/bump-image.sh"
  cp "${PROMOTE}" "${root}/.devops/ci/promote.sh"
  cat > "${root}/.devops/promotion.yaml" <<'YAML'
apiVersion: platform.capstone/v1
registry: harbor.example.com/team-sample
app: myapp
environments:
  staging:
    trigger: "tag:v*"
    tagConvention: "semver"
    overlay: ".devops/chart/overlays/staging"
    gate: auto
  prod:
    trigger: "manual:promote-to-prod"
    tagConvention: "semver"
    overlay: ".devops/chart/overlays/prod"
    gate: auto
YAML
  cat > "${root}/.devops/chart/overlays/staging/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: team-sample-staging
resources:
  - ../../base
images:
  - name: myapp-frontend
    newName: harbor.example.com/team-sample/myapp-frontend
    newTag: 1.2.3
  - name: myapp-backend
    newName: harbor.example.com/team-sample/myapp-backend
    newTag: 1.2.3
YAML
  cat > "${root}/.devops/chart/overlays/prod/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: team-sample-prod
resources:
  - ../../base
images:
  - name: myapp-frontend
    newName: harbor.example.com/team-sample/myapp-frontend
    newTag: 1.1.0
  - name: myapp-backend
    newName: harbor.example.com/team-sample/myapp-backend
    newTag: 1.1.0
YAML
  # git is optional here — guard it so a git-less container doesn't spray
  # "git: command not found" across every make_repo() call (only the [uncommitted]
  # and [commit] assertions below actually depend on git being present).
  if command -v git >/dev/null 2>&1; then
    ( cd "${root}" && git init -q && git config user.email t@t && git config user.name t && git add -A && git commit -qm init )
  fi
  printf '%s' "${root}"
}

# ⚠ MATCH BOTH THE QUOTED AND UNQUOTED FORMS.
# Inherited-from-crimson-copies BUG, fixed here: this helper used to grep for a
# bare `newTag: 1.2.3`, but promote.sh (like bump-image.sh) always WRITES the
# double-quoted form `newTag: "1.2.3"`. So two assertions below reported FAIL on
# a promotion that had in fact worked perfectly -- verified by running promote.sh
# by hand and reading the resulting overlay. A suite that always shows 2 red is a
# suite people stop reading, which is worse than no suite.
count_tag() {
  local n
  n="$(grep -cE "newTag: \"?$1\"?" "$2" 2>/dev/null)" || n=0
  printf '%s' "${n}"
}
assert_eq() { if [ "$2" = "$3" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL [$1]: got '$2' want '$3'"; fi; }

# Isolate the no-yq sed-fallback path (same pattern as bump-image.test.sh).
NOYQ_DIR="$(mktemp -d)"
for b in bash sh sed cut head dirname awk printf cat env grep git mktemp; do
  src="$(command -v "$b" 2>/dev/null)" && [ -n "$src" ] && ln -sf "$src" "${NOYQ_DIR}/$b"
done

# Build a repo whose staging overlay is QUOTED, i.e. what staging's kustomization.yaml
# ACTUALLY looks like after a real bump-image.sh write (which always double-quotes) --
# unlike make_repo()'s hand-written bare `newTag: 1.2.3` fixtures above, which never
# exercised the real-world shape and so never caught FIX-23.
make_quoted_repo() {
  local root; root="$(mktemp -d)"
  mkdir -p "${root}/.devops/ci" "${root}/.devops/chart/overlays/staging" "${root}/.devops/chart/overlays/prod"
  cp "${BUMP}" "${root}/.devops/ci/bump-image.sh"
  cp "${PROMOTE}" "${root}/.devops/ci/promote.sh"
  cat > "${root}/.devops/promotion.yaml" <<'YAML'
apiVersion: platform.capstone/v1
registry: harbor.example.com/team-sample
app: myapp
environments:
  staging:
    trigger: "tag:v*"
    tagConvention: "semver"
    overlay: ".devops/chart/overlays/staging"
    gate: auto
  prod:
    trigger: "manual:promote-to-prod"
    tagConvention: "semver"
    overlay: ".devops/chart/overlays/prod"
    gate: auto
YAML
  cat > "${root}/.devops/chart/overlays/staging/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: team-sample-staging
resources:
  - ../../base
images:
  - name: myapp-frontend
    newName: harbor.example.com/team-sample/myapp-frontend
    newTag: "1.0.0"
  - name: myapp-backend
    newName: harbor.example.com/team-sample/myapp-backend
    newTag: "1.0.0"
YAML
  cat > "${root}/.devops/chart/overlays/prod/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: team-sample-prod
resources:
  - ../../base
images:
  - name: myapp-frontend
    newName: harbor.example.com/team-sample/myapp-frontend
    newTag: v0.9.0
  - name: myapp-backend
    newName: harbor.example.com/team-sample/myapp-backend
    newTag: v0.9.0
YAML
  if command -v git >/dev/null 2>&1; then
    ( cd "${root}" && git init -q && git config user.email t@t && git config user.name t && git add -A && git commit -qm init )
  fi
  printf '%s' "${root}"
}

echo "== promote.sh tests =="

# 1) staging's live tag (1.2.3) lands in prod's overlay, unwritten.
R1="$(make_repo)"; PK1="${R1}/.devops/chart/overlays/prod/kustomization.yaml"
ALLOW_UNVERIFIED_PROMOTE=1 bash "${R1}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
assert_eq "promote rc"          "${RC}" "0"
assert_eq "prod new count"      "$(count_tag '1.2.3' "${PK1}")" "2"
assert_eq "prod old count"      "$(count_tag '1.1.0' "${PK1}")" "0"

# 2) no COMMIT=1 -> the write happens but nothing is committed (dry-write, matches bump-image.sh).
if command -v git >/dev/null 2>&1; then
  DIRTY="$(git -C "${R1}" status --porcelain)"
  case "${DIRTY}" in
    *"overlays/prod/kustomization.yaml"*) PASS=$((PASS+1)) ;;
    *) FAIL=$((FAIL+1)); echo "FAIL [uncommitted]: expected a dirty prod overlay, got: '${DIRTY}'" ;;
  esac
else
  echo "NOTE: git not available — skipping uncommitted-dirty-status assertion"
fi

# 3) COMMIT=1 promotes AND commits (the GitOps signal) -- FIX-18/D-030: must NOT carry
# `[skip ci]` (permanently suppresses any future tag push on this commit too; see
# bump-image.sh's header comment).
if command -v git >/dev/null 2>&1; then
  R2="$(make_repo)"
  COMMIT=1 ALLOW_UNVERIFIED_PROMOTE=1 bash "${R2}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "commit rc" "${RC}" "0"
  LAST="$(git -C "${R2}" log -1 --pretty=%s 2>/dev/null)"
  case "${LAST}" in
    *"[skip ci]"*) FAIL=$((FAIL+1)); echo "FAIL [commit]: commit subject must NOT carry [skip ci] (FIX-18): '${LAST}'" ;;
    "ci: bump prod images to 1.2.3") PASS=$((PASS+1)) ;;
    *) FAIL=$((FAIL+1)); echo "FAIL [commit]: unexpected commit subject: '${LAST}'" ;;
  esac
  PK2="${R2}/.devops/chart/overlays/prod/kustomization.yaml"
  assert_eq "committed prod tag count" "$(count_tag '1.2.3' "${PK2}")" "2"
else
  echo "NOTE: git not available — skipping COMMIT=1 commit-message and committed-tag assertions"
fi

# 4) from == to is refused (guard against a no-op / self-promote mistake).
R3="$(make_repo)"
bash "${R3}/.devops/ci/promote.sh" prod prod >/tmp/promote.log 2>&1; RC=$?
assert_eq "same-env rc" "${RC}" "2"

# 5) a mismatched "from" overlay (partial hand-edit) is refused, not silently promoted.
R4="$(make_repo)"
SK4="${R4}/.devops/chart/overlays/staging/kustomization.yaml"
sed -i '0,/newTag: 1.2.3/s//newTag: 9.9.9/' "${SK4}"   # only ONE of the two entries changes
bash "${R4}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
assert_eq "mismatched rc" "${RC}" "1"

# 6) FIX-23 regression: staging is quoted (newTag: "1.0.0", the real post-bump-image.sh
# shape) -- promoting it must NOT double-quote prod. yq path (default PATH). yq's
# strenv only quotes when the bare value would otherwise parse as a non-string YAML
# type; "1.0.0" (two dots) is never ambiguous with a YAML number, so yq correctly
# writes it BARE here -- both `newTag: 1.0.0` and `newTag: "1.0.0"` are valid,
# equivalent YAML, so the assertion is quote-tolerant (same pattern bump-image.test.sh
# uses), unlike case 7 below where the sed fallback always quotes by design.
R5="$(make_quoted_repo)"; PK5="${R5}/.devops/chart/overlays/prod/kustomization.yaml"
ALLOW_UNVERIFIED_PROMOTE=1 bash "${R5}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
assert_eq "quoted/yq promote rc"       "${RC}" "0"
assert_eq "quoted/yq no double-quote"  "$(grep -c 'newTag: ""' "${PK5}")" "0"
assert_eq "quoted/yq bare-or-quoted tag" "$(grep -Ec 'newTag: "?1\.0\.0"?$' "${PK5}")" "2"

# 7) same regression, no-yq sed fallback (the actual reported failure mode -- prod
# ships this way because node:24-trixie, the real CI runner image, has no yq).
if PATH="${NOYQ_DIR}" command -v yq >/dev/null 2>&1; then
  echo "NOTE: yq present on restricted PATH — sed fallback not isolated; skipping FIX-23 sed regression"
else
  R6="$(make_quoted_repo)"; PK6="${R6}/.devops/chart/overlays/prod/kustomization.yaml"
  PATH="${NOYQ_DIR}" ALLOW_UNVERIFIED_PROMOTE=1 bash "${R6}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "quoted/sed promote rc"        "${RC}" "0"
  assert_eq "quoted/sed no double-quote"   "$(grep -c 'newTag: ""' "${PK6}")" "0"
  assert_eq "quoted/sed single-quoted tag" "$(grep -c 'newTag: "1.0.0"' "${PK6}")" "2"
  # The regression as originally reported: LIVE_TAG carrying literal quote characters
  # (7 chars for "1.0.0" instead of 5) is exactly what produced `newTag: ""1.0.0""`.
  assert_eq "quoted/sed no stray quote pairs" "$(grep -c 'newTag: """' "${PK6}")" "0"
fi

# ── AB#34: THE TAG MUST ACTUALLY EXIST IN THE REGISTRY ──────────────────────
#
# The bug these cases exist for: promote.sh copied <from>'s tag into <to> without
# ever asking the registry whether that tag was BUILT. Live proof —
# `ida-llm-agile:be4e3d9` never existed (the agile component postdates that
# commit), so a dev→prod promote pinned prod to an image that cannot be pulled and
# the board came up ImagePullBackOff. promotion-writers.test.sh structurally cannot
# catch this: the writer exists and is correctly gated; the TAG is what is wrong.
#
# These cases stand up a REAL registry on loopback and never set
# ALLOW_UNVERIFIED_PROMOTE, so they exercise the actual HTTP path — the probe, the
# 404, and the fail-before-mutate ordering.
MOCK_REGISTRY_PY="$(mktemp -d)/mock_registry.py"
cat > "${MOCK_REGISTRY_PY}" <<'PY'
"""A minimal OCI-distribution responder: 200 for tags in MOCK_TAGS, 404 otherwise.

Deliberately NOT a stub of promote.sh's own logic -- it speaks the wire protocol,
so the suite exercises the real request promote.sh sends (URL shape, auth header,
token exchange) rather than a mock shaped to agree with it.

MOCK_AUTH_MODE:
  ""       open registry, anonymous reads
  basic    401 unless an Authorization header is present
  bearer   THE REAL HARBOR'S BEHAVIOUR, verified against
           harbor.capstone.uamishub.com: an anonymous manifest GET is answered
           401 + `WWW-Authenticate: Bearer realm=...,service=...,scope=...`. The
           realm issues a token to ANYONE, but a token minted without a
           credential carries no pull rights and the retry is 401 again -- which
           is exactly what the live registry does, and the reason a Basic-only
           check would have refused every real promotion.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KNOWN = {t for t in os.environ.get("MOCK_TAGS", "").split(",") if t}
AUTH_MODE = os.environ.get("MOCK_AUTH_MODE", "")
GOOD_TOKEN = "token-with-pull"
ANON_TOKEN = "token-without-pull"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):  # keep the suite's output readable
        pass

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _token_endpoint(self):
        # A credential earns a token that can pull; anonymity earns one that cannot.
        got_credential = bool(self.headers.get("Authorization"))
        token = GOOD_TOKEN if got_credential else ANON_TOKEN
        self._send(200, json.dumps({"token": token}).encode())

    def _respond(self):
        path = self.path.split("?", 1)[0]
        if path == "/service/token":
            return self._token_endpoint()

        authorization = self.headers.get("Authorization", "")
        if AUTH_MODE == "basic" and not authorization:
            return self._send(401, headers=[("WWW-Authenticate", 'Basic realm="harbor"')])
        if AUTH_MODE == "bearer" and authorization != "Bearer " + GOOD_TOKEN:
            repo = ""
            if path.startswith("/v2/") and "/manifests/" in path:
                repo = path[len("/v2/"):].split("/manifests/", 1)[0]
            realm = "http://%s/service/token" % self.headers.get("Host", "127.0.0.1")
            challenge = 'Bearer realm="%s",service="mock-registry",scope="repository:%s:pull"' % (realm, repo)
            return self._send(401, headers=[("WWW-Authenticate", challenge)])

        ref = None
        if path.startswith("/v2/") and "/manifests/" in path:
            repo, tag = path[len("/v2/"):].split("/manifests/", 1)
            ref = repo + ":" + tag
        if ref is not None and ref in KNOWN:
            return self._send(
                200,
                b'{"schemaVersion":2}',
                [("Content-Type", "application/vnd.oci.image.manifest.v1+json")],
            )
        return self._send(404)

    do_GET = _respond
    do_HEAD = _respond


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(server.server_address[1], flush=True)
server.serve_forever()
PY

MOCK_PID=""
MOCK_PORT=""
start_mock_registry() {
  # $1 = comma-separated "<repo>:<tag>" refs the registry should answer 200 for.
  # $2 = auth mode: "" (open), "basic", or "bearer" (what the real Harbor does).
  local tags="$1" mode="${2:-}" portfile i
  portfile="$(mktemp)"
  MOCK_TAGS="${tags}" MOCK_AUTH_MODE="${mode}" python3 "${MOCK_REGISTRY_PY}" >"${portfile}" 2>/dev/null &
  MOCK_PID=$!
  for i in $(seq 1 100); do
    MOCK_PORT="$(head -1 "${portfile}" 2>/dev/null | tr -dc '0-9')"
    [ -n "${MOCK_PORT}" ] && return 0
    sleep 0.1
  done
  return 1
}
stop_mock_registry() {
  [ -n "${MOCK_PID}" ] && kill "${MOCK_PID}" 2>/dev/null
  wait "${MOCK_PID}" 2>/dev/null
  MOCK_PID=""
}

# Same fixture shape as make_repo, but the registry host is a parameter so the
# overlay can point at the loopback mock. staging live at 1.2.3, prod at 1.1.0.
make_repo_at() {
  local registry="$1" root; root="$(mktemp -d)"
  mkdir -p "${root}/.devops/ci" "${root}/.devops/chart/overlays/staging" "${root}/.devops/chart/overlays/prod"
  cp "${BUMP}" "${root}/.devops/ci/bump-image.sh"
  cp "${PROMOTE}" "${root}/.devops/ci/promote.sh"
  cat > "${root}/.devops/promotion.yaml" <<YAML
apiVersion: platform.capstone/v1
registry: ${registry}
app: myapp
environments:
  staging:
    trigger: "tag:v*"
    tagConvention: "semver"
    overlay: ".devops/chart/overlays/staging"
    gate: auto
  prod:
    trigger: "manual:promote-to-prod"
    tagConvention: "semver"
    overlay: ".devops/chart/overlays/prod"
    gate: auto
YAML
  cat > "${root}/.devops/chart/overlays/staging/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: team-sample-staging
resources:
  - ../../base
images:
  - name: myapp-frontend
    newName: ${registry}/myapp-frontend
    newTag: "1.2.3"
  - name: myapp-backend
    newName: ${registry}/myapp-backend
    newTag: "1.2.3"
YAML
  cat > "${root}/.devops/chart/overlays/prod/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: team-sample-prod
resources:
  - ../../base
images:
  - name: myapp-frontend
    newName: ${registry}/myapp-frontend
    newTag: "1.1.0"
  - name: myapp-backend
    newName: ${registry}/myapp-backend
    newTag: "1.1.0"
YAML
  printf '%s' "${root}"
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "NOTE: python3 not available — skipping the registry-verification cases (8-11)"
else

# 8) HAPPY PATH THROUGH THE REAL PROBE. Both component tags exist in the registry,
#    no override set: the promotion proceeds exactly as before the check existed.
#    This is the case that proves the guard did not break promotion.
if start_mock_registry "team-sample/myapp-frontend:1.2.3,team-sample/myapp-backend:1.2.3"; then
  R7="$(make_repo_at "127.0.0.1:${MOCK_PORT}/team-sample")"
  PK7="${R7}/.devops/chart/overlays/prod/kustomization.yaml"
  bash "${R7}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "registry-ok rc"        "${RC}" "0"
  assert_eq "registry-ok prod tag"  "$(count_tag '1.2.3' "${PK7}")" "2"
  stop_mock_registry
else
  FAIL=$((FAIL+1)); echo "FAIL [registry-ok]: mock registry never started"
fi

# 9) ⚠ THE AB#34 REGRESSION. The registry has the FRONTEND at 1.2.3 but not the
#    BACKEND -- exactly the ida-llm-agile:be4e3d9 shape (one component was never
#    built at that tag). promote.sh must refuse, name the offending image:tag, and
#    -- the part that matters -- leave prod's overlay BYTE-IDENTICAL. A guard that
#    refuses after writing half the overlay is not fail-before-mutate.
if start_mock_registry "team-sample/myapp-frontend:1.2.3"; then
  R8="$(make_repo_at "127.0.0.1:${MOCK_PORT}/team-sample")"
  PK8="${R8}/.devops/chart/overlays/prod/kustomization.yaml"
  BEFORE8="$(cat "${PK8}")"
  bash "${R8}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "missing-tag rc"           "${RC}" "1"
  assert_eq "missing-tag wrote nothing" "$(cat "${PK8}")" "${BEFORE8}"
  assert_eq "missing-tag prod untouched" "$(count_tag '1.2.3' "${PK8}")" "0"
  # The operator has to be able to see WHICH image is missing without re-deriving it.
  if grep -q 'myapp-backend:1\.2\.3' /tmp/promote.log; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1)); echo "FAIL [missing-tag names the image]: log did not cite myapp-backend:1.2.3"
  fi
  stop_mock_registry
else
  FAIL=$((FAIL+1)); echo "FAIL [missing-tag]: mock registry never started"
fi

# 10) INCONCLUSIVE IS ALSO A REFUSAL (fail-closed). The registry is simply not
#     there -- the port was live and is now closed. "I could not check" must not
#     read as "it is fine": that is the failure mode this whole change exists to
#     end. Without the documented override, refuse and write nothing.
if start_mock_registry "team-sample/myapp-frontend:1.2.3"; then
  DEAD_PORT="${MOCK_PORT}"
  stop_mock_registry
  R9="$(make_repo_at "127.0.0.1:${DEAD_PORT}/team-sample")"
  PK9="${R9}/.devops/chart/overlays/prod/kustomization.yaml"
  BEFORE9="$(cat "${PK9}")"
  bash "${R9}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "unreachable rc"            "${RC}" "1"
  assert_eq "unreachable wrote nothing" "$(cat "${PK9}")" "${BEFORE9}"
  # ...and the SAME repo promotes fine once the operator explicitly accepts the risk.
  ALLOW_UNVERIFIED_PROMOTE=1 bash "${R9}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "override rc"      "${RC}" "0"
  assert_eq "override prod tag" "$(count_tag '1.2.3' "${PK9}")" "2"
  # The override must be LOUD -- a silent bypass is the old behaviour with extra steps.
  if grep -qi 'unverified\|not verified\|WARNING' /tmp/promote.log; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1)); echo "FAIL [override is loud]: no warning in the log"
  fi
else
  FAIL=$((FAIL+1)); echo "FAIL [unreachable]: mock registry never started"
fi

# 11) CREDENTIALS ARE ACTUALLY SENT. A private Harbor project answers 401 to an
#     anonymous probe. Unauthenticated -> inconclusive -> refuse; with
#     HARBOR_USERNAME/HARBOR_PASSWORD -> the Basic header goes out and the probe
#     resolves. Without this case the check would "pass" everywhere by accident on
#     a public registry and fail closed forever on the real, private one.
if start_mock_registry "team-sample/myapp-frontend:1.2.3,team-sample/myapp-backend:1.2.3" basic; then
  R10="$(make_repo_at "127.0.0.1:${MOCK_PORT}/team-sample")"
  PK10="${R10}/.devops/chart/overlays/prod/kustomization.yaml"
  bash "${R10}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "401 anonymous rc"  "${RC}" "1"
  assert_eq "401 wrote nothing" "$(count_tag '1.2.3' "${PK10}")" "0"
  HARBOR_USERNAME=robot HARBOR_PASSWORD=secret \
    bash "${R10}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "authenticated rc"       "${RC}" "0"
  assert_eq "authenticated prod tag" "$(count_tag '1.2.3' "${PK10}")" "2"
  stop_mock_registry
else
  FAIL=$((FAIL+1)); echo "FAIL [auth]: mock registry never started"
fi


# 12) BOTH TRANSPORTS, EXPLICITLY. promote.sh speaks to the registry through curl
#     OR python3, and no single environment exercises both: the promote runner
#     (node:24.16-trixie) has curl, ci.yml's seam-test job (python:3.12-slim) has
#     python3 and deliberately no curl. Whichever one CI happens to run is the only
#     one that would ever be tested — so pin each in turn and check the OTHER one
#     is not quietly broken. A transport that returns 000 for everything still
#     "fails closed", so this would otherwise surface as a promote that refuses
#     forever, on the day someone needs to ship.
if start_mock_registry "team-sample/myapp-frontend:1.2.3,team-sample/myapp-backend:1.2.3"; then
  for client in curl python3; do
    if ! command -v "${client}" >/dev/null 2>&1; then
      echo "NOTE: ${client} not available — skipping its transport case"
      continue
    fi
    RC12="$(make_repo_at "127.0.0.1:${MOCK_PORT}/team-sample")"
    PK12="${RC12}/.devops/chart/overlays/prod/kustomization.yaml"
    REGISTRY_HTTP_CLIENT="${client}" bash "${RC12}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
    assert_eq "transport ${client} rc"       "${RC}" "0"
    assert_eq "transport ${client} prod tag" "$(count_tag '1.2.3' "${PK12}")" "2"
  done
  stop_mock_registry
else
  FAIL=$((FAIL+1)); echo "FAIL [transport]: mock registry never started"
fi

# 13) THE CREDENTIAL PATH PRODUCTION ACTUALLY USES. In CI nobody sets
#     HARBOR_USERNAME — the harbor robot arrives as a mounted docker config.json
#     (build-and-push.yaml waits for exactly that file). If promote.sh could only
#     read the env vars, the real promote would 401 on a private project and refuse
#     every time, and the suite would never notice because it sets the env vars.
if start_mock_registry "team-sample/myapp-frontend:1.2.3,team-sample/myapp-backend:1.2.3" basic; then
  DCFG_DIR="$(mktemp -d)"
  # base64("robot:secret") — the same field docker/kaniko write.
  cat > "${DCFG_DIR}/config.json" <<JSON
{"auths":{"127.0.0.1:${MOCK_PORT}":{"auth":"cm9ib3Q6c2VjcmV0"}}}
JSON
  R13="$(make_repo_at "127.0.0.1:${MOCK_PORT}/team-sample")"
  PK13="${R13}/.devops/chart/overlays/prod/kustomization.yaml"
  DOCKER_CONFIG="${DCFG_DIR}" bash "${R13}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "docker-config auth rc"       "${RC}" "0"
  assert_eq "docker-config auth prod tag" "$(count_tag '1.2.3' "${PK13}")" "2"
  stop_mock_registry
else
  FAIL=$((FAIL+1)); echo "FAIL [docker-config auth]: mock registry never started"
fi

# ── 14-16: THE REAL REGISTRY'S AUTH SHAPE ──────────────────────────────────
# Verified against harbor.capstone.uamishub.com before these were written: an
# anonymous manifest GET there returns
#   401 WWW-Authenticate: Bearer realm="https://…/service/token",service="harbor-registry",…
# NOT a Basic challenge. So the check has to exchange the credential at the realm
# for a scoped token and retry. These three cases are the difference between a
# guard that works in production and one that refuses every promotion forever --
# a mode that "fails closed" and would therefore have looked fine in review.

# 14) Bearer challenge + a credential -> the token dance resolves, promote proceeds.
if start_mock_registry "team-sample/myapp-frontend:1.2.3,team-sample/myapp-backend:1.2.3" bearer; then
  R14="$(make_repo_at "127.0.0.1:${MOCK_PORT}/team-sample")"
  PK14="${R14}/.devops/chart/overlays/prod/kustomization.yaml"
  HARBOR_USERNAME=robot HARBOR_PASSWORD=secret \
    bash "${R14}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "bearer promote rc"       "${RC}" "0"
  assert_eq "bearer promote prod tag" "$(count_tag '1.2.3' "${PK14}")" "2"
  stop_mock_registry
else
  FAIL=$((FAIL+1)); echo "FAIL [bearer promote]: mock registry never started"
fi

# 15) ⚠ THE AB#34 REGRESSION, THROUGH THE REAL AUTH PATH. A guard that only ever
#     resolves 200s is half a guard: the token dance has to surface a 404 too.
#     This is case 9 again, but reached the way production reaches it.
if start_mock_registry "team-sample/myapp-frontend:1.2.3" bearer; then
  R15="$(make_repo_at "127.0.0.1:${MOCK_PORT}/team-sample")"
  PK15="${R15}/.devops/chart/overlays/prod/kustomization.yaml"
  BEFORE15="$(cat "${PK15}")"
  HARBOR_USERNAME=robot HARBOR_PASSWORD=secret \
    bash "${R15}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "bearer missing rc"           "${RC}" "1"
  assert_eq "bearer missing wrote nothing" "$(cat "${PK15}")" "${BEFORE15}"
  if grep -q 'myapp-backend:1\.2\.3' /tmp/promote.log; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1)); echo "FAIL [bearer missing names the image]: log did not cite myapp-backend:1.2.3"
  fi
  stop_mock_registry
else
  FAIL=$((FAIL+1)); echo "FAIL [bearer missing]: mock registry never started"
fi

# 16) No credential against a bearer registry. The realm hands out a token to
#     anyone, but an anonymous one carries no pull rights and the retry is 401
#     again -- live-confirmed behaviour. That must read as INCONCLUSIVE (refuse),
#     never as "missing" (which would blame the image for a credential problem and
#     send someone rebuilding a tag that was fine).
if start_mock_registry "team-sample/myapp-frontend:1.2.3,team-sample/myapp-backend:1.2.3" bearer; then
  R16="$(make_repo_at "127.0.0.1:${MOCK_PORT}/team-sample")"
  PK16="${R16}/.devops/chart/overlays/prod/kustomization.yaml"
  bash "${R16}/.devops/ci/promote.sh" staging prod >/tmp/promote.log 2>&1; RC=$?
  assert_eq "bearer anon rc"           "${RC}" "1"
  assert_eq "bearer anon wrote nothing" "$(count_tag '1.2.3' "${PK16}")" "0"
  if grep -qi 'could not confirm' /tmp/promote.log; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1)); echo "FAIL [bearer anon is inconclusive]: expected a 'could not confirm' refusal, not a 'does not exist' one"
  fi
  stop_mock_registry
else
  FAIL=$((FAIL+1)); echo "FAIL [bearer anon]: mock registry never started"
fi

fi

echo "== FINAL: $PASS passed, $FAIL failed =="
[ "${FAIL}" -eq 0 ]
