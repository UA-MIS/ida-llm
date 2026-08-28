# IDA-LLM docs

Start with the root [`README.md`](../README.md) for what is scaffolding and what
is yours, and [`.devops/README.md`](../.devops/README.md) for the deploy contract.

## Where things are documented

| topic | where |
|---|---|
| **authoring tasks** -- the full guide: families, difficulty ladders, gold answers, anchored rubrics, dataset hygiene, the pre-PR checklist | [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) |
| two worked exemplar families to copy | [`tasks/quantitative-quiz/`](../tasks/quantitative-quiz/) (verifiable), [`tasks/conceptual-grading/`](../tasks/conceptual-grading/) (subjective) |
| **the researcher track** -- the scholarship task families, the persona/use-mode tag vocabulary the recommendation forks on, and the research-privacy rule for unpublished data and IP | [`docs/researcher-track.md`](researcher-track.md) |
| the deploy path, secrets, previews, adding a component | [`.devops/README.md`](../.devops/README.md) |
| every environment variable | [`.env.example`](../.env.example) |
| the model registry | [`models.yaml`](../models.yaml) |
| **provider clients** -- which client answers for which entry, the Anthropic/OpenAI gotchas, retry and `Retry-After`, why there is no mock fallback | [`docs/model-clients.md`](model-clients.md) |
| **provider keys** -- how a secret gets from Vault to a model call, adding a new one, and why `OPENAI_API_KEY` is deliberately unset locally | [`docs/provider-keys.md`](provider-keys.md) |
| **LLM-as-judge** -- how subjective tasks are scored, the bias controls, what judging costs, retroactive grading | [`docs/llm-judge.md`](llm-judge.md) |
| **calibration slices** -- checking our harness against *published* benchmark numbers, and sizing a real run against the $25 cap (not the same thing as judge calibration) | [`docs/calibration.md`](calibration.md) |
| off-cluster inference (Sparks) | [`infra/inference/README.md`](../infra/inference/README.md) |
| **sensitive course material** -- where real exams/quizzes live, what may enter the repo, provenance pointers, and the cloud-vs-local rule | [`docs/sensitive-material.md`](sensitive-material.md) |
| **the intake pipeline** -- how real material is de-identified on intake, the provenance pointer, the cleaned/uncleaned gate, and what pattern-based cleaning does not catch | [`docs/intake-pipeline.md`](intake-pipeline.md) |

## Suggested first tasks

The walking skeleton has landed: the harness runs, the runner consumes the
queue, results persist, and the frontend renders them. What is left is depth,
not scaffolding.

1. **Verify the provider clients against a real endpoint.** Anthropic
   (Messages API) and OpenAI (chat completions, both the plain and the
   *reasoning* dialect) are implemented and covered by mocked-HTTP tests -- see
   [`docs/model-clients.md`](model-clients.md). What is still parked is the
   first real call.

   This is now unblocked for **OpenAI**: `luna` (`gpt-5.6-luna`) is enabled in
   `models.yaml` and `OPENAI_API_KEY` is in Vault and projected into the
   deployed runner, on a **$25 test-only cap**. The smoke test runs **in
   staging after deploy**, never from a dev box (which holds no key, by
   design) -- see [`docs/provider-keys.md`](provider-keys.md). Anthropic still
   needs credits and a tag. The documented gotchas (OpenAI's
   `max_completion_tokens` and its reasoning-model sampling restrictions,
   Anthropic's sampling rejections) are the likeliest first failures.

   Note the two senses of "calibration" in this project, which are different
   things and are easy to confuse: the **calibration slice**
   ([`docs/calibration.md`](calibration.md)) checks *our harness against
   published benchmark numbers*; **judge calibration** (item 2 below) checks
   *the LLM judge against human graders*.
2. **Calibrate the judge.** LLM-as-judge is implemented and **off by default**
   ([`docs/llm-judge.md`](llm-judge.md)): set `IDA_JUDGE_MODEL_KEY` to a
   `models.yaml` key, and `python -m ida_harness.regrade <run_id>` grades runs
   that already finished. The calibration record shape exists and is queryable
   per sample and criterion; the human-agreement study has not been run.
3. **Decide whether the nightly should *produce* subjective runs, and teach the
   API about the judge.** Both grading paths are wired: the runner grades
   subjective samples as they run (`IDA_JUDGE_MODEL_KEY` → `build_worker` →
   `Worker` → `run_task(judge=…)`), and `judge-calibration` grades the backlog
   nightly against
   [the row-level predicate contract](llm-judge.md#the-row-level-predicate-contract),
   bounded by `results.judge_attempts` so a down judge cannot be re-billed
   forever. Two named follow-ons remain, both deliberately stopped at a decision
   rather than guessed: `rebenchmark`/`model-sweep` still exclude subjective
   tasks (turning that on adds a judge call per criterion per sample to the
   unattended nightly), and the API still reports `scorable: false` for them
   (that field is a public contract). A `POST /runs/{id}/regrade` endpoint would
   give the *CLI* regrade path a way to reach Postgres, which the sweep already
   has. Every sweep must stay idempotent and MUST exit non-zero on failure.
4. **Write real tasks.** [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) is the whole
   authoring guide and `tasks/quantitative-quiz/` and `tasks/conceptual-grading/`
   are the two families to copy from. (`tasks/demo/` is not an exemplar -- it is
   the pair of tiny tasks the tracer bullet runs.) The schema gate runs on every
   PR, so a malformed rubric fails the pull request instead of a benchmark run
   three hours in.
