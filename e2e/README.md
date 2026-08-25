# The tracer bullet

One test that proves the whole pipeline is wired, not just that each piece works
alone. It runs in **two modes** against the **same assertions**:

| | `test_tracer_inprocess.py` | `test_tracer_compose.py` |
|---|---|---|
| Run with | `make test` (and CI) | `make tracer` |
| Postgres | SQLite | real CloudNativePG-compatible Postgres 16 |
| Redis | `InMemoryQueue` | real Redis 7 |
| MinIO | `LocalArtifactStore` | real MinIO |
| mock-model | in-process ASGI | real container over HTTP |
| API / runner | in-process | real containers |
| Needs Docker | no | yes |

The in-process mode is the one that gates every commit: it is fast, hermetic and
exercises **the same application code** — the swapped pieces are alternative
implementations of the same protocols (`RunQueue`, `ArtifactStore`), not mocks.
The compose mode is what proves the containers, networking, migrations and
service discovery are right too.

## The path being traced

```
POST /runs            (api)      → run row committed as `queued`, id minted
  → RPUSH ida:queue:runs         → RunJobMessage on the queue
  → BLPOP               (runner) → run claimed, marked `running`, serving config stamped
  → harness             (harness)→ POST /v1/chat/completions to mock-model
  → numeric_match scorer         → Score per sample
  → transcripts                  → MinIO  runs/<id>/transcripts/<sample>.json
  → result rows + rollup         → Postgres
GET /runs/{id}         (api)     → score + serving config + artifact pointer
GET /runs/{id}/results/{s}/transcript
                                 → the archived bytes, back out of MinIO
```

## What is asserted

Both modes call the **same** functions in `conftest.py`, so neither gate can
drift weaker than the other:

| Assertion | Pins |
|---|---|
| `assert_tracer_run_is_complete` | the happy path: 4/4 scored, D-1 serving config on the run and every result, token/cost rollup adds up, every score has an artifact pointer |
| `assert_transcript_is_faithful` | the archived bytes contain the real system+user exchange |
| `assert_subjective_run_is_unscored_not_zeroed` | `succeeded`, `error_count 0`, `mean_score null` — not-yet-scorable is **not** a failure |
| `assert_all_errored_run_is_marked_failed` | a run whose every call failed reports `failed` with `error_count == sample_count` — **not** `succeeded`, and distinguishable from the subjective case |
| `assert_partial_run_is_marked_partial` | some failed, some did not: `partial`, and the mean covers only the survivors |

The last two exist because an earlier revision reported a run of four failed API
calls as `succeeded` and the UI rendered it as "a subjective task". Both are
`mean_score: null`; only one of them measured nothing.

## Running it

```bash
make test      # in-process — no Docker needed
make tracer    # full docker-compose stack, then the same assertions
```

Frontend coverage is deliberately build-level (`make test-frontend`): the page's
API contract is typechecked against generated types, and no browser automation
is needed to prove the skeleton is wired.
