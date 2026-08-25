# IDA-LLM

An LLM benchmark harness and results platform.

> **Status: the deploy path is live; the application is not written yet.**
>
> This repository was scaffolded so that your first push builds, tests and
> deploys. The **structure**, the **chart** and the **pipelines** are real and
> verified end to end. The application logic is deliberately left to you — files
> that are placeholders say so at the top, in the file itself.

> **Sprint board:** work items for this project live at
> **<https://ida-agile.capstone.uamishub.com>** (`apps/agile/` — sign in with GitHub;
> access is limited to the `UA-MIS/ida-llm` team).

---

## What is real, and what is yours

**Real, tested, don't rewrite unless you mean to:**

- the deploy contract in [`.devops/`](.devops/README.md) — chart, overlays, CI seam
- both container images (built and run locally: they start, serve, and run as a
  non-root UID that matches the chart)
- the CI pipeline — five gates, all passing
- the **task/rubric schema gate** (`tools/validate_tasks.py`) — 8 rules, unit-tested
- the **mock model endpoint** — the safety switch that keeps PRs free
- the Alembic setup, verified `upgrade → downgrade → upgrade` against Postgres 17
- the health-probe contract (see below — it matters more than it looks)

**Yours to write:**

- `packages/harness/src/ida_harness/clients.py` — the provider clients. The
  `ModelClient` protocol is fixed; the bodies raise `NotImplementedError` with the
  reason. They deliberately do **not** fall back to the mock: a benchmark that
  quietly scored a mock while reporting a frontier model's name would invalidate
  every number in the database.
- `services/runner/src/ida_runner/worker.py` — the loop claims a job and does
  nothing with it. Keep the SIGTERM handler when you replace the body.
- `services/runner/src/ida_runner/sweeps.py` — the three CronJob entry points.
- `services/api/src/ida_api/app.py` — everything below the health endpoints.
- `frontend/src/app/` — the whole UI.
- `tasks/` — the real task suite. Two examples ship so the schema gate has
  something to check; an empty suite would let the gate pass vacuously.

---

## Layout

```
frontend/           Next.js 15 (standalone)          -> image: ida-llm-frontend
services/api/       FastAPI                          \
services/runner/    workers + sweeps + mock model     >- image: ida-llm-python-app
packages/core/      settings, ORM models              /   (ONE build, FOUR commands)
packages/harness/   THE standalone benchmark harness /
tasks/              versioned task defs + rubrics    <- schema-gated in CI
models.yaml         the model registry               <- schema-gated in CI
migrations/         Alembic
tools/              the task/model schema validator
infra/              off-cluster inference notes (Sparks)
.devops/            the deploy contract  -> read .devops/README.md
```

`packages/harness/` is the starred deliverable: it must stay **installable and
runnable outside this repo**. That is why it depends on nothing under `services/`
and takes the task suite as a path rather than discovering it.

---

## Local development

```bash
# Python: one editable install of all four distributions
python -m venv .venv && . .venv/bin/activate
pip install -e packages/core -e packages/harness -e services/api -e services/runner
pip install -r requirements-dev.txt

cp .env.example .env        # nothing secret in it; fill in what you need

ruff check packages services tools
pytest
python tools/validate_tasks.py

# the mock model endpoint (what CI and dev point at)
PORT=8099 ida-mock-model

# frontend
cd frontend && npm ci && npm run dev
```

---

## Environments

| | URL | models |
|---|---|---|
| dev | `ida-llm-dev.capstone.uamishub.com` | **mock** (free, offline) |
| staging | `ida-llm-staging.capstone.uamishub.com` | real |
| prod | `ida-llm.capstone.uamishub.com` | real |

dev and staging sit behind the platform's org-login gate; prod is public.

**No pull request and no dev deploy can spend provider credits or reach campus
hardware.** That is enforced in CI, in the overlays, and asserted by a render
test — three places, because a rule that lives in one file is a rule the next
change forgets. Details in [`.devops/README.md`](.devops/README.md).

---

## Two things worth knowing before you change the chart

**The health endpoints are a deployment contract, not an app detail.**
`/healthz` is liveness and **must not touch the database**; `/readyz` is readiness
and **does**. A liveness probe that checks a dependency turns a brief database
blip into a rolling restart of every replica — that is how a small outage becomes
a large one. There is a test that fails if `/healthz` starts needing a database.

**The campus "Sparks" vLLM route is deliberately deferred, not forgotten.**
`SPARKS_BASE_URL` is wired through settings, the ConfigMap and `models.yaml`, and
is empty everywhere. The cluster's egress policy opens `:443` to the internet but
opens **no route to Sparks**. Turning it on is a value here plus one block in
`platform-infra/platform-services/ida-llm-egress/netpol.yaml`, which spells out
the exact change and the three ways to get it wrong.

---

## Deploying

You mostly don't — pushing to `main` is the deploy.

| you do | what happens |
|---|---|
| push to `main` | CI runs, both images build, **dev** updates |
| `git tag v1.0.0 && git push --tags` | one immutable image; **staging** updates |
| run *promote-to-prod* in Actions | that same image goes to **prod** |

Nothing rebuilds between staging and prod — promotion is a tag copy, so the bytes
that ran in staging are the bytes that run in prod.

**You never need `kubectl`.** Everything is the portal and git.
