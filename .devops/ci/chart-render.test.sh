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
#   * an unsuspended nightly sweep in ANY namespace -- the sweeps are currently
#     frozen in every environment, and a silent un-suspend puts an unattended
#     credit-spending job back on a timer with nobody watching.
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
expected_deploys = 5
check(len(deploys) == expected_deploys,
      f"{expected_deploys} Deployments (got {len(deploys)})")
check(len(statefulsets) == 1, f"1 StatefulSet (got {len(statefulsets)})")
check(len(cronjobs) == 3, f"3 CronJobs (got {len(cronjobs)})")
expected_services = 6
check(len(services) == expected_services,
      f"{expected_services} Services (got {len(services)})")
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

# ---- the dev-only demo overrides, asserted BOTH directions ------------------
# The populated-demo dev site adds synthetic demo models (models.dev.yaml), demo
# curriculum (majors.dev.yaml / slo.dev.yaml), a union task catalogue
# (/app/tasks-all) and the frontend demo-unit gate (IDA_DEMO_CURRICULUM). Every
# one is honest ONLY because it is dev-only: dev names it, and staging/prod must
# NEVER set it, or demo models/structure reach the production environment. Same
# shape as the mock safety switch above — thrown in dev, provably OFF elsewhere.
DEV_ONLY_OVERRIDES = {
    "IDA_MODELS_FILE": "/app/models.dev.yaml",
    "IDA_MAJORS_FILE": "/app/curriculum/majors.dev.yaml",
    "IDA_CURRICULUM_FILE": "/app/curriculum/slo.dev.yaml",
    "IDA_TASKS_DIR": "/app/tasks-all",
    "IDA_DEMO_CURRICULUM": "1",
}
cfg_data = (config or {}).get("data", {})
for key, dev_value in DEV_ONLY_OVERRIDES.items():
    got = cfg_data.get(key, "")
    if env == "dev":
        check(got == dev_value, f"{env}: {key} is set to the dev-only value ({dev_value})")
    else:
        check(got == "",
              f"{env}: {key} is unset (loads committed registry/curriculum/tasks, no demo data)")

# ---- nightly sweeps in previews ---------------------------------------------
# ⚠ THIS ASSERTION WAS INVERTED FOR dev/staging/prod. It used to require that
# the sweeps were ACTIVE outside preview. They are now suspended EVERYWHERE, by
# `suspend: true` in base/cronjobs.yaml -- a deliberate freeze on the only
# unattended credit-spend surface in this chart, held until the team decides to
# turn continuous benchmarking back on.
#
# The check is kept (rather than deleted) because it still guards the thing worth
# guarding -- it now catches an ACCIDENTAL un-suspend, and it catches a PARTIAL
# one, where a patch or a merge leaves one of the three firing while the other two
# look correctly off. A silently-resumed sweep bills on a timer with nobody
# watching; that is exactly the failure this suite exists to make loud.
#
# TO RE-ENABLE: flip `suspend` in .devops/chart/base/cronjobs.yaml AND change the
# dev/staging/prod branch below back to asserting the sweeps are active. Two
# deliberate edits, by design -- see the header comment in base/cronjobs.yaml.
if env == "preview":
    # Left running, every open PR fires three benchmark sweeps a night against a
    # namespace with no quota. Single most expensive accident available here.
    # Preview is suspended by its OWN overlay patch as well as by base, so it
    # stays off even after base's suspend is flipped back for the real envs.
    check(all(c["spec"].get("suspend") is True for c in cronjobs),
          "preview: all CronJobs are suspended")
else:
    check(all(c["spec"].get("suspend") is True for c in cronjobs),
          f"{env}: all CronJobs are suspended (nightly sweeps frozen)")

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
        if entry["name"].endswith(("_KEY", "_SECRET", "_URL", "_TOKEN", "_TOKENS", "_PASSWORD")):
            if entry["name"] in ("DATABASE_URL",) or entry["name"].endswith(("_KEY", "_SECRET", "_TOKEN", "_TOKENS", "_PASSWORD")):
                check("value" not in entry,
                      f"{container['name']}: {entry['name']} comes from a secretKeyRef, not a literal")

# ---- the agile board: PROD ONLY, AND EXACTLY ONE CLAIMANT FOR ITS HOST ---------
# This block is a REGRESSION TEST. The board originally lived in base/, so its
# Ingress HOST RULE rendered into all three environments -- three Ingress objects
# claiming ida-agile.capstone.uamishub.com, which made Traefik pick among them
# non-deterministically. Only prod had a backend, and dev/staging carry the tenant
# SSO middlewares, so the board worked or 302'd to a DIFFERENT app's auth proxy
# depending on which object won. Scaling the Deployment to 0 elsewhere did not
# help: a host rule is claimed by the RULE, not by whether it has endpoints.
agile = named.get("ida-llm-agile")
agile_ingresses = [
    i for i in by_kind.get("Ingress", [])
    if any(r["host"] == "ida-agile.capstone.uamishub.com" for r in i["spec"]["rules"])
]
# THE BOARD IS GONE FROM THIS CHART, IN EVERY ENVIRONMENT. It used to be
# prod-only, and this block used to assert prod HAD it. The team migrated to the
# platform board (`ida-llm-agile.capstone.uamishub.com`, namespace `agile`), so
# the assertion is inverted rather than deleted: what mattered was never "the
# board exists", it was that exactly one thing claims that host. Zero claimants
# is the correct count now, and this still catches the original defect -- a
# stale host rule outliving the workload it pointed at.
check(agile is None, f"{env}: no agile Deployment (the board moved to the platform chart)")
check(not agile_ingresses,
      f"{env}: NOTHING claims the old agile host (got {len(agile_ingresses)})")

if ingress:
    # The app's own Ingress must never carry the board's host.
    app_hosts = [r["host"] for r in ingress["spec"]["rules"]]
    check("ida-agile.capstone.uamishub.com" not in app_hosts,
          f"{env}: the app Ingress does NOT claim the agile host (got {app_hosts})")

# ---- servicemonitors + autoscaling ---------------------------------------------
monitors = {d["metadata"]["name"] for d in by_kind.get("ServiceMonitor", [])}
check(monitors == {"ida-llm-api", "ida-llm-runner", "ida-llm-frontend"},
      f"3 ServiceMonitors (got {sorted(monitors)})")

# ⚠ Every scraped port must be a CONTAINER port named `http`: the
# Composition-owned netpol allows ingress from `monitoring` on `port: http` only,
# and a NetworkPolicy port name matches the CONTAINER port name. A scrape blocked
# that way reads as a broken exporter, not a firewall.
container_port_names = {
    p["name"]
    for w in deploys + statefulsets
    for c in w["spec"]["template"]["spec"]["containers"]
    for p in c.get("ports", [])
}
runner = named.get("ida-llm-runner")
if runner:
    names = {p["name"] for c in runner["spec"]["template"]["spec"]["containers"]
             for p in c.get("ports", [])}
    check("http" in names,
          f"runner's metrics container port is named 'http' so the netpol admits the scrape (got {sorted(names)})")

hpas = by_kind.get("HorizontalPodAutoscaler", [])
if env == "preview":
    # Its minReplicas of 2 would OVERRIDE the replicas:1 patch and run two
    # runners in every open PR's namespace, against a quota sized for one of
    # everything. A preview is a review aid; there is nothing to autoscale.
    check(not hpas, f"preview: the HPA is removed (got {[h['metadata']['name'] for h in hpas]})")
else:
    check(len(hpas) == 1 and hpas[0]["spec"]["scaleTargetRef"]["name"] == "ida-llm-runner",
          "exactly one HPA, targeting the runner")
    if hpas:
        check(hpas[0]["spec"]["minReplicas"] == 2 and hpas[0]["spec"]["maxReplicas"] == 4,
              "HPA bounds are 2-4 (the spec's stated runner range)")

pdbs = by_kind.get("PodDisruptionBudget", [])
for pdb in pdbs:
    # minAvailable on a scaled-down deployment makes the node UNDRAINABLE and
    # hangs a cluster upgrade with no obvious cause.
    check("maxUnavailable" in pdb["spec"],
          f"{pdb['metadata']['name']}: PDB uses maxUnavailable, not minAvailable")

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

# ── THE PROMOTION INVARIANT ──────────────────────────────────────────────────
# Within ONE overlay every images[].newTag must agree. bump-image.sh rewrites
# them all in a single pass and promote.sh REFUSES to promote when they disagree
# -- so a component whose entry was forgotten or hand-edited does not fail here,
# it fails much later at the next promotion, with a tag-mismatch error that
# points nowhere near the missing line. (Nearly shipped exactly that when the
# agile component was added while CI had already bumped the other two.)
echo "== promotion invariant (one tag per overlay)"
for env in dev staging prod preview; do
  overlay="${REPO_ROOT}/.devops/chart/overlays/${env}/kustomization.yaml"
  tags="$(grep -E '^[[:space:]]*newTag:' "${overlay}" | sed -E 's/^[[:space:]]*newTag:[[:space:]]*//; s/^"(.*)"$/\1/' | sort -u)"
  count="$(printf '%s\n' "${tags}" | grep -c .)"
  names="$(grep -cE '^[[:space:]]*- name: ida-llm-' "${overlay}")"
  if [ "${count}" = "1" ]; then
    pass "${env}: all ${names} components share one tag ($(printf '%s' "${tags}"))"
  else
    fail "${env}: components disagree on a tag -- promote.sh would refuse: $(printf '%s' "${tags}" | tr '\n' ' ')"
  fi
  if [ "${names}" = "3" ]; then
    pass "${env}: all 3 built components have an images[] entry"
  else
    fail "${env}: expected 3 images[] entries, found ${names}"
  fi
done

echo "== FINAL: ${PASS} passed, ${FAIL} failed =="
[ "${FAIL}" -eq 0 ]
