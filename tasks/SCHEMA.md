# Authoring tasks

A task is one YAML file under `tasks/`. Anything matching `**/*.yaml` or
`**/*.yml` whose filename does **not** start with `_` is loaded as a task.

The machine-checkable contract is
[`packages/core/ida_core/schemas/task.schema.json`](../packages/core/ida_core/schemas/task.schema.json);
CI validates every file against it -- the `task-schema` job in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs
`python tools/validate_tasks.py` on every pull request. This page
is the human summary of the conventions the schema cannot express.

---

## The one decision that shapes everything: `kind`

Every task is exactly one of two kinds. This is the taxonomy axis the whole
platform is built around, and it decides how the task can ever be scored.

| | `verifiable` | `subjective` |
|---|---|---|
| Scored by | a program (`exact_match`, `numeric_match`) | an LLM judge against a rubric |
| Every sample needs | a `target` (gold answer) | **no** `target` |
| Needs a `rubric` | no — forbidden | yes — required |
| Working today? | **yes** | **loaded and validated, not yet scorable** |

If you can write down the correct answer, the task is `verifiable`. Write it as
`verifiable`. Reach for `subjective` only when there genuinely is no single
right answer (feedback, explanation quality, pedagogical framing).

> **Subjective tasks do not produce scores yet.** The LLM-as-judge path is an
> interface in the walking skeleton
> (`ida_harness.scoring.LLMJudgeScorer` raises `NotImplementedError`). Subjective
> tasks load, validate, run against the model, and store their transcripts — but
> their results carry `scorable: false` and `score: null`. That is deliberate:
> a blank is honest, a zero would look like a failing model.

---

## Required fields

```yaml
version: 1                       # always 1; bumped only on a breaking format change
id: demo/arithmetic-quiz-check   # globally unique, lowercase, `/` for grouping
title: Arithmetic quiz answer check
kind: verifiable                 # or: subjective
scorer:
  kind: numeric_match            # exact_match | numeric_match | llm_judge
samples:
  - id: add-simple               # unique within the task, PATH-SAFE (see below)
    input: "What is 17 + 25?"
    target: "42"                 # verifiable only
```

Optional but strongly encouraged: `description`, `domain`, `system_prompt`, `tags`.

### `id` conventions

- Lowercase; `a-z 0-9 . _ - /`.
- Group with `/`: `statistics/hypothesis-selection`, `history/source-critique`.
- **Never reuse an id for different content.** A result row records the task id
  and the git SHA; changing what an id *means* silently invalidates comparisons
  against every result already stored.

### Sample `id` conventions

A sample id becomes the leaf of its transcript's object key
(`runs/<run_id>/transcripts/<sample_id>.json`), so it must match
`^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$` — **no slashes, no leading dot**. This is
enforced, not advisory (`ida_core.artifacts._check_segment`).

`.` is allowed, so ids like `fig.3a` are fine. Repeated sampling nests its
extra transcripts *under* the sample (`transcripts/<sample_id>/r<n>.json`)
rather than suffixing the leaf, precisely so that a sample legitimately named
`s1.r2` can never collide with repetition 2 of a sample named `s1`. You do not
have to avoid dots.

---

## Scorers

### `exact_match`

String equality after normalisation. All-or-nothing: 1.0 or 0.0. If you want
partial credit, you want a `subjective` task.

### `numeric_match`

Extracts the **last** number in the completion (models restate the question
first, so the first number is usually an input) and compares to the target.

```yaml
scorer:
  kind: numeric_match
  tolerance: 0.0001          # absolute: |got - want| <= tolerance
  relative_tolerance: 0.01   # relative: |got - want| <= 0.01 * |want|
```

Passes if **either** tolerance is satisfied. Both default to `0` — exact
equality. Opt in to slack deliberately; silent tolerance is how two labs end up
reporting different numbers for the same benchmark.

> **`strip_punctuation` is rejected for `numeric_match`.** `.` and `,` are
> numerically significant, so stripping punctuation turns `3.5` into `35` and
> `1,234.5` into `12345` — scoring every correct decimal answer as wrong, with
> no error. Both validation layers refuse it, so you find out in CI rather than
> in your results. If you need it, the task wants `exact_match`.

### `llm_judge`

Requires `scorer.rubric_id` to equal `rubric.id`. Not implemented yet — see above.

---

## Normalisation — be explicit

Nothing is stripped, lowered or collapsed unless you say so. Applied in this
fixed order:

`take_last_line` → `strip` → `collapse_whitespace` → `strip_punctuation` → `lowercase`

**Whatever is applied to the completion is applied to the target too.** The
comparison is symmetric in both scorers; an asymmetric one silently marks
correct answers wrong.

```yaml
scorer:
  kind: numeric_match
  normalisation:
    strip: true                # default true
    collapse_whitespace: true  # default true
    take_last_line: true       # default false — use when the model reasons first
    lowercase: false           # default false
    # strip_punctuation is NOT permitted here — see the numeric_match note above.
```

For `exact_match`, `strip_punctuation: true` is available and safe.

`take_last_line: true` plus a `system_prompt` that says "put the final answer on
the last line" is the standard recipe for a task where you want the model to
show its working.

---

## Steering the answer format

Put answer-format instructions in the task's `system_prompt`, **not** in the
harness. The system prompt is versioned in git and its SHA is recorded on every
result; a hardcoded nudge inside the solver would not be, and would silently
change every historical comparison the day someone edits it.

---

## Rubrics (subjective tasks)

```yaml
rubric:
  id: essay-feedback-v1        # version the id, do not edit a rubric in place
  scale_min: 0
  scale_max: 1
  criteria:
    - name: specificity
      description: >-
        Feedback points at concrete passages rather than generic advice.
      weight: 2.0              # relative weight; must be > 0
```

Criterion `description`s are written **for the judge model to read**. Vague
criteria produce noisy grades. Say what a passing response does and what a
failing one does.

Version rubric ids (`-v1`, `-v2`) rather than editing them: a grade is only
comparable to grades produced by the same rubric.

---

## Checklist before you commit a task

- [ ] `kind` matches reality — could you write the answer down? then `verifiable`.
- [ ] Every `verifiable` sample has a `target`; no `subjective` sample has one.
- [ ] Sample ids are path-safe and unique within the task.
- [ ] Normalisation is stated, not assumed.
- [ ] No `strip_punctuation` on a `numeric_match` task (both layers reject it).
- [ ] A `numeric_match` target contains exactly one number. If it does not, the
      sample is recorded with an error rather than scored — it will not silently
      pass, and it will not take the rest of the run down with it.
- [ ] `make lint-tasks` passes (schema + semantic validation).
