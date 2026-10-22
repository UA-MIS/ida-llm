# `.devops/` — the deploy contract

Everything the platform needs to build, ship and promote this repo. It is a
**contract**, not app code: the platform's `ida-llm-envs` ApplicationSet reads
`promotion.yaml` from this repo at `HEAD`, CI reads `components.yaml`, and ArgoCD
renders `chart/overlays/<env>`.

```
components.yaml    what gets BUILT       -> the CI build matrix
promotion.yaml     trigger -> env -> tag -> the ApplicationSet + the CI seam
ci/*.sh            the seam scripts      -> unit-tested, run in CI
chart/base/        the workload shape    -> prod defaults
chart/overlays/    per-env differences   -> dev, staging, prod, preview
```

---

## The deploy path

| trigger | tag | lands in |
|---|---|---|
| push to `main` | `<git-describe>` | **dev**, continuously |
| push tag `vX.Y.Z` | `X.Y.Z` | **staging** |
| run *promote-to-prod* | the **same** `X.Y.Z` | **prod** |

**Build once, promote the same image.** Both components always carry the
identical tag, and `promote.sh` refuses to promote if they disagree. A promotion
is a tag copy — never a rebuild, never a new git tag, never a code edit. The bytes
that ran in staging are the bytes that run in prod.

---

## What runs where

Two images. Six workloads. `components.yaml` lists what is **built**; the chart is
where the fan-out lives.

| workload | image | command | dev | staging | prod |
|---|---|---|---|---|---|
| `frontend` | `ida-llm-frontend` | `node server.js` | 1 | 1 | 2 |
| `api` | `ida-llm-python-app` | `ida-api` | 1 | 1 | 2 |
| `runner` | `ida-llm-python-app` | `ida-runner` | 1 | 2 | 4 |
| `mock-model` | `ida-llm-python-app` | `ida-mock-model` | 1 | **0** | **0** |
| `redis` | upstream (StatefulSet) | — | 1 | 1 | 1 |
| `object-store` | upstream MinIO | — | 1 | 1 | 1 |
| 3 × sweep CronJob | `ida-llm-python-app` | `ida-sweep <name>` | active | active | active |

`api`, `runner`, `redis`, `object-store` and `mock-model` have **no public
Ingress**. Only the frontend is routed publicly.

---

## The credit / campus-hardware safety switch

> **No pull request, and no dev deploy, can spend provider credits or reach
> campus hardware.**

That is enforced in three places, on purpose — a rule that lives in one workflow
file is a rule the next workflow forgets:

1. **CI** (`.github/workflows/ci.yml`) sets `MOCK_MODEL_BASE_URL` and gives the
   provider variables obviously-fake literals, so a test that reaches for a live
   provider fails on auth rather than succeeding and billing someone.
2. **The dev and preview overlays** run the `mock-model` Deployment *and* point
   `MOCK_MODEL_BASE_URL` at it. Both halves are required: a URL with no pod gives
   connection-refused, a pod with no URL leaves the mock idle while real
   providers get billed.
3. **`chart-render.test.sh`** asserts both directions — mock **on** in
   dev/preview, mock **off and URL empty** in staging/prod. The inverse is the
   expensive one: a mock quietly answering in production would invalidate every
   stored benchmark result while everything looked healthy.

`staging` deliberately uses **real** models. A staging that mocked its models
would prove the deploy path and nothing about what the app exists to do, and the
first real inference call would then happen in production.

---

## Secrets

Nothing secret is in git. The overlays name **Vault paths and property keys
only**; ESO materializes them.

| Secret | Source | Keys |
|---|---|---|
| `ida-llm-secret` | `secret/tenants/ida-llm/<env>/app` | `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `SPARKS_API_KEY`, `LOCAL_LLM_API_KEY` (added by the portal bot PR) |
| `ida-llm-db` | `secret/tenants/ida-llm/<env>/database` | assembled into `DATABASE_URL` |

Seed or rotate a value:

```bash
vault kv patch secret/tenants/ida-llm/dev/app ANTHROPIC_API_KEY=...
```

The `SecretStore` (`vault-tenant`) and its `eso-tenant` ServiceAccount are **not**
shipped by this repo for dev/staging/prod — the CapstoneTenant Composition creates
them. Shipping copies would make them dual-owned and fight Crossplane.

`secretKeyRef`s are deliberately **not** `optional: true`. A missing secret keeps
the pod in `CreateContainerConfigError` — loud and correct — rather than letting
it boot with the variable unset and serve wrong results while reporting Ready.
Every Deployment that reads an ESO secret also carries a Reloader annotation, or a
pod that started before ESO wrote the Secret would keep its unresolved env for the
life of the container.

---

## The database

`postgres`, provisioned automatically by the tenant claim: per environment a PG17
database and login role `ida_llm_<env>` on the in-cluster tenant DB tier.

The **database name is not in Vault** — it is structural (`<team with - as _>_<env>`),
so the DSN is assembled in the overlay's `target.template`. If the tenant slug
ever changes, that literal must change with it.

Migrations run as an **initContainer on the `api` Deployment only**. `Job` is
whitelisted now, so a PreSync hook Job is possible — an initContainer is used
because it needs no hook machinery to be correct, and putting it on `runner` too
would have four replicas racing the same migration on every rollout.

CI runs `alembic upgrade head` → `downgrade base` → `upgrade head` against a
throwaway Postgres 17. A migration that only works **forward** is one you cannot
roll back at 2am.

---

## Preview environments

The `preview` overlay and the PR-preview CI legs are **complete and
render-tested**. They are **dormant** because the *platform* cannot fence a
preview namespace yet — the tenant claim carries `previewEnabled: false`.

Four blockers, all outside this repo:

1. `<team>-pr-<n>` namespaces get **no** quota, LimitRange or NetworkPolicy from
   the Composition (its per-env bundle ranges over dev|staging|prod only). A
   preview would have *more* network reach than prod.
2. The Vault `AuthBackendRole` binds the **literal** `ida-llm-preview`, not
   `ida-llm-pr-<n>`, and the list is not a glob — so ESO 403s.
3. `harbor-pull` is explicitly not rendered for preview, so every pod
   ImagePullBackOffs against the private Harbor project.
4. `tenants/_template/applicationset-preview.yaml` still carries
   `DO NOT MERGE WITHOUT SECURITY REVIEW` with four open blockers.

**When those close, previews turn on by flipping one field on the tenant claim.
Nothing in this repo changes.** Do not delete the preview overlay as dead code —
it is the half of the contract this repo owns, already done.

---

## Adding the `agile` component

A third component — an ADO-style sprint board at the **explicit** host
`ida-agile.capstone.uamishub.com`, single pod, **prod only**, its own Postgres
schema — is being built separately. The chart is already shaped to take it. Five
edits, in this order, and nothing above needs to change:

**1. `components.yaml`** — replace the RESERVED comment block with a real entry.
Its `context` must be `.` like the others, and `image` must carry the `ida-llm-`
prefix so two components never collide in the shared Harbor project:

```yaml
  - name: agile
    kind: backend
    context: .
    dockerfile: services/agile/Dockerfile
    image: ida-llm-agile
    port: 8080
    path: ""          # NOT "/" -- it gets its own host, not a path on the app's
    needsDb: true
    buildType: container
```

The CI matrix picks it up with no workflow edit — `resolve-components.sh` reads
this file.

**2. `chart/base/deployments.yaml`** — add one Deployment. Copy the `api` block
and change: name, `app.kubernetes.io/component: agile`, image
`ida-llm-agile:latest`, `replicas: 1`, its port, and its own migration
initContainer if it has migrations. Keep `runAsUser: 65532`, the Reloader
annotation, and the split `/healthz` liveness ÷ `/readyz` readiness contract.

**3. `chart/base/services.yaml`** — add one ClusterIP Service, `:80` →
`targetPort: http`. That takes the app to six Services against a quota of 15.

**4. `chart/base/ingress.yaml`** — add a **second rule** to the **existing**
`ida-llm` Ingress, and add the host to `tls.hosts`:

```yaml
    - host: ida-agile.capstone.uamishub.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: ida-llm-agile, port: { name: http } }
```

> ### ⚠ Three things to get right here — read before editing
>
> **(a) Use the existing Ingress object; do not create a second one.** The
> platform's env ApplicationSet attaches the non-prod SSO forwardAuth via a
> `templatePatch` targeting `kind: Ingress, name: ida-llm`. A new Ingress with a
> different name would silently receive **no** auth gate in dev and staging — no
> error, just an open app.
>
> **(b) The middleware annotation is per-Ingress-OBJECT, not per-rule.** Every
> host on this object shares one auth posture per environment. That is fine here
> *because* the agile board is prod-only, and prod is never gated. If it ever
> gains a dev or staging presence, it inherits the org-login gate along with the
> main app — which is almost certainly what you want, but it should be a decision,
> not a surprise.
>
> **(c) The host is EXPLICIT and must not be patched per env.** Every other host
> follows `<app>-<env>`; this one does not. So the dev/staging/preview overlays
> must patch **only `/spec/rules/0/host`** — index 0, the frontend — and must add
> `ida-agile...` to their `tls.hosts` list unchanged. Patching `rules/1/host` or
> replacing `tls/0/hosts` wholesale is how the router and the certificate end up
> disagreeing. Note the host is still **single-label** under
> `capstone.uamishub.com`; the Cloudflare Universal SSL wildcard covers exactly
> one level, so `ida-agile.capstone...` works and `agile.ida-llm.capstone...`
> would not resolve to valid public TLS.

**5. `chart/overlays/{dev,staging,preview}/kustomization.yaml`** — scale it to 0
in the non-prod envs (prod-only component), and add its image to the `images:`
list in **all four** overlays so the promotion seam moves all three components
together:

```yaml
  - target: { kind: Deployment, name: ida-llm-agile }
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 0
```

```yaml
  - name: ida-llm-agile
    newName: harbor.capstone.uamishub.com/ida-llm/ida-llm-agile
    newTag: "v0.0.0"
```

> ⚠ **The `images:` entry is required in every overlay, including the ones where
> it is scaled to 0.** `bump-image.sh` rewrites every `images[].newTag` in one
> pass and `promote.sh` **refuses to promote** if the overlays disagree on a tag.
> An overlay missing the entry will not fail loudly — it will make the next
> promotion refuse, with an error that points at the tag mismatch rather than at
> the missing line.

**Database.** The claim provisions **one** database per environment
(`ida_llm_prod`). The agile board wants its own **schema**, not its own database —
so it reuses `ida-llm-db` and sets a distinct schema (e.g. `search_path=agile`) or
an Alembic `version_table_schema`. Do not add a second `database:` to the tenant
claim; the XRD takes one engine per tenant, and a second claim for the same team
would fight the first over the same namespaces.

**Finally**: `chart-render.test.sh` asserts `5 Deployments` and `5 Services`. Bump
both counts in the same PR, or CI will (correctly) fail.

---

## Running the seam locally

```bash
# what would this git event build?
GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main sh .devops/ci/resolve-image.sh

# the build matrix
sh .devops/ci/resolve-components.sh

# render an overlay and assert every deploy invariant
bash .devops/ci/chart-render.test.sh

# the seam scripts' own unit tests
for s in resolve-image resolve-components bump-image promote seed-initial-envs; do
  bash ".devops/ci/${s}.test.sh"
done
```
