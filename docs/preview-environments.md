# PR preview environments — deferred

**Status: NOT enabled. Deferred by owner decision, 2026-08-25.**

Opening a pull request does **not** create a preview environment. It runs the
five CI gates in `ci.yml` and nothing else.

## Why

The gaps are all on the **platform** side, not in this repo. They are written up
in full — with effort estimates and an incident report — in platform-infra:

> `docs/operator/tenant-preview-gaps.md`

Summary of the four:

| # | Gap | Whose change |
|---|---|---|
| 1 | A per-PR namespace gets **no** ResourceQuota, LimitRange or NetworkPolicy — a preview would have *more* network reach than prod while running untrusted PR code. | **platform** |
| 2 | Vault's k8s-auth role binds an **exact list** of namespaces, so a per-PR namespace's ESO identity is refused. provider-vault exposes no namespace *selector*. | **platform** |
| 3 | `harbor-pull` is not rendered for preview namespaces, so every pod `ImagePullBackOff`s against the private registry. | **platform** |
| 4 | Static `pr-1` collision — **not applicable** to this tenant. | none |

## What this repo already has, sitting inert

Everything on the app side is done and costs nothing while dormant:

- `.devops/chart/overlays/preview/` — a complete overlay, render-tested by
  `.devops/ci/chart-render.test.sh` on every PR, so it cannot silently rot.
- `.devops/promotion.yaml` — a `preview` environment entry.
- `.github/workflows/build-and-push.yaml` — a `bump-preview` job and a commented-out
  `pull_request:` trigger.

**Reviving previews, once the platform gaps close, is two edits:** uncomment the
`pull_request:` trigger in `build-and-push.yaml`, and set `previewEnabled: true`
on the tenant claim in platform-infra. Nothing else here changes.

## One thing not to "simplify" if previews are revived

A preview must get a **throwaway in-namespace Postgres**, never the shared tenant
database, and its namespace must be granted **no egress to the db-tier at all**.
A preview runs untrusted pull-request code; pointing it at the real database means
one bad migration in a PR drops the team's dev data. The absence of that egress
rule is what makes the guarantee real rather than a convention.
