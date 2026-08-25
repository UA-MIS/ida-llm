# Task + rubric schema (`ida.capstone/v1`)

`tasks/**/*.yaml` and `models.yaml` are **versioned data**, not config. Every
benchmark result cites the git SHA of the task file and the rubric that produced
it — that citation is only worth something if the files are well-formed, so the
schema is enforced in CI (`ida-validate-tasks`, run by `.github/workflows/ci.yml`).
A malformed rubric **fails the pull request**. It does not fail three hours into a
benchmark run.

Validator: [`tools/validate_tasks.py`](../tools/validate_tasks.py). It is
dependency-light on purpose (PyYAML only) so it runs in any container the CI
happens to have.

## Task file

```yaml
apiVersion: ida.capstone/v1
kind: Task
id: <slug>                 # unique across tasks/**; [a-z0-9-]; matches the filename stem
version: 1                 # integer, bump on any semantic change to prompt/rubric
title: <human title>
category: <slug>           # free-form grouping, e.g. reasoning, extraction, code
prompt: |                  # the exact text sent to the model
  ...
rubric:                    # how a response is scored
  kind: exact | contains | numeric | judge
  ...                      # kind-specific fields, see below
gold: <any>                # the reference answer (required except kind: judge)
tags: [<slug>, ...]        # optional
```

### `rubric.kind`

| kind | extra fields | scoring |
|---|---|---|
| `exact` | `case_sensitive` (bool, default `false`) | 1.0 if the response equals `gold`, else 0.0 |
| `contains` | `any_of` (list of strings, required) | 1.0 if the response contains **any** entry |
| `numeric` | `tolerance` (float ≥ 0, required) | 1.0 if `abs(response - gold) <= tolerance` |
| `judge` | `judge_model` (model id from `models.yaml`), `criteria` (non-empty list) | judge model returns 0.0–1.0 |

### Rules the validator enforces

1. `apiVersion` is exactly `ida.capstone/v1` and `kind` is `Task`.
2. `id` is unique across every task file, is a DNS-style slug, and **matches the
   filename stem** — so a result citing `id` can be traced back to a path.
3. `version` is a positive integer.
4. `prompt` is non-empty after stripping.
5. `rubric.kind` is one of the four above, and the kind-specific fields are
   present and well-typed.
6. `gold` is present for every kind except `judge` (a judge rubric has no single
   reference answer).
7. `judge_model` — when present — resolves to an `id` in `models.yaml`. This is
   the check that catches the actual expensive mistake: a rubric pointing at a
   model that was renamed or removed, discovered mid-run.
8. `models.yaml` itself: unique ids, known `provider`, `temperature` in [0, 2],
   `max_tokens` a positive integer, and `api_key_env` / `base_url_env` are
   environment-variable NAMES (`[A-Z0-9_]+`) — never literal values. Rule 8 is
   what stops a pasted API key from being committed.

## Adding a task

1. Create `tasks/<category>/<id>.yaml`.
2. Run `python tools/validate_tasks.py` locally (or `ida-validate-tasks`).
3. Open the PR. CI runs the same validator; a failure blocks the merge.
