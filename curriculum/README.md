# `curriculum/` — the outcomes and the course taxonomy, as data

Two files, two publishers, one join key — **the course code**:

| file | authority | answers |
|---|---|---|
| [`slo.yaml`](slo.yaml) | the programme's curriculum map | which outcomes a course teaches, and at what level |
| [`majors.yaml`](majors.yaml) | the university course catalog | which majors exist, which classes each one owns |

They are kept apart rather than merged because they are transcriptions of
**different published documents** with different revision dates. One `source:`
field per file is what makes a later disagreement attributable to a moved
goalpost rather than to us.

Both are **data, not documentation**. Each has a JSON Schema
([`curriculum.schema.json`](../packages/core/ida_core/schemas/curriculum.schema.json),
[`majors.schema.json`](../packages/core/ida_core/schemas/majors.schema.json)),
a loader with cross-field validation
([`ida_core.curriculum`](../packages/core/ida_core/curriculum.py),
[`ida_core.majors`](../packages/core/ida_core/majors.py)), and both are
validated by `make lint-tasks` — which is the `task-schema` CI gate — alongside
`tasks/**` and `models.yaml`.

## `majors.yaml` — and the one field the drill-down's honesty rests on

`/explore` opens on the college's majors, because a professor is a professor **of
a major**, not of the shared core. Major → class → the outcomes behind it → the
evidence.

The load-bearing field is **`task_families`** on a class. Results are filed by
*outcome* — a task carries `slo:SLO2`, never `course:MIS 200` — so a class scored
from "the outcomes it teaches" gets a number that is *identical* for every other
class the map marks against those outcomes. Run the three MIS 200 exam families
without it and AC 210, ST 260, GBA 300, OM 300 and FI 302 each display a score
from a course none of them is: a dozen fabricated measurements, each
individually plausible, produced by arithmetic rather than by anybody lying.

So a class counts only the results whose task family it claims, and **a class
that claims none can never show a number**. That is the default, and it is
correct. Today exactly one class in the college claims any: MIS 200.

Three cross-file rules are gated in CI, because none of them is visible from
either file alone:

1. **Every class can name itself** — it carries a `title`, or the coverage grid
   has a row for its code. A class with neither would render as a nameless column.
2. **Every coverage course is claimed exactly once** — by one major, or by
   `unassigned_core` with a reason. An edit that dropped `MIS 200` from every
   class list would empty the only populated path in the product, silently.
3. **Every `task_families` entry names a family the catalogue has** — a
   misspelled family makes a class read "not measured yet" forever, which looks
   exactly like a class nobody has got round to running.

Title precedence is **catalog first, curriculum map second** (the map abbreviates:
"Fundamentals of MIS" against the catalog's "Fundamentals of Management
Information Systems"). Differences are *printed* by the validator, never gated —
gating would force a transcription of one published document to be edited to
agree with another.

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
