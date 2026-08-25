#!/usr/bin/env bash
# chart-render.test.sh — renders each overlay and asserts the invariants a
# kustomize JSON6902 patch can silently break.
#
# WHY THIS EXISTS: none of the checks below are visible by reading a diff, and
# every one of them corresponds to a failure this platform has actually seen:
#   * an Ingress patch replaces `tls.hosts` WHOLESALE, so adding a rule host in
#     base leaves an overlay with a router rule that has no matching TLS entry;
#   * a pod count that fits at steady state and does NOT fit during a rollout
#     surge -- the quota then rejects pods silently and the rollout just crawls,
#     which reads as "the cluster is slow today";
#   * a per-tenant storage quota consumed entirely by one PVC, so the OTHER
#     claim never binds and the symptom points at the wrong workload.
# Plus two that are specific to this app and would be expensive to get wrong:
#   * a mock model endpoint reachable in staging/prod (results silently faked);
#   * unsuspended nightly sweeps in a preview namespace (every open PR burning
#     provider credits three times a night).
#
# Requires: kubectl (for `kubectl kustomize`) and python3.
# Run: .devops/ci/chart-render.test.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASS=0; FAIL=0

pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found; skipping"; exit 0; }

# Per-env quotas, from the Crossplane Composition's $envs list (platform-infra
# platform-services/crossplane/apis/composition.yaml, as of #532).
# ⚠ KEEP IN SYNC with that file. If a platform quota changes and these do not,
# this suite goes green while the cluster rejects pods.
declare -A POD_QUOTA=(     [dev]=24 [staging]=24 [prod]=28 [preview]=0 )
declare -A STORAGE_QUOTA=( [dev]=5  [staging]=5  [prod]=20 [preview]=0 )

for env in dev staging prod preview; do
  echo "== ${env}"
  # The rendered manifest goes to a FILE, not to python's stdin: `python3 - <<PY`
  # already uses stdin for the script itself, so a pipe into it is silently
  # discarded and every check sees an empty document list.
  rendered_file="$(mktemp)"
  if ! kubectl kustomize "${REPO_ROOT}/.devops/chart/overlays/${env}" > "${rendered_file}" 2>/dev/null; then
    fail "${env}: kustomize build failed"
    rm -f "${rendered_file}"
    continue
  fi

  result="$(ENVNAME="${env}" RENDERED="${rendered_file}" \
            POD_QUOTA="${POD_QUOTA[$env]}" STORAGE_QUOTA="${STORAGE_QUOTA[$env]}" \
            python3 - <<'PY'
import os
import yaml

env = os.environ["ENVNAME"]
pod_quota = int(os.environ["POD_QUOTA"])
storage_quota = int(os.environ["STORAGE_QUOTA"])

with open(os.environ["RENDERED"]) as handle:
    docs = [d for d in yaml.safe_load_all(handle) if d]

checks = []


def check(ok, label):
    checks.append((bool(ok), label))


by_kind = {}
for doc in docs:
    by_kind.setdefault(doc["kind"], []).append(doc)

deploys = by_kind.get("Deployment", [])
statefulsets = by_kind.get("StatefulSet", [])
services = by_kind.get("Service", [])
cronjobs = by_kind.get("CronJob", [])
pvcs = by_kind.get("PersistentVolumeClaim", [])
ingress = next(iter(by_kind.get("Ingress", [])), None)
config = next((d for d in by_kind.get("ConfigMap", []) if d["metadata"]["name"] == "ida-llm-config"), None)

named = {d["metadata"]["name"]: d for d in deploys}

# ---- shape -----------------------------------------------------------------
check(len(deploys) == 5, f"5 Deployments (got {len(deploys)})")
check(len(statefulsets) == 1, f"1 StatefulSet (got {len(statefulsets)})")
check(len(cronjobs) == 3, f"3 CronJobs (got {len(cronjobs)})")
check(len(services) == 5, f"5 Services (got {len(services)})")
check(len(services) <= 15, "Services within the tenant quota of 15")

# Every Service must select a workload that exists -- a renamed component leaves
# a Service with no endpoints, which fails as a 502 at the Ingress, not at sync.
workload_components = {
    d["metadata"]["labels"]["app.kubernetes.io/component"] for d in deploys + statefulsets
}
for svc in services:
    component = svc["spec"]["selector"].get("app.kubernetes.io/component")
    check(component in workload_components,
          f"Service {svc['metadata']['name']} selects a real workload")

# The redis Service MUST stay headless or the StatefulSet's stable-identity
# guarantee is silently lost (it would load balance instead).
redis_svc = next((s for s in services if s["metadata"]["name"] == "ida-llm-redis"), None)
check(redis_svc and redis_svc["spec"].get("clusterIP") == "None", "redis Service is headless")

# ---- pod budget vs quota, WITH rollout surge -------------------------------
if pod_quota:
    steady = sum(d["spec"]["replicas"] for d in deploys)
    steady += sum(s["spec"]["replicas"] for s in statefulsets)
    # Default maxSurge is 25%, which rounds UP to 1 at any replica count, so
    # every RollingUpdate Deployment with >=1 replica transiently needs one
    # extra pod. `Recreate` (the object store) surges by 0.
    surge = sum(
        1 for d in deploys
        if d["spec"]["replicas"] > 0 and d["spec"].get("strategy", {}).get("type") != "Recreate"
    )
    # Three nightly sweeps can overlap a rollout.
    sweeps = sum(1 for c in cronjobs if not c["spec"].get("suspend", False))
    # dev alone also carries the per-team Adminer db-console pod.
    console = 1 if env == "dev" else 0
    peak = steady + surge + sweeps + console
    check(peak <= pod_quota,
          f"peak pods {peak} (steady {steady} + surge {surge} + sweeps {sweeps} + console {console}) "
          f"<= quota {pod_quota}")
    # And leave real headroom, not an exact fit -- the lesson from D-175/D-176/#526.
    check(peak <= pod_quota - 4, f"peak pods {peak} leaves >=4 headroom under {pod_quota}")

# ---- storage budget vs quota ------------------------------------------------
if storage_quota:
    def gib(value):
        return int(str(value).removesuffix("Gi"))

    total = sum(gib(p["spec"]["resources"]["requests"]["storage"]) for p in pvcs)
    # The redis volumeClaimTemplate is NOT a PVC object in the rendered output --
    # the StatefulSet controller creates it at runtime -- so count it explicitly.
    for sts in statefulsets:
        for tmpl in sts["spec"].get("volumeClaimTemplates", []):
            total += gib(tmpl["spec"]["resources"]["requests"]["storage"])
    check(total <= storage_quota,
          f"total storage {total}Gi (PVCs + volumeClaimTemplates) <= quota {storage_quota}Gi")

# ---- ingress ----------------------------------------------------------------
check(ingress is not None, "an Ingress is rendered")
if ingress:
    # The env ApplicationSet's SSO templatePatch targets `name: ida-llm`. Rename
    # it and dev/staging silently lose their auth gate -- no error, just an open app.
    check(ingress["metadata"]["name"] == "ida-llm", "Ingress is named 'ida-llm' (SSO patch target)")
    rule_hosts = {r["host"] for r in ingress["spec"]["rules"]}
    tls_hosts = {h for t in ingress["spec"]["tls"] for h in t["hosts"]}
    check(rule_hosts == tls_hosts, f"every rule host has a TLS entry (rules {rule_hosts}, tls {tls_hosts})")
    # Cloudflare Universal SSL covers exactly ONE label under capstone.uamishub.com.
    for host in rule_hosts:
        label = host.removesuffix(".capstone.uamishub.com")
        check("." not in label, f"host {host} is single-label (Cloudflare wildcard depth)")

# ---- the credit / campus-hardware safety switch -----------------------------
mock = named.get("ida-llm-mock-model")
mock_url = (config or {}).get("data", {}).get("MOCK_MODEL_BASE_URL", "")
if env in ("dev", "preview"):
    # BOTH halves required: a URL with no pod gives connection-refused; a pod
    # with no URL leaves the mock idle while real providers get billed.
    check(mock and mock["spec"]["replicas"] >= 1, f"{env}: mock-model is running")
    check(mock_url == "http://ida-llm-mock-model", f"{env}: MOCK_MODEL_BASE_URL points at the mock")
else:
    # THE expensive inverse. A mock quietly answering in staging or prod would
    # invalidate every stored benchmark result while everything looked healthy.
    check(mock and mock["spec"]["replicas"] == 0, f"{env}: mock-model is scaled to zero")
    check(mock_url == "", f"{env}: MOCK_MODEL_BASE_URL is empty (real providers)")

# Sparks stays unset everywhere until the egress route exists.
check((config or {}).get("data", {}).get("SPARKS_BASE_URL", "") == "",
      "SPARKS_BASE_URL is empty (no egress route yet)")

# ---- nightly sweeps in previews ---------------------------------------------
if env == "preview":
    # Left running, every open PR fires three benchmark sweeps a night against a
    # namespace with no quota. Single most expensive accident available here.
    check(all(c["spec"].get("suspend") is True for c in cronjobs),
          "preview: all CronJobs are suspended")
else:
    check(all(c["spec"].get("suspend", False) is False for c in cronjobs),
          f"{env}: CronJobs are active")

# ---- CronJob safety settings -------------------------------------------------
for cron in cronjobs:
    name = cron["metadata"]["name"]
    spec = cron["spec"]
    # Two overlapping sweeps writing the same run rows is corruption, not throughput.
    check(spec.get("concurrencyPolicy") == "Forbid", f"{name}: concurrencyPolicy Forbid")
    # Retained Jobs hold retained PODS, which count against the pods quota.
    check(spec.get("successfulJobsHistoryLimit", 3) <= 2, f"{name}: bounded success history")
    check(spec.get("failedJobsHistoryLimit", 1) <= 2, f"{name}: bounded failure history")

# ---- images -------------------------------------------------------------------
containers = [
    c
    for w in deploys + statefulsets
    for c in w["spec"]["template"]["spec"]["containers"]
    + w["spec"]["template"]["spec"].get("initContainers", [])
]
for container in containers:
    image = container["image"]
    check(":" in image.rsplit("/", 1)[-1], f"{container['name']}: image is tagged")
    check(not image.endswith(":latest"), f"{container['name']}: image is not :latest")
    # Every upstream image must come through the pull-through cache, or the
    # build/deploy path depends on Docker Hub rate limits.
    check(image.startswith("harbor.capstone.uamishub.com/"),
          f"{container['name']}: image is served from Harbor")

# ---- secrets are never literals ----------------------------------------------
for container in containers:
    for entry in container.get("env", []):
        if entry["name"].endswith(("_KEY", "_SECRET", "_URL", "_TOKEN", "_PASSWORD")):
            if entry["name"] in ("DATABASE_URL",) or entry["name"].endswith(("_KEY", "_TOKEN", "_PASSWORD")):
                check("value" not in entry,
                      f"{container['name']}: {entry['name']} comes from a secretKeyRef, not a literal")

for ok, label in checks:
    print(("PASS " if ok else "FAIL ") + label)
PY
  )"

  while IFS= read -r line; do
    case "${line}" in
      PASS\ *) pass "${line#PASS }" ;;
      FAIL\ *) fail "${line#FAIL }" ;;
      *) [ -n "${line}" ] && echo "  ${line}" ;;
    esac
  done <<< "${result}"

  rm -f "${rendered_file}"
done

echo "== FINAL: ${PASS} passed, ${FAIL} failed =="
[ "${FAIL}" -eq 0 ]
