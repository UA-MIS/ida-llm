#!/usr/bin/env bash
# promote.sh — the click-to-promote seam (promotion-model redesign, see
# artifacts/design/promotion-model.md in platform-infra). Reads the image tag
# CURRENTLY LIVE in <from>'s overlay and writes that SAME tag into <to>'s
# overlay — no fresh build, no code edit, no new git tag. This is what
# .github/workflows/promote-to-prod.yaml runs on workflow_dispatch: the human
# clicking "Run workflow" IS the gate; this script does the bump.
#
# Reuses bump-image.sh for the actual write (+ optional commit) so there is
# ONE write path for every env, whether driven by a fresh build (bump-image.sh
# directly) or by re-pointing at an already-live version (this script).
#
# Before writing anything it VERIFIES every component's tag actually exists in
# the registry (AB#34) — see the block below for why a consistent overlay is not
# the same thing as a buildable one.
#
# Usage:
#   promote.sh <from-env> <to-env>          # dry run: print the live tag, don't write
#   COMMIT=1 promote.sh staging prod        # write + commit (the GitOps signal)
#
# Environment:
#   COMMIT=1                     commit the write (the GitOps signal)
#   HARBOR_USERNAME/_PASSWORD    credential for the registry probe; otherwise the
#                                runner's docker config.json is reused
#   DOCKER_CONFIG                directory holding that config.json (default
#                                /kaniko/.docker, then ~/.docker)
#   ALLOW_UNVERIFIED_PROMOTE=1   skip the registry check, loudly. The escape
#                                hatch, not the default — read the block below.
#   REGISTRY_HTTP_CLIENT         force `curl` or `python3` (default: whichever exists)
#   REGISTRY_SCHEME              default https; loopback hosts are always http
#   REGISTRY_PROBE_TIMEOUT       per-request seconds (default 10)
set -euo pipefail

FROM="${1:-}"
TO="${2:-}"
if [ -z "${FROM}" ] || [ -z "${TO}" ]; then
  echo "usage: $0 <from-env> <to-env>" >&2
  exit 2
fi
if [ "${FROM}" = "${TO}" ]; then
  echo "from and to must differ (got '${FROM}' twice)" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEVOPS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${DEVOPS_DIR}/.." && pwd)"
PROMOTION="${DEVOPS_DIR}/promotion.yaml"

[ -f "${PROMOTION}" ] || { echo "promotion.yaml not found at ${PROMOTION}" >&2; exit 1; }

# Resolve env -> overlay from the promotion contract. Same read as
# bump-image.sh's read_overlay (yq-preferred; sed/awk fallback for a bare runner).
read_overlay() {
  local env="$1"
  if command -v yq >/dev/null 2>&1; then
    yq -r ".environments.${env}.overlay" "${PROMOTION}"
  else
    awk -v env="${env}" '
      $0 ~ "^[[:space:]]+" env ":[[:space:]]*$" { inblk=1; next }
      inblk && /^[[:space:]]+[a-z]+:[[:space:]]*$/ && $0 !~ "^[[:space:]]{6,}" { inblk=0 }
      inblk && /overlay:/ { sub(/^[^:]*:[[:space:]]*/, ""); sub(/[[:space:]]*#.*$/, ""); gsub(/^[ \t]+|[ \t]+$|"/, ""); print; exit }
    ' "${PROMOTION}"
  fi
}

FROM_OVERLAY="$(read_overlay "${FROM}")"
if [ -z "${FROM_OVERLAY}" ] || [ "${FROM_OVERLAY}" = "null" ]; then
  echo "no overlay mapping for env '${FROM}' in promotion.yaml" >&2
  exit 1
fi
FROM_KUSTOMIZATION="${REPO_DIR}/${FROM_OVERLAY}/kustomization.yaml"
[ -f "${FROM_KUSTOMIZATION}" ] || { echo "overlay kustomization not found: ${FROM_KUSTOMIZATION}" >&2; exit 1; }

# Read the LIVE tag out of <from>'s overlay. bump-image.sh's invariant is that
# every component's images[].newTag is set to the SAME tag in one write, so
# read the first entry and refuse if any entry disagrees — that means <from>
# is in a hand-edited / partially-bumped state and promoting it would ship an
# inconsistent set of component versions.
if command -v yq >/dev/null 2>&1; then
  LIVE_TAG="$(yq -r '.images[0].newTag' "${FROM_KUSTOMIZATION}")"
  MISMATCHED="$(LIVE_TAG="${LIVE_TAG}" yq -r '[.images[].newTag] | map(select(. != strenv(LIVE_TAG))) | length' "${FROM_KUSTOMIZATION}")"
else
  # Strip the newTag: prefix, any trailing comment, then any ONE layer of matching
  # surrounding quotes (bump-image.sh's sed fallback always double-quotes its writes;
  # single-quote handling is defensive). Without this, a quoted staging value like
  # `newTag: "1.0.0"` extracts LIVE_TAG=`"1.0.0"` (quotes included) -- bump-image.sh's
  # sed fallback then re-quotes that verbatim into prod as `newTag: ""1.0.0""`, invalid
  # YAML that leaves prod's Application ComparisonError/unsyncable (FIX-23, source-
  # confirmed against a live promote run). MATCHING_COUNT below must compare against
  # the SAME bare value kustomization.yaml actually stores (quoted), so it re-wraps
  # LIVE_TAG in double quotes for the grep -- see the comment there.
  LIVE_TAG="$(grep -m1 -E '^[[:space:]]*newTag:' "${FROM_KUSTOMIZATION}" | sed -E 's/^[[:space:]]*newTag:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/')"
  TOTAL_COUNT="$(grep -cE '^[[:space:]]*newTag:' "${FROM_KUSTOMIZATION}")"
  # LIVE_TAG is now bare (quotes stripped above); match it against the overlay's stored
  # form, which may be bare (e.g. `v1.2.3`) or double-quoted (e.g. an all-numeric sha,
  # meow-dev #341) -- so check for either rendering, not just the bare one.
  MATCHING_COUNT="$(grep -cE "^[[:space:]]*newTag:[[:space:]]*\"?${LIVE_TAG}\"?\$" "${FROM_KUSTOMIZATION}")"
  MISMATCHED=$(( TOTAL_COUNT - MATCHING_COUNT ))
fi

if [ -z "${LIVE_TAG}" ] || [ "${LIVE_TAG}" = "null" ]; then
  echo "could not read a live tag from ${FROM_KUSTOMIZATION}" >&2
  exit 1
fi
if [ "${MISMATCHED}" != "0" ]; then
  echo "${FROM}'s components do not all share one tag — refusing to promote an inconsistent state (check ${FROM_KUSTOMIZATION})" >&2
  exit 1
fi

echo "==> ${FROM} is live at ${LIVE_TAG}"

# ── AB#34: THE TAG MUST EXIST IN THE REGISTRY BEFORE WE WRITE IT ────────────
#
# THE BUG THIS CLOSES. Everything above proves <from>'s overlay is internally
# consistent — every component names the SAME tag. It proves nothing about
# whether that tag was ever BUILT. `ida-llm-agile:be4e3d9` is the live proof:
# the agile component postdates commit be4e3d9, so no build ever pushed that
# image, yet dev's overlay named it like any other. A dev→prod promote copied
# it verbatim and pinned prod to an image that cannot be pulled — the board came
# up ImagePullBackOff, and the first signal was a user reporting a dead page.
#
# promotion-writers.test.sh cannot catch this class: it asserts a WRITER exists
# and is ref-gated, and the writer was present and correct. The tag was wrong.
# Only the registry knows that, so we ask it.
#
# FAIL BEFORE MUTATE. Every component is checked BEFORE bump-image.sh is
# invoked, so a refusal leaves <to>'s overlay byte-identical. A guard that
# refuses halfway through a write leaves prod in a state nobody chose.
#
# ⚠ INCONCLUSIVE IS A REFUSAL, NOT A PASS. If the probe cannot reach the
# registry, has no credential for a private project, or gets a 5xx, this script
# refuses. "I could not check" must never render as "it is fine" — that is
# precisely the silent-pass behaviour being removed here, and the same stance
# build-and-push.yaml already takes when the push credential is missing ("fail
# CLOSED rather than pushing unauthenticated"). ALLOW_UNVERIFIED_PROMOTE=1 is
# the documented, deliberately loud escape hatch for an operator who has
# confirmed the images another way and needs to ship anyway.
PROBE_TIMEOUT="${REGISTRY_PROBE_TIMEOUT:-10}"
# Every manifest media type a Harbor-hosted image can present. Omitting these
# makes a registry answer 404 for an image that exists but is an OCI index —
# which would be a FALSE ALARM, and a guard that cries wolf gets switched off.
ACCEPT_MANIFESTS='application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json, */*'

# Which HTTP client to use. BOTH are needed, and neither alone is enough:
# the promote runner (node:24.16-trixie, via buildpack-deps) always has curl but
# not necessarily python3, while ci.yml's seam-test job runs python:3.12-slim,
# which has python3 and deliberately NO curl (that job's own comment explains
# why it cannot apt-get one: these runners have egress on :443 only). Override
# with REGISTRY_HTTP_CLIENT to pin one — the suite uses it to exercise both.
HTTP_CLIENT="${REGISTRY_HTTP_CLIENT:-}"
if [ -z "${HTTP_CLIENT}" ]; then
  if command -v curl >/dev/null 2>&1; then HTTP_CLIENT=curl
  elif command -v python3 >/dev/null 2>&1; then HTTP_CLIENT=python3
  else HTTP_CLIENT=none
  fi
fi

# https everywhere EXCEPT loopback, which is plain http — the same rule container
# runtimes apply to localhost registries, and what lets the test suite stand up a
# real registry on 127.0.0.1 instead of mocking out this function (a mock shaped
# to agree with the caller would have passed against the be4e3d9 bug too).
registry_scheme() {
  case "$1" in
    localhost|localhost:*|127.0.0.1|127.0.0.1:*|\[::1\]|\[::1\]:*) printf 'http' ;;
    *) printf '%s' "${REGISTRY_SCHEME:-https}" ;;
  esac
}

b64() { printf '%s' "$1" | base64 | tr -d '\n'; }

# The Basic credential for <host>, or empty. Explicit env wins; otherwise reuse
# the docker config the runner already mounts (the harbor robot). Empty is NOT an
# error here — public projects answer an anonymous probe, and a 401 from a private
# one is caught downstream as "inconclusive" rather than guessed at.
basic_auth_for() {
  local host="$1" cfg
  if [ -n "${HARBOR_USERNAME:-}" ] && [ -n "${HARBOR_PASSWORD:-}" ]; then
    b64 "${HARBOR_USERNAME}:${HARBOR_PASSWORD}"
    return 0
  fi
  for cfg in "${DOCKER_CONFIG:-/kaniko/.docker}/config.json" "${HOME:-/root}/.docker/config.json"; do
    [ -s "${cfg}" ] || continue
    if command -v python3 >/dev/null 2>&1; then
      python3 - "${host}" "${cfg}" <<'PY' && return 0
import base64, json, sys
host, path = sys.argv[1], sys.argv[2]
try:
    auths = (json.load(open(path)) or {}).get("auths") or {}
except Exception:
    raise SystemExit(1)
for key in (host, "https://" + host, "http://" + host, "https://" + host + "/v1/"):
    entry = auths.get(key)
    if not entry:
        continue
    if entry.get("auth"):
        print(entry["auth"].strip())
        raise SystemExit(0)
    user, password = entry.get("username"), entry.get("password")
    if user and password:
        print(base64.b64encode(f"{user}:{password}".encode()).decode())
        raise SystemExit(0)
raise SystemExit(1)
PY
    else
      # No python3: a tolerant flattened-JSON read of `"<host>":{..."auth":"<b64>"}`.
      local found
      found="$(tr -d ' \n' < "${cfg}" | sed -n 's/.*"'"${host}"'":{[^}]*"auth":"\([^"]*\)".*/\1/p' | head -1)" || found=""
      if [ -n "${found}" ]; then printf '%s' "${found}"; return 0; fi
    fi
  done
  return 1
}

# The python3 transport, as a string (`python3 -c "${PY_PROBE}"`, NOT a heredoc:
# a heredoc whose body would sit outside an enclosing $( ) is an unterminated
# here-document -- bash warns and reads the rest of THIS FILE as the script).
# TLS verification stays ON: a promote that trusts any certificate is a promote
# that can be answered by anything on the path.
PY_PROBE='
import os, urllib.error, urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every 3xx instead of following it.

    ⚠ THIS IS A CREDENTIAL CONTAINMENT CONTROL, NOT A TIDINESS PREFERENCE.
    urllib re-sends every header except Content-Length/Content-Type when it
    follows a redirect, INCLUDING Authorization, and it does so ACROSS HOSTS.
    So a same-host token realm answering 302 walks the harbor robot straight
    past the same-host check in bearer_token_for -- reproduced end to end on
    CPython 3.12. curl (the prod transport) never followed redirects here
    because it is invoked without -L; this makes the CI transport agree.
    Returning None turns the 3xx into an HTTPError, so it lands as a non
    200/404 status and the caller classifies it inconclusive -> refuse.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


mode = os.environ.get("PROBE_MODE", "status")
request = urllib.request.Request(os.environ["PROBE_URL"], method="GET")
request.add_header("Accept", os.environ["PROBE_ACCEPT"])
if os.environ.get("PROBE_AUTH"):
    request.add_header("Authorization", os.environ["PROBE_AUTH"])
try:
    opener = urllib.request.build_opener(NoRedirect)
    response = opener.open(request, timeout=float(os.environ["PROBE_TIMEOUT_S"]))
    status, headers, body = response.status, response.headers, response.read()
except urllib.error.HTTPError as exc:
    status, headers, body = exc.code, exc.headers, b""
except Exception:
    status, headers, body = 0, None, b""
if mode == "status":
    print("%03d" % status)
elif mode == "challenge":
    print(headers.get("WWW-Authenticate", "") if headers else "")
else:
    print(body.decode("utf-8", "replace"))
'

# One GET, three things we might want from it. `auth` is the FULL header value
# ("Basic ..." or "Bearer ..."), empty for anonymous. Never fails the script: an
# unreachable registry is a RESULT (classified as inconclusive by the caller),
# not a stack of set -e surprises here.
http_get() {
  local url="$1" auth="${2:-}" mode="${3:-status}" out=""
  case "${HTTP_CLIENT}" in
    curl)
      # ⚠ NO -L, DELIBERATELY. Following a redirect would forward the
      # Authorization header off-host and defeat bearer_token_for's same-host
      # check (see the NoRedirect handler in PY_PROBE for the same control on
      # the other transport). A 3xx must stay a 3xx so it reads as inconclusive.
      local args=(-s --connect-timeout 5 -m "${PROBE_TIMEOUT}" -H "Accept: ${ACCEPT_MANIFESTS}")
      [ -n "${auth}" ] && args+=(-H "Authorization: ${auth}")
      case "${mode}" in
        status)    out="$(curl "${args[@]}" -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null)" || out="" ;;
        challenge) out="$(curl "${args[@]}" -D - -o /dev/null "${url}" 2>/dev/null \
                          | tr -d '\r' | sed -n 's/^[Ww][Ww][Ww]-[Aa]uthenticate:[[:space:]]*//p' | head -1)" || out="" ;;
        body)      out="$(curl "${args[@]}" "${url}" 2>/dev/null)" || out="" ;;
      esac
      ;;
    python3)
      out="$(PROBE_URL="${url}" PROBE_AUTH="${auth}" PROBE_TIMEOUT_S="${PROBE_TIMEOUT}" \
             PROBE_ACCEPT="${ACCEPT_MANIFESTS}" PROBE_MODE="${mode}" python3 -c "${PY_PROBE}" 2>/dev/null)" || out=""
      ;;
  esac
  printf '%s' "${out}"
}

http_status() {
  local out; out="$(http_get "$1" "${2:-}" status)"
  case "${out}" in
    ''|*[!0-9]*) printf '000' ;;
    *) printf '%s' "${out}" ;;
  esac
}

# ⚠ THE REGISTRY DOES NOT WANT OUR BASIC HEADER -- IT WANTS A TOKEN.
#
# Verified against the live registry, not assumed: harbor.capstone.uamishub.com
# answers an anonymous manifest GET with
#   401 WWW-Authenticate: Bearer realm="https://…/service/token",
#                                service="harbor-registry",
#                                scope="repository:ida-llm/ida-llm-agile:pull"
# i.e. the standard OCI token flow, NOT Basic. A check that only knew how to send
# Basic would read every real image as 401 -> inconclusive -> refuse, and the
# guard would block every promotion instead of the broken ones. That is the
# failure this function exists to avoid, so the dance is implemented properly:
# exchange the credential at the realm for a scoped token, then retry.
#
# The credential goes ONLY to a realm on the SAME HOST as the registry we are
# already talking to. The challenge is attacker-influenced data -- honouring an
# arbitrary realm would mail the harbor robot to whatever host it names.
bearer_token_for() {
  local host="$1" repo="$2" auth="$3" challenge realm service scope realm_host body token
  challenge="$(http_get "$4" "" challenge)"
  case "${challenge}" in
    [Bb]earer*) ;;
    *) return 1 ;;
  esac
  realm="$(printf '%s' "${challenge}"   | sed -n 's/.*realm="\([^"]*\)".*/\1/p')"
  service="$(printf '%s' "${challenge}" | sed -n 's/.*service="\([^"]*\)".*/\1/p')"
  scope="$(printf '%s' "${challenge}"   | sed -n 's/.*scope="\([^"]*\)".*/\1/p')"
  [ -n "${realm}" ] || return 1
  [ -n "${scope}" ] || scope="repository:${repo}:pull"
  realm_host="${realm#*://}"; realm_host="${realm_host%%/*}"
  if [ "${realm_host}" != "${host}" ]; then
    echo "    !       refusing to send the registry credential to a token realm on a different host (${realm_host} != ${host})" >&2
    return 1
  fi
  body="$(http_get "${realm}?service=${service}&scope=${scope}" "${auth}" body)"
  # ⚠ TOLERATE WHITESPACE AROUND THE JSON COLON. The live Harbor answers compact
  # (`{"token":"ey…"}`), but json.dumps and several registries emit `{"token": "…"}`
  # -- and a token regex that silently misses turns into "no token" -> inconclusive
  # -> refuse, i.e. a guard that blocks every promotion and blames the registry.
  token="$(printf '%s' "${body}" | sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
  [ -n "${token}" ] || token="$(printf '%s' "${body}" | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
  [ -n "${token}" ] || return 1
  printf '%s' "${token}"
}

# exists | missing | inconclusive:<code>, for one <host>/<repo>:<tag>.
#
# Order: anonymous GET (public projects and 404s resolve here for free) ->
# bearer token exchange (what the real Harbor requires) -> Harbor's own
# /api/v2.0 artifact read with Basic (for a deployment that fronts /v2/
# differently). Anything that is neither a definite 200 nor a definite 404 stays
# inconclusive on purpose.
tag_state() {
  local host="$1" repo="$2" tag="$3" auth="$4" scheme url code token project rest
  scheme="$(registry_scheme "${host}")"
  url="${scheme}://${host}/v2/${repo}/manifests/${tag}"

  code="$(http_status "${url}" "")"
  case "${code}" in
    200) printf 'exists';  return 0 ;;
    404) printf 'missing'; return 0 ;;
  esac

  if [ "${code}" = "401" ] || [ "${code}" = "403" ]; then
    if token="$(bearer_token_for "${host}" "${repo}" "${auth:+Basic ${auth}}" "${url}")" && [ -n "${token}" ]; then
      code="$(http_status "${url}" "Bearer ${token}")"
      case "${code}" in
        200) printf 'exists';  return 0 ;;
        404) printf 'missing'; return 0 ;;
      esac
    fi
    # Some Harbor deployments accept Basic on /v2/ directly; cheap to try.
    if [ -n "${auth}" ]; then
      code="$(http_status "${url}" "Basic ${auth}")"
      case "${code}" in
        200) printf 'exists';  return 0 ;;
        404) printf 'missing'; return 0 ;;
      esac
    fi
  fi

  # Harbor's REST API, which does take Basic. Nested repository names must arrive
  # double-encoded.
  case "${repo}" in
    */*)
      project="${repo%%/*}"
      rest="$(printf '%s' "${repo#*/}" | sed 's|/|%252F|g')"
      code="$(http_status "${scheme}://${host}/api/v2.0/projects/${project}/repositories/${rest}/artifacts/${tag}" "${auth:+Basic ${auth}}")"
      case "${code}" in
        200) printf 'exists';  return 0 ;;
        404) printf 'missing'; return 0 ;;
      esac
      ;;
  esac

  printf 'inconclusive:%s' "${code}"
}

# The component image refs to check: every `newName` in <from>'s overlay, each at
# LIVE_TAG (the block above already proved they all carry that one tag).
# ⚠ `|| true` ON BOTH READS, AND IT IS LOAD-BEARING. Under `set -e -o pipefail`
# a grep that matches NOTHING exits 1 and takes the whole script with it -- so
# the "could not read any images[].newName" message three lines below could never
# print, and an overlay with no newName entries showed up on the prod button as a
# bare `exit 1` with no explanation. The empty-check IS the error path; let it run.
if command -v yq >/dev/null 2>&1; then
  IMAGE_NAMES="$(yq -r '.images[].newName' "${FROM_KUSTOMIZATION}" 2>/dev/null || true)"
else
  IMAGE_NAMES="$(grep -E '^[[:space:]]*newName:' "${FROM_KUSTOMIZATION}" \
                 | sed -E 's/^[[:space:]]*newName:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//; s/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/' || true)"
fi
# yq prints the literal `null` for an entry with no newName -- one line per entry,
# so this is a filter, not an equality test. Blank lines go too: what remains is
# exactly the set of real image names, and "nothing remains" is the error case below.
IMAGE_NAMES="$(printf '%s\n' "${IMAGE_NAMES}" | sed '/^null$/d; /^[[:space:]]*$/d' || true)"
if [ -z "${IMAGE_NAMES}" ]; then
  echo "could not read any images[].newName from ${FROM_KUSTOMIZATION} — refusing to promote a set of components I cannot verify" >&2
  exit 1
fi

if [ "${ALLOW_UNVERIFIED_PROMOTE:-}" = "1" ]; then
  echo "WARNING: ALLOW_UNVERIFIED_PROMOTE=1 — the registry check is being SKIPPED." >&2
  echo "WARNING: the following images are going into ${TO} UNVERIFIED; if any was never built," >&2
  echo "WARNING: ${TO} will come up ImagePullBackOff (AB#34):" >&2
  printf '%s\n' "${IMAGE_NAMES}" | while IFS= read -r n; do
    [ -n "${n}" ] && echo "WARNING:   ${n}:${LIVE_TAG}" >&2
  done
else
  if [ "${HTTP_CLIENT}" = "none" ]; then
    echo "cannot verify ${FROM}'s tags: no curl and no python3 on PATH, so the registry cannot be reached." >&2
    echo "Install either, or re-run with ALLOW_UNVERIFIED_PROMOTE=1 if you have confirmed the images exist another way." >&2
    exit 1
  fi
  echo "==> verifying every component is present in the registry at ${LIVE_TAG} (via ${HTTP_CLIENT})"
  MISSING=""
  UNKNOWN=""
  while IFS= read -r NEWNAME; do
    [ -n "${NEWNAME}" ] || continue
    case "${NEWNAME}" in
      */*) ;;
      *)
        UNKNOWN="${UNKNOWN}
  ${NEWNAME}:${LIVE_TAG} (no registry host in newName)"
        continue ;;
    esac
    HOST="${NEWNAME%%/*}"
    REPO="${NEWNAME#*/}"
    AUTH="$(basic_auth_for "${HOST}" || true)"
    STATE="$(tag_state "${HOST}" "${REPO}" "${LIVE_TAG}" "${AUTH}")"
    case "${STATE}" in
      exists)  echo "    ok      ${NEWNAME}:${LIVE_TAG}" ;;
      missing) echo "    MISSING ${NEWNAME}:${LIVE_TAG}"
               MISSING="${MISSING}
  ${NEWNAME}:${LIVE_TAG}" ;;
      *)       echo "    ?       ${NEWNAME}:${LIVE_TAG} (${STATE})"
               UNKNOWN="${UNKNOWN}
  ${NEWNAME}:${LIVE_TAG} (HTTP ${STATE#inconclusive:})" ;;
    esac
  done <<EOF
${IMAGE_NAMES}
EOF

  if [ -n "${MISSING}" ]; then
    echo "" >&2
    echo "REFUSING TO PROMOTE ${FROM} -> ${TO}: these images do not exist in the registry:${MISSING}" >&2
    echo "" >&2
    echo "${TO} has NOT been written. Promoting this tag would pin ${TO} to an image that cannot" >&2
    echo "be pulled (ImagePullBackOff). This usually means ${FROM} names a tag from before that" >&2
    echo "component existed, or its build leg failed while the others succeeded — rebuild ${FROM}" >&2
    echo "at a tag every component actually has, then promote that." >&2
    exit 1
  fi
  if [ -n "${UNKNOWN}" ]; then
    echo "" >&2
    echo "REFUSING TO PROMOTE ${FROM} -> ${TO}: the registry could not confirm these images:${UNKNOWN}" >&2
    echo "" >&2
    echo "${TO} has NOT been written. \"Could not check\" is not \"it is fine\" (AB#34). A 401/403 means" >&2
    echo "no usable credential was found — set HARBOR_USERNAME/HARBOR_PASSWORD, or point DOCKER_CONFIG" >&2
    echo "at a directory whose config.json holds the harbor robot. HTTP 000 means the registry was" >&2
    echo "unreachable from this runner. If you have confirmed the images exist another way, re-run" >&2
    echo "with ALLOW_UNVERIFIED_PROMOTE=1." >&2
    exit 1
  fi
fi

echo "==> promoting ${LIVE_TAG} to ${TO}"

# Hand off to bump-image.sh for the write (+ COMMIT=1 commit). COMMIT, if set
# in this process's environment, is inherited by the child automatically.
# Invoke via `sh` (not a direct exec) so it works even when the shipped script lacks the
# execute bit: the compose action ships .devops/ci VERBATIM via fs.outputFile at mode 644,
# so a direct `"${SCRIPT_DIR}/bump-image.sh"` fails "Permission denied" in a real tenant
# repo. The workflow + RUNBOOK invoke every script as `sh …` for the same reason.
# `bash`, NOT `sh` — see the same note in seed-initial-envs.sh. bump-image.sh is
# a bash script (`set -euo pipefail`), which dash refuses to start. Defensive
# rather than a fix for a live break (the platform runners cope with `sh`); it
# just honours the declared interpreter. Still no +x bit required, which is what
# the `sh` form was working around.
bash "${SCRIPT_DIR}/bump-image.sh" "${TO}" "${LIVE_TAG}"
