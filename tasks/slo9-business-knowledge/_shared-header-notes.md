<!-- Not a task file: the leading underscore keeps it out of the loader
     (ida_core.validation.discover_task_files skips names starting with `_`).
     It holds the two design decisions shared by every rung of this family, so
     they are stated once rather than six times. -->

# slo9-business-knowledge — family design notes

## Why forced choice

SLO9 is the only outcome whose text asks for **breadth**: "a comprehensive
understanding of core business principles". Breadth is what a wide forced-choice
family measures well and an essay measures badly — twenty short items across
six functions tell you more about coverage than one long answer about any of
them. Every other SLO family in this benchmark is either a calculation or a
judged artefact; this one is a knowledge sweep, and that is deliberate.

## The floor is 0.25, not 0.00 — read scores accordingly

Every item has four options, so a model answering at random scores about **0.25**
on any task in this family. A mean near 0.25 therefore means *no signal*, not
*poor knowledge*, and a rung is only discriminating once scores sit clearly
above it. This is the one number a reader of these results has to hold in mind,
and it is why the ladder climbs by making the *distractors* better rather than
the stems longer: a distractor that nobody would pick is a three-option item
with a 0.33 floor.

## Key distribution

Correct answers are spread across A/B/C/D within every file, on purpose. A
family whose key is usually B is passed by a model that always answers B, and
that model would look knowledgeable.

## Sample ids and `description` are PUBLISHED — do not name the answer in them

`GET /tasks/{id}` redacts `target` and nothing else. `sample.id`, `sample.input`,
`sample.metadata`, `description` and `tags` all go out verbatim, unauthenticated
(`ida_api.schemas.TaskDetail.of`).

That makes `tasks/SCHEMA.md`'s "name samples for what they probe" advice
**actively harmful here**, and it is the one place this family must depart from
it. The advice is safe for the numeric exemplar, where a method name is not a
number — but for a forced-choice item whose keyed option *is* a term, a sample
id like `limited-liability` or `diseconomies-of-scale` hands over the key. An
early draft of this family did exactly that in twelve items, and its rung-5
`description` enumerated all six misconceptions in sample order, which named
the option to avoid on every item and would have lifted a guesser from 0.25 to
0.33.

The same applies to `metadata.skill`, which is published verbatim. A skill slug
whose words appear in its own keyed option — `opportunity-cost` beside an option
reading "Is an opportunity cost…", `bottleneck-identification` beside "…because
it is the bottleneck" — hands over the key just as a sample id does. Name the
skill for the *situation type*, not the concept the key states.

So: **name a sample for its SCENARIO, not its answer** — `corporate-form-feature`
rather than `limited-liability`, `serial-line-investment-priority` rather than
`invest-at-the-bottleneck`. Everything explanatory goes in a YAML comment, which
is never parsed and never served.

## The other authoring trap in this family

`exact_match` targets here are single letters, and the validator's
answer-leak tripwire searches sample `metadata` for the target as a standalone
token — treating `-` as a word boundary. So a metadata slug containing a
single-letter token (`e-commerce`, `plan-b`) beside a target of `e` or `b`
fails `make lint-tasks`. Keep slugs free of one-letter tokens; there is no
reason to have one.
