# IDA-LLM docs

Start with the root [`README.md`](../README.md) for what is scaffolding and what
is yours, and [`.devops/README.md`](../.devops/README.md) for the deploy contract.

## Where things are documented

| topic | where |
|---|---|
| **authoring tasks** -- the full guide: families, difficulty ladders, gold answers, anchored rubrics, dataset hygiene, the pre-PR checklist | [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) |
| two worked exemplar families to copy | [`tasks/quantitative-quiz/`](../tasks/quantitative-quiz/) (verifiable), [`tasks/conceptual-grading/`](../tasks/conceptual-grading/) (subjective) |
| the deploy path, secrets, previews, adding a component | [`.devops/README.md`](../.devops/README.md) |
| every environment variable | [`.env.example`](../.env.example) |
| the model registry | [`models.yaml`](../models.yaml) |
| **provider clients** -- which client answers for which entry, the Anthropic/OpenAI gotchas, retry and `Retry-After`, why there is no mock fallback | [`docs/model-clients.md`](model-clients.md) |
| **LLM-as-judge** -- how subjective tasks are scored, the bias controls, what judging costs, retroactive grading | [`docs/llm-judge.md`](llm-judge.md) |
| off-cluster inference (Sparks) | [`infra/inference/README.md`](../infra/inference/README.md) |

## Suggested first tasks

The walking skeleton has landed: the harness runs, the runner consumes the
queue, results persist, and the frontend renders them. What is left is depth,
not scaffolding.

1. **Verify the provider clients against a real endpoint.** Anthropic
   (Messages API) and OpenAI (chat completions) are implemented and covered by
   mocked-HTTP tests -- see [`docs/model-clients.md`](model-clients.md). What is
   still parked is one real call per provider, which needs credits and a tag.
   The documented gotchas (OpenAI's `max_completion_tokens`, Anthropic's
   sampling rejections) are the likeliest first failures.
2. **Turn the judge on, and calibrate it.** LLM-as-judge is implemented
   ([`docs/llm-judge.md`](llm-judge.md)) and **off by default** -- set
   `IDA_JUDGE_MODEL_KEY` to a `models.yaml` key to grade subjective runs, and
   `python -m ida_harness.regrade <run_id>` to grade ones that already finished.
   Two follow-ons are named in that document: wiring the setting through the
   runner service, and a `POST /runs/{id}/regrade` endpoint so a retroactive
   grade reaches Postgres and the UI. The calibration record shape exists; the
   human-agreement study has not been run.
3. **Fill in the three sweeps.** `services/runner/ida_runner/sweeps.py` is
   scaffold: the CronJobs run nightly and exit 0 without doing work. Every sweep
   must stay idempotent and MUST exit non-zero on failure.
4. **Write real tasks.** [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) is the whole
   authoring guide and `tasks/quantitative-quiz/` and `tasks/conceptual-grading/`
   are the two families to copy from. (`tasks/demo/` is not an exemplar -- it is
   the pair of tiny tasks the tracer bullet runs.) The schema gate runs on every
   PR, so a malformed rubric fails the pull request instead of a benchmark run
   three hours in.
