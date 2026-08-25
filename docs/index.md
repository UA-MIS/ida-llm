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
| off-cluster inference (Sparks) | [`infra/inference/README.md`](../infra/inference/README.md) |

## Suggested first tasks

The walking skeleton has landed: the harness runs, the runner consumes the
queue, results persist, and the frontend renders them. What is left is depth,
not scaffolding.

1. **Fill in a real provider client.** `packages/harness/ida_harness/client.py`
   fixes the OpenAI-compatible surface and the mock proves it end to end. Add
   `anthropic` and keep it interchangeable with the mock.
2. **Make `subjective` tasks scorable.** The schema loads and validates them
   today (`tasks/SCHEMA.md`), but the LLM-as-judge scorer is still an interface.
3. **Fill in the three sweeps.** `services/runner/ida_runner/sweeps.py` is
   scaffold: the CronJobs run nightly and exit 0 without doing work. Every sweep
   must stay idempotent and MUST exit non-zero on failure.
4. **Write real tasks.** [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) is the whole
   authoring guide and `tasks/quantitative-quiz/` and `tasks/conceptual-grading/`
   are the two families to copy from. (`tasks/demo/` is not an exemplar -- it is
   the pair of tiny tasks the tracer bullet runs.) The schema gate runs on every
   PR, so a malformed rubric fails the pull request instead of a benchmark run
   three hours in.
