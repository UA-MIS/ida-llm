# IDA-LLM docs

Start with the root [`README.md`](../README.md) for what is scaffolding and what
is yours, and [`.devops/README.md`](../.devops/README.md) for the deploy contract.

## Where things are documented

| topic | where |
|---|---|
| task + rubric schema, and the 8 rules CI enforces | [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) |
| the deploy path, secrets, previews, adding a component | [`.devops/README.md`](../.devops/README.md) |
| every environment variable | [`.env.example`](../.env.example) |
| the model registry | [`models.yaml`](../models.yaml) |
| off-cluster inference (Sparks) | [`infra/inference/README.md`](../infra/inference/README.md) |

## Suggested first tasks

1. **Fill in one provider client.** `packages/harness/src/ida_harness/clients.py`
   already fixes the `ModelClient` protocol; implement `anthropic` or `openai`
   against it and the mock stays interchangeable with the real thing.
2. **Make the runner actually run a task.** The loop claims a job from Redis and
   drops it. Wire `load_tasks` → `build_client` → `score_response` → write rows.
   Keep the SIGTERM handler.
3. **Write real tasks.** Replace `tasks/examples/`. The schema gate runs on every
   PR, so a malformed rubric fails the pull request instead of a benchmark run.
4. **Give the frontend something to show.** `/api/runs` returns an empty list with
   the right shape; the api has no public Ingress, so call it server-side at
   `http://ida-llm-api`.
