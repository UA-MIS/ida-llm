# `curriculum/` — the Student Learning Outcomes, as data

[`slo.yaml`](slo.yaml) holds the nine BScBA Student Learning Outcomes, the two
axes every SLO-anchored benchmark task is filed under, and the published
course-by-outcome coverage grid.

It is **data, not documentation**. It has a JSON Schema
([`curriculum.schema.json`](../packages/core/ida_core/schemas/curriculum.schema.json)),
a loader with cross-field validation
([`ida_core.curriculum`](../packages/core/ida_core/curriculum.py)), and it is
validated by `make lint-tasks` — which is the `task-schema` CI gate — alongside
`tasks/**` and `models.yaml`.

## Why it exists

A benchmark result is a number **plus the thing it is a number about**. This
platform already refuses to lose the first half: every result carries its
serving config and the git SHA of the task that produced it (**D-1**).

An `slo:SL02` typo loses the second half just as completely, and does it
*silently*. The task loads. The run succeeds. The score is real. And it is filed
under a heading that does not exist, so it disappears from every per-outcome
view without ever producing an error.

So the outcome list is a file, the tags are checked against it, and a mistyped
outcome fails the pull request rather than the analysis.

## The tag contract

A task that is part of this benchmark carries three tags:

```yaml
tags: [slo-benchmark, "slo:SLO2", "use-mode:capability", ladder-l3, quantitative-literacy]
```

| tag | meaning |
|---|---|
| `slo-benchmark` | family membership — one filter selects the whole benchmark |
| `slo:<ID>` | which outcome, spelled exactly `SLO1`…`SLO9` |
| `use-mode:<id>` | what is being asked of the model; only `capability` is in use |
| `ladder-lN` | which rung of its family's difficulty ladder |

**Parse `key:value` tags by splitting on the FIRST colon.** They live in `tags`
rather than in a structured field because a task file has no task-level
`metadata` — the JSON Schema sets `additionalProperties: false` at the top
level, and `tags` is the one free-form list. That is not a workaround: `tags` is
published by `GET /tasks/{id}`, and results are reported per (task, model), so
`tags` is exactly the granularity a per-outcome view groups on.

Every sample repeats the same two facts un-prefixed, for per-sample drill-down:

```yaml
metadata: { skill: break-even-volume, provenance: synthetic, slo: SLO2, use_mode: capability }
```

**Group by `tags`; drill down by sample `metadata`.** Two spellings of one fact
is a drift risk, so `check_task_tags` requires them to agree rather than trusting
that they do — a task whose tag says `SLO2` and whose sample metadata says `SLO9`
is rejected.

### What is enforced, and where

`tools/validate_tasks.py` rejects a task that:

- names an outcome the map does not declare;
- names an outcome marked `text_benchmarkable: false`;
- names a use mode that is not `in_use`;
- carries two `slo:` or two `use-mode:` tags (a result row has one of each);
- carries either tag without `slo-benchmark`, or the reverse;
- has sample metadata missing or contradicting the task's tags.

A task carrying none of the three tags is not part of this benchmark and passes
untouched — the `demo/` and exemplar families predate it.

## Consumers should read outcome ids and statements from this file

Do not hardcode nine strings. The wording here is the registrar's and will be
re-transcribed when the published map changes; anything that copies it will
drift. `load_curriculum(default_curriculum_path(repo_root()))` returns a
validated `CurriculumMap` with `outcome_ids()`, `get(id)`,
`text_benchmarkable_ids()`, `courses_for_outcome(id)`,
`outcomes_for_course(code)` and `is_assessment_point(course, outcome)`.

## Two outcomes are deliberately out of scope

`SLO5 Teamwork` and `SLO8 Oral Communication` are marked
`text_benchmarkable: false`, and the validator refuses any task that claims
them.

This is a decision, not a gap, and it is recorded in the file so that a
benchmark covering seven outcomes cannot be mistaken for a programme that has
seven. Teamwork is behaviour inside a real group over time; a single-turn prompt
can at best measure whether a model can *write about* teamwork, which is SLO7
wearing a different label. Oral communication is delivery, timing and audience
response; a transcript is not a presentation. Measuring the nearest text-shaped
proxy and filing it under those outcomes would be the most misleading thing this
repository could publish.

## Coverage levels

From the published map's legend: `I` Introduced, `R` Reinforced, `M` Mastered,
`A` Assessment Point, `M+A` Mastered + Assessment Point. An omitted key means
the map does not mark that pair — **not** that the level is unknown.

The level is not decoration. An outcome measured at an assessment point (`A`,
`M+A`) is one the programme already reports on, so a family aimed at that
(course, outcome) pair is aimed at something with an existing human number to
compare against later.

**MIS 200 (Fundamentals of MIS)** is the target course for the first live run:
SLO1 at `R`, SLO2 at `A`, SLO9 at `I`. Those three families are authored to full
depth, and SLO2 — the assessment point — is `verifiable`, so it produces numbers
today without a judge model being configured and funded.

## Provenance

The nine outcome statements and the coverage grid were transcribed by hand from
the university's published curriculum map for the BScBA General Business (core)
programme; `source`, `source_last_modified` and `retrieved` are recorded in the
file. `retrieved` is separate from `source_last_modified` on purpose: a
curriculum map is edited in place, so a later disagreement should be
attributable to a moved goalpost rather than blamed on the transcription.

Nothing here is course material, student work, or an assessment instrument. It
is the list of outcomes and the map of which course covers which — both public
programme description. The benchmark content itself, under `tasks/`, is entirely
synthetic; see [`tasks/SCHEMA.md` → Dataset hygiene](../tasks/SCHEMA.md#dataset-hygiene).
