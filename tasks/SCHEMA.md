# Authoring tasks

**This is the one page you need to author a task family for IDA-LLM.** It
assumes you have never seen this repository before. Read it top to bottom the
first time; after that, use the contents below and the
[checklist](#the-pre-pr-checklist) at the end.

You do not need to run an agent, understand the harness, or write any Python. A
task is a YAML file. If you can write down a quiz question and its answer, you
can author one.

---

## Contents

1. [The 90-second version](#the-90-second-version)
2. [What you are authoring: samples, tasks, families](#what-you-are-authoring-samples-tasks-families)
3. [The difficulty ladder](#the-difficulty-ladder)
4. [The one decision that shapes everything: `kind`](#the-one-decision-that-shapes-everything-kind)
5. [Required fields](#required-fields)
6. [Verifiable tasks: scorers, gold answers, tolerance](#verifiable-tasks)
7. [Subjective tasks: rubrics with real anchors](#subjective-tasks)
8. [Dataset hygiene: what may and may not go in `tasks/`](#dataset-hygiene)
9. [Running the validator and the harness locally](#running-it-locally)
10. [Claiming and delivering a task family](#claiming-and-delivering-a-task-family)
11. [The pre-PR checklist](#the-pre-pr-checklist)

Two complete worked families ship in this repository and are the standard to
copy:

| | family | what it demonstrates |
|---|---|---|
| **verifiable** | [`tasks/quantitative-quiz/`](quantitative-quiz/) | 7 tasks on a difficulty ladder, 43 gold answers, tolerance chosen against the nearest wrong method |
| **subjective** | [`tasks/conceptual-grading/`](conceptual-grading/) | 5 tasks, fully anchored rubrics, criteria weighted so they pull against each other |

`tasks/demo/` is something else: two tiny tasks that exist so the end-to-end
tracer bullet has something to run. Do not copy them — copy the exemplars.

---

## The 90-second version

```yaml
version: 1
id: my-family/l1-something          # lowercase, `/` groups, globally unique
title: A human-readable title
kind: verifiable                    # or: subjective
domain: statistics
system_prompt: >-
  Instructions to the model, including the answer FORMAT you want.
scorer:
  kind: numeric_match               # exact_match | numeric_match | llm_judge
  tolerance: 0.01
  normalisation: { strip: true, collapse_whitespace: true, take_last_line: true }
tags: [my-family, ladder-l1]
samples:
  - id: first-item                  # path-safe, unique within the task
    input: "The prompt the model sees."
    # 3 + 4 = 7  <- put the derivation in a COMMENT, never in metadata
    target: "7"
    metadata: { skill: addition, provenance: synthetic }
```

Then:

```bash
make lint-tasks     # schema + semantic validation; this is also the CI gate
```

Everything below is the reasoning behind those fields.

---

## What you are authoring: samples, tasks, families

Three levels, and the platform treats them very differently.

| level | is | scored |
|---|---|---|
| **sample** | one prompt, one expected outcome | individually, pass/fail |
| **task** | one YAML file: a set of samples sharing a scorer, a system prompt and a skill | reported as a **mean over its samples** |
| **family** | a directory of related task files sharing an id prefix and a tag | not a platform concept — a convention for authors and readers |

The level that matters most is the **task**, because the task is the unit the
platform reports. A run produces one `mean_score` per (task, model). Everything
you put in one file gets averaged together; everything you split across files
stays separately visible.

That single fact drives every structural decision below.

### Task-family anatomy

A family is a directory under `tasks/` plus a shared id prefix:

```
tasks/quantitative-quiz/
├── l1-descriptive-key.yaml        id: quantitative-quiz/l1-descriptive-key
├── l2-spread-key.yaml             id: quantitative-quiz/l2-spread-key
├── l3-item-parameterisation.yaml  id: quantitative-quiz/l3-item-parameterisation
└── ...
```

Conventions that make a family navigable:

- **One directory, one family, one id prefix.** The directory name and the id
  prefix are the same string.
- **The filename matches the part of the id after the prefix.** `l2-spread-key`
  is in `l2-spread-key.yaml`. Nothing enforces this; a reader trying to find the
  file that produced a result will thank you.
- **Tag every task in the family with the family name**, plus its rung:
  `tags: [quantitative-quiz, ladder-l2, spread]`. There is no task-level
  `metadata` field — `tags` is where family membership lives, and it is exposed
  by the API, so a UI can group by it.
- **Every task in a family shares one `kind`.** A family that mixes verifiable
  and subjective tasks is two families that happen to share a directory. Split
  them.
- **6–8 tasks for a verifiable family, 4–6 for a subjective one** is the size
  that has worked. Fewer and the ladder has no rungs; more and nobody reviews
  the last three properly.

### Samples within a task

A task's samples should all probe the **same skill at the same difficulty**,
because they are averaged. Five samples is a good number: enough that one lucky
guess does not read as competence, few enough that you can verify every gold
answer by hand.

What varies between samples in a task is the *surface* — different numbers,
different wording, one negative value, one decimal answer — not the difficulty
and not the skill.

---

## The difficulty ladder

> **One rung = one task file.** Never one task file with easy and hard samples
> mixed together.

This is the convention most worth internalising, and the reason is arithmetic.
Suppose you write a ten-sample task with four trivial items and six hard ones. A
model that gets every trivial item and no hard one scores 0.4. So does a model
that gets four hard items and no trivial one. Those are wildly different models
and the platform cannot tell you which you have, because you averaged the
information away before it ever reached a result row.

Split them, and you get a **profile** instead of a number (illustrative shape,
not measured results):

```
l1-descriptive-key      1.00   ██████████
l2-spread-key           1.00   ██████████
l3-item-parameterisation 0.80  ████████
l4-distribution-key     0.83   ████████
l5-inference-key        0.43   ████
l6-regression-key       0.29   ███
l7-distractor-key       0.17   ██
```

That profile answers the question the platform exists to answer — *what can this
model be trusted with?* — and a single mean never can.

### Building a ladder

1. **Rung 1 is the floor, and it should be nearly free.** Its job is to tell you
   that a bad score higher up is about difficulty, not about the model being
   broken or your prompt format being unparseable. If every model scores 1.00 on
   rung 1, rung 1 is doing its job.
2. **Each rung adds exactly one demand.** In the exemplar family: rung 1 is one
   step of arithmetic; rung 2 adds *choosing between two methods*; rung 3 adds
   *instantiating a template*; rung 4 adds *an external reference*; rung 5 adds
   *an intermediate quantity*; rung 6 adds *chained items where an error
   propagates*; rung 7 adds *reasoning as a mistaken student rather than a
   correct one*. Say what the rung adds in the file's header comment.
3. **The top rung should be genuinely hard.** If your best model scores 1.00 on
   every rung, the ladder has no ceiling and stops discriminating the moment
   models improve.
4. **Number the rung in the id** (`l1-`, `l2-`) so the catalog sorts into ladder
   order, **and** in `tags` (`ladder-l3`) so it is machine-readable.

Numbering in the id does mean you cannot insert a rung between `l2` and `l3`
later without renaming — and **ids must never be reused for different content**
(see below). Inserting a rung means adding `l8` at the end or renumbering the
family in one deliberate commit. That cost is worth the readability; a family
whose rungs are not obvious from the listing does not get used as a ladder.

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

### The decision procedure

Ask, in this order:

1. **Can I write the answer down right now?** If yes → `verifiable`. Stop.
2. **Could I make it so, by constraining the question?** Very often yes, and
   this is the move worth learning. "Write a good multiple-choice distractor"
   has no single answer. "Here is a question and here is the specific
   misconception; what number does a student holding it produce?" has exactly
   one. Naming the misconception moved the task across the line. See
   [`l7-distractor-key.yaml`](quantitative-quiz/l7-distractor-key.yaml), which
   is the worked version of this.
3. **Is what I actually care about the reasoning, the framing or the
   pedagogy?** Then it is genuinely `subjective`, and it needs a rubric.

**Prefer `verifiable` wherever it is honest to.** It is scorable today, it costs
nothing to run, and its results are reproducible. A subjective task is a real
contribution but you will not see a number from it yet.

> **Subjective tasks do not produce scores yet.** The LLM-as-judge path is an
> interface in the walking skeleton
> (`ida_harness.scoring.LLMJudgeScorer` raises `NotImplementedError`). Subjective
> tasks load, validate, run against the model, and store their transcripts — but
> their results carry `scorable: false` and `score: null`. That is deliberate:
> a blank is honest, a zero would look like a failing model.
>
> **You do not have to mark this anywhere.** `kind: subjective` plus
> `scorer.kind: llm_judge` *is* the mechanism: `TaskSpec.is_scorable` becomes
> False, the API reports an `unscorable_reason`, and the UI shows "not yet
> scorable". Nothing in your file changes when the judge lands. Adding
> `not-yet-scorable` to `tags` is a convention the exemplars follow so a human
> scanning the listing sees it too.

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

The machine-checkable contract is
[`packages/core/ida_core/schemas/task.schema.json`](../packages/core/ida_core/schemas/task.schema.json);
CI validates every file against it — the `task-schema` job in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs
`python tools/validate_tasks.py` on every pull request.

Anything matching `**/*.yaml` or `**/*.yml` under `tasks/` whose filename does
**not** start with `_` is loaded as a task.

### `id` conventions

- Lowercase; `a-z 0-9 . _ - /`.
- Group with `/`: `statistics/hypothesis-selection`, `history/source-critique`.
- **Never reuse an id for different content.** A result row records the task id
  and the git SHA; changing what an id *means* silently invalidates comparisons
  against every result already stored. Renaming a task is a real decision, not a
  tidy-up.

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

Name samples for what they probe (`median-even-n`, `sd-population-divisor`), not
`s1`/`s2`. The id is what a reviewer sees in a failing result.

### `description`, and where the provenance goes

`description` is free text and is published by the API. Use it for what the task
measures, why it is its own rung, and — required, see
[dataset hygiene](#dataset-hygiene) — **where the content came from**.

---

## Verifiable tasks

### The sample record

A verifiable sample is three things and one comment:

```yaml
- id: weighted-mean-gradebook
  input: >-
    A quiz item reads: "A course grade is 20% quizzes, 30% midterm and 50%
    final. A student scores 82 on quizzes, 74 on the midterm and 91 on the
    final. Compute the course grade." Produce the value for the answer key.
  # 0.20*82 = 16.4; 0.30*74 = 22.2; 0.50*91 = 45.5; total = 84.1
  # Unweighted mean would be (82+74+91)/3 = 82.33 -- 1.77 away, far outside
  # the 0.01 tolerance, so the item still separates the two methods.
  target: "84.1"
  metadata: { skill: weighted-mean, provenance: synthetic }
```

**`input`** is exactly what the model sees, appended to the `system_prompt`.
Write out the full item; do not assume shared context.

**`target`** is the gold answer as a string. Rules:

- **One number, if the scorer is `numeric_match`.** A target the scorer cannot
  extract a number from is recorded as an *error*, not a failure — it will not
  silently pass and it will not take the rest of the run down.
- **No units, no currency symbol, no label.** `"336"`, not `"$336.00"`. Put the
  formatting demand in the `system_prompt` instead.
- **The target must not be liftable from the prompt without doing the work.**
  The thing to defend against is a model that copies **the last number of the
  prompt**, or echoes a figure the item just handed it, and passes. This bites
  hardest on invariance items ("the SD was 6.4; after shifting every value by 5,
  what is the SD?" — answer 6.4, quoted in the prompt and also the answer).
  Rephrase so at least one step is required:
  [`l2-spread-key.yaml`](quantitative-quiz/l2-spread-key.yaml) gives the
  *variance* and asks for the standard deviation.

  A target that merely *coincides* with one of the supplied data values is
  fine — for a mode it is unavoidable, since the mode is by definition a member
  of the data set, and a median often is too. `l1/mode-single` (target `5`) and
  `l2/iqr-tukey-hinges` (target `8`) both do this and both are sound: neither
  target is the last number in its prompt, and reaching it still requires the
  work. Check *liftability*, not string presence.
- **Avoid values that sit exactly on a rounding boundary.** `1092/144 = 7.5833`
  is a fine item; `1098/144 = 7.625` is not, because round-half-up and
  round-half-even disagree and your item has two defensible keys.

### Derivations go in comments, never in `metadata`

> **`metadata` is published. Targets are not.**
>
> `GET /tasks/{id}` **redacts every `target`** unless the caller holds the
> `author` role — publishing the answer key is both an integrity risk (anyone
> can tune against it) and a contamination risk (a scraped key reaches a future
> training corpus). But that endpoint returns `sample.metadata` **verbatim, to
> everyone, unauthenticated**.
>
> So a derivation in `metadata` hands out the very answer the redaction exists to
> protect. Put derivations, expected verdicts and author's notes in **YAML
> comments**. Comments are not parsed, are not part of `content_sha`, and never
> leave the repository — while still sitting right next to the target where a
> reviewer reading the PR will see them.

Every gold answer in the exemplar family carries its derivation in a comment.
That is not decoration: it is what makes 43 hand-computed keys reviewable. A key
nobody can check is a key nobody will trust.

Keep in `metadata` only things that are safe to publish and useful to a
consumer: `skill`, `difficulty`, `template`, `provenance`, `scenario`.

### Scorers

#### `exact_match`

String equality after normalisation. All-or-nothing: 1.0 or 0.0. If you want
partial credit, you want a `subjective` task.

#### `numeric_match`

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

#### `llm_judge`

Requires `scorer.rubric_id` to equal `rubric.id`. Not implemented yet — see
[above](#the-one-decision-that-shapes-everything-kind).

### Choosing a tolerance

There are two forces, and a tolerance has to satisfy both:

1. **Wide enough to admit correct answers.** If your item says "round to two
   decimal places", a correct answer can be up to `0.005` away from the exact
   value. A tolerance of `0` fails it. Two decimal places → `0.01`. Four →
   `0.001`. Money rounded to the cent → `0.011` if any exact value can land a
   half-cent from the target.

   **There is one tolerance per task, so it must admit the loosest rounding any
   item in the file asks for.** A file whose system prompt says "two decimal
   places" cannot use `0.001` even if most of its items are exact — one added
   item later and it marks a correctly-rounded correct answer wrong, silently.
   [`l4-distribution-key.yaml`](quantitative-quiz/l4-distribution-key.yaml)
   mixes two- and four-decimal items and therefore uses `0.01`, the looser of
   the two. If one item genuinely needs a tolerance the rest of the file cannot
   live with, that item belongs in a different task.
2. **Narrow enough to reject the nearest *wrong method*.** This is the half
   people forget, and it is the half that decides whether the item measures
   anything.

The procedure, and it takes two minutes per item:

> Work out what the most plausible *wrong* method gives. Write down the distance
> from the correct key. **The tolerance must be much smaller than that
> distance** — an order of magnitude is comfortable. Then record the distance in
> the comment beside the target.

Worked, from the exemplar family:

```yaml
  - id: sample-sd-small
    # ... sample sd of 4, 8, 6, 5, 3
    # sample variance = 14.8 / (5-1) = 3.7 ; sd = sqrt(3.7) = 1.9235... -> 1.92
    # Population divisor would give sqrt(14.8/5) = 1.72 -- 0.20 away.
    target: "1.92"
```

Tolerance `0.01`, gap to the wrong method `0.20`. Twenty times the tolerance:
the item still separates the two divisors, which is the entire reason the item
exists.

A tolerance wide enough to swallow a method error is a tolerance that stopped
measuring anything — and it fails silently, which is the worst way to fail.

When the gap is thin, **say so in the comment** rather than leaving it for a
reviewer to discover; `l5-inference-key.yaml`'s `one-proportion-z-statistic`
does exactly that.

### Normalisation — be explicit

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
show its working. Every task in the verifiable exemplar family uses it.

### Steering the answer format

Put answer-format instructions in the task's `system_prompt`, **not** in the
harness. The system prompt is versioned in git and its SHA is recorded on every
result; a hardcoded nudge inside the solver would not be, and would silently
change every historical comparison the day someone edits it.

A `system_prompt` that works, from the exemplar family:

```yaml
system_prompt: >-
  You are producing the answer key for an undergraduate introductory-statistics
  quiz. Use exactly the convention the item names. Round to two decimal places.
  Put the final numeric answer alone on the last line, with no units, no label
  and no other text on that line.
```

Note what it does: sets the role, pins the convention, pins the rounding, and
pins the output format precisely enough that `take_last_line` + `numeric_match`
can grade it. Every task in a family should share one system prompt, so that
differences between rungs are differences in difficulty and not in phrasing.

### Item-writing rules that are not about the schema

These are assessment-design rules. They are what separates an exemplar family
from a wall of arithmetic.

- **Pin every convention the item depends on.** "Compute the IQR" has at least
  four defensible answers because at least four quartile methods are in common
  use. An item with two defensible answers and one key is not a hard item, it is
  an **invalid** item. Name the method in the prompt.
- **Supply external reference values in the prompt.** If an item needs
  `P(Z < 1.28)`, give it. Otherwise you are measuring which table the model
  memorised, and you will mark a model wrong for reading a three-decimal table.
  See the design note at the top of
  [`l4-distribution-key.yaml`](quantitative-quiz/l4-distribution-key.yaml).
- **Ask for the quantity you want, not an intermediate.** And check that
  reporting the intermediate lands far outside your tolerance.
- **When several samples share one scenario, say so in a comment.** Five of the
  seven samples in `l6-regression-key.yaml` describe the same fitted line, which
  means a reviewer checks one regression instead of seven arithmetic chains.

---

## Subjective tasks

A subjective task replaces the gold answer with a **rubric**: a set of weighted
criteria a judge model grades the response against.

```yaml
kind: subjective
scorer:
  kind: llm_judge
  rubric_id: conceptual-grading-coverage-v1   # must equal rubric.id
rubric:
  id: conceptual-grading-coverage-v1
  scale_min: 0
  scale_max: 1
  criteria:
    - name: recall-of-present-points
      description: |-
        ...
      weight: 3.0
```

Version rubric ids (`-v1`, `-v2`) rather than editing them in place: a grade is
only comparable to grades produced by the same rubric.

### Criterion descriptions are written for the judge

The `description` is not documentation. It is **the instruction the judge model
reads when it grades**. Vague criteria produce noisy grades, and a criterion
that cannot be disagreed with cannot discriminate.

### The anchored-rubric template

> **An anchor is a description of observable behaviour at a score level.
> An adjective is not an anchor.**

"Thorough", "appropriate", "good quality", "clear" — two judges will read those
differently, and the difference becomes noise in your results. Replace every one
of them with a statement of what a response at that level actually *does*.

Use this shape for every criterion:

```yaml
    - name: <short-slug>
      description: |-
        <One question the judge is answering, in one sentence.>

        1.0 -- <what a response at this level does, observably>
        0.5 -- <what a response at this level does, observably>
        0.0 -- <what a response at this level does, observably>
      weight: <number>
```

**Use a literal block scalar (`|-`), not a folded one (`>-`).** Folding runs the
three anchors together into one paragraph and destroys the structure the judge
is meant to read.

A real one, from
[`l1-key-point-coverage.yaml`](conceptual-grading/l1-key-point-coverage.yaml):

```yaml
    - name: precision-against-false-credit
      description: |-
        Does the response avoid marking PRESENT any point the student answer
        does not contain? Credit given for something unsaid is the failure mode
        that makes an automated marker unusable, so it is weighted equally with
        recall.

        1.0 -- no point absent from the answer is marked PRESENT.
        0.5 -- one absent point is marked PRESENT, and the quoted evidence is at
               least related to it.
        0.0 -- an absent point is marked PRESENT with fabricated evidence, or
               two or more absent points are marked PRESENT.
      weight: 3.0
```

Notice: the anchors are **countable**. "One absent point" and "two or more" can
be checked. That is what makes two judges agree.

Three levels (1.0 / 0.5 / 0.0) is the right default. Five levels sound more
precise and are harder to anchor; if you cannot describe distinct observable
behaviour at each of five levels, you have three levels and three unlabelled gaps.

> **Anchors live inside the `description` string** because the schema has no
> per-level anchor field. That is a known limitation, not a preference — see
> [`Rubric`](../packages/core/ida_core/contracts.py). Following the template
> above keeps every rubric in the repository parseable in the same way, which is
> what a later structured-anchor field would need.

### Weights, and making criteria pull against each other

`weight` is relative and must be `> 0`. Weights are what stop a judge from
maximising the easy criteria and ignoring the one that matters.

The technique worth stealing from
[`l4-actionable-feedback.yaml`](conceptual-grading/l4-actionable-feedback.yaml):
that task asks for feedback a student can act on **without being told the
answer**. The easiest way to be actionable is to disclose the answer. So the two
criteria are weighted **equally, at 3.0**, and a response cannot buy one with
the other.

> If the real task has a tension in it, put the tension in the rubric. A rubric
> whose criteria all point the same way is measuring one thing under several
> names.

The other guard is a criterion that punishes the degenerate strategy.
`l5-key-independent-marking.yaml` rewards accepting correct-but-unconventional
answers — a grader could score well by accepting *everything*, so the rubric
carries a `not-uniformly-generous` criterion at weight 3.0 and the task carries a
sample that is unconventional **and wrong**. Ask yourself: *what is the laziest
response that scores 1.0 on my rubric?* Then write the criterion that catches it.

### Choosing samples for a subjective task

Coverage matters more than volume. Three or four samples per task, chosen to
span the judgement:

- one **clean** case where the right answer is unambiguous;
- one **borderline** case where two verdicts are defensible — grade the
  reasoning, not the verdict;
- one **trap**: an answer that looks right and is not, or looks wrong and is not;
- one where the honest answer is **"nothing is wrong"**. A family whose samples
  are all faulty teaches a grader to always find a fault, and a grader that
  always finds a fault is useless.

Say which is which in a comment above each sample. The exemplar family does this
on all twenty of its samples.

---

## Dataset hygiene

Everything in `tasks/` is committed to a public repository, published by an
unauthenticated API, and may be read by people outside the university. Three
rules, and none of them is optional.

### 1. No real student work. No PII. This is FERPA, not politeness.

Student coursework, exam answers, submitted essays and grade records are
**education records** under FERPA. They may not enter this repository — **not
even with names removed**, because short-answer text is often re-identifiable
from its content and the de-identification standard is higher than deleting a
name.

Write synthetic student answers instead. Every student answer in
`tasks/conceptual-grading/` was written for the file, imitating the *shape* of
undergraduate work without being any student's work. It is not hard, it takes
about ten minutes per task, and it makes the family redistributable.

The same rule covers instructor material that identifies individuals, real
gradebook data, and anything from a course's LMS.

### 2. No copyrighted textbook content.

Do not copy questions, exercises, data sets or worked examples out of a
textbook, a published question bank, a commercial test-prep product or another
institution's exam. Reproducing them here is republication.

Write your own items. If an item needs to look like a familiar textbook problem,
that is fine — the *idea* of a two-sample t-test problem is not copyrightable,
the publisher's particular wording and numbers are. Change both.

### 3. State the provenance of every task, in its `description`.

One sentence, in the task's `description`, saying where the content came from:

```yaml
description: >
  ...

  Provenance: every data set is synthetic, authored for this file. No textbook
  content, no real student data.
```

And per-sample, in `metadata`:

```yaml
    metadata: { skill: weighted-mean, provenance: synthetic }
```

Usual values: `synthetic` (you wrote it), `public-domain`, `cc-by` (say which
work, in the description), `instructor-authored` (a member of staff wrote it for
this purpose and has agreed to its publication).

> There is no schema field for provenance and nothing enforces this — the
> top-level schema forbids unknown keys, so `description` and sample `metadata`
> are the two places it can live. Reviewers should refuse a task family with no
> provenance statement.

### And the one that is easy to get wrong

**Sample `metadata` is published unauthenticated.** Targets are redacted;
metadata is not. Never put an answer, a derivation, or anything you would not
publish into `metadata`. Use a YAML comment. This is restated here because it is
the mistake most likely to be made by someone who has understood everything
else.

---

## Running it locally

### The validator — the fast loop

```bash
make lint-tasks
```

This is exactly what the `task-schema` CI job runs. It checks **both** layers
(the JSON Schema and the pydantic contracts), validates `models.yaml` too, and
reports *every* problem rather than stopping at the first — so one pass gives
you the whole list. Run it after every file you write.

Output for a healthy tree looks like:

```
  ok  .../tasks/quantitative-quiz/l1-descriptive-key.yaml  (verifiable, numeric_match, 6 sample(s), scorable)
  ok  .../tasks/conceptual-grading/l1-key-point-coverage.yaml  (subjective, llm_judge, 4 sample(s), NOT YET SCORABLE)
...
All authored content is valid.
```

`NOT YET SCORABLE` on a subjective task is the expected, correct output. It is
not a warning.

### The harness — running your task against the mock model

The validator proves your file is *well-formed*. Running it proves the prompts
and the normalisation actually work together. Do this before you open the PR for
any verifiable family.

```bash
make dev          # postgres, redis, minio, the mock model, api, runner, frontend
```

Then fire a run at your task:

```bash
curl -sS -X POST localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"task_ids":["quantitative-quiz/l1-descriptive-key"],
       "model_keys":["mock"],
       "label":"authoring check"}'
```

Watch it at <http://localhost:3000>, or fetch the result:

```bash
curl -sS localhost:8000/runs | python3 -m json.tool
```

`make down` stops the stack; `make clean` also deletes its volumes.

> **What the mock is and is not.** `mock` is a deterministic canned-answer
> service, not a language model. It evaluates a single `a <op> b` expression if
> it finds one and otherwise returns a stable hash-derived sentence. **A low
> score against the mock means nothing about your task.** What you are checking
> is that the run reaches `succeeded`, that every sample produced a transcript,
> that no sample carries an `error`, and that the scorer's `explanation` shows
> the two values it compared — which tells you whether your normalisation is
> doing what you meant.
>
> A sample recorded with an **error** *is* a real problem and usually means the
> target is unparseable. Fix it.

### Everything CI will run

```bash
make lint         # ruff + lint-tasks + frontend
make test         # pytest across packages/ and services/, plus the e2e tracer
make ci           # the six PR gates, minus the ones that need a cluster
```

For a tasks-only change, `make lint-tasks && make test-python` is the honest
minimum: the harness tests load every task in `tasks/`, so a broken file fails
there too.

**Read the output.** A command that scrolled past is not a command that passed.

---

## Claiming and delivering a task family

The board is the source of truth for who is doing what. The loop, end to end:

1. **Claim the item on the board.** Find the task-family item, assign it to
   yourself, and move it to *Active* — this is the "Start work" step, and it is
   what stops two people authoring the same family.
2. **Branch off fresh `main`.**
   ```bash
   git fetch origin && git checkout main && git pull
   git checkout -b tasks/<your-family-name>
   ```
3. **Author the family.** One directory, one id prefix, one rung per file. Copy
   the exemplar closest to your `kind`.
4. **Get the validator green.** `make lint-tasks`, then `make test-python`.
5. **Commit, with the board id in every commit message.** The integration links
   commits to the work item by the `AB#<id>` mention, so a commit without it is
   invisible on the board:
   ```
   feat(tasks): a quantitative-quiz family across seven difficulty rungs

   <what the family measures, and any judgement calls a reviewer should check>

   AB#42
   ```
6. **Open the PR.** Put `AB#<id>` in the **title** and in the **body**. In the
   body, tell the reviewer what to check: which gold answers you computed by
   hand, which items have a thin tolerance margin, where the content came from.
7. **Six CI gates must be green** — `python`, `frontend`, `agile`, `task-schema`,
   `migrations`, `chart`. `task-schema` is the one your work will trip; the
   others must stay green, which for a tasks-only change means you did not touch
   anything else.
8. **Merge resolves the item.** Move it to *Resolved*/*Closed* on the board when
   the PR lands.

### What a reviewer will check

Author as if this list is the review, because it is:

- Every gold answer, re-derived independently. Your comments make this possible;
  without them a reviewer either takes the key on trust or does not review it.
- Every tolerance against the nearest wrong method.
- That the rungs are actually ordered, and that each one adds a stated demand.
- That every rubric criterion has behavioural anchors, not adjectives.
- That the provenance statement is there and is true.
- That nothing in `metadata` leaks an answer.

---

## The pre-PR checklist

Structure:

- [ ] One directory, one family, one id prefix, one `kind`.
- [ ] One difficulty rung per task file; the rung is in the id **and** in `tags`.
- [ ] Rung 1 is nearly free; the top rung is genuinely hard.
- [ ] Every task in the family shares one `system_prompt` style.
- [ ] Sample ids are path-safe, unique within the task, and named for what they
      probe.
- [ ] No task id reuses an id that has ever meant something else.

Verifiable tasks:

- [ ] `kind` matches reality — could you write the answer down? then `verifiable`.
- [ ] Every sample has a `target`; no `rubric` anywhere in the file.
- [ ] A `numeric_match` target contains exactly one number, no units, no symbols.
- [ ] **Every target carries its derivation in a YAML comment** — and nothing
      answer-shaped is in `metadata`.
- [ ] The target is not liftable from the prompt — in particular it is not the
      last number in the `input`. (Coinciding with a supplied data value is
      fine: a mode always does.)
- [ ] No target sits on a rounding boundary.
- [ ] Tolerance is wide enough for the rounding you asked for and at least ~10×
      narrower than the distance to the nearest wrong method — and that distance
      is recorded in the comment.
- [ ] Every convention the item depends on is pinned in the prompt.
- [ ] Every external reference value the item needs is supplied in the prompt.
- [ ] Normalisation is stated, not assumed.
- [ ] No `strip_punctuation` on a `numeric_match` task (both layers reject it).

Subjective tasks:

- [ ] No sample has a `target`; `scorer.rubric_id` equals `rubric.id`.
- [ ] The rubric id is versioned (`-v1`), and you did not edit an existing one in
      place.
- [ ] Every criterion `description` uses `|-` and states observable behaviour at
      1.0 / 0.5 / 0.0. No adjectives standing in for anchors.
- [ ] Anchors are countable wherever they can be.
- [ ] Weights reflect what matters, and any real tension in the task is a pair of
      equally weighted criteria.
- [ ] You asked "what is the laziest response that scores 1.0?" and wrote the
      criterion that catches it.
- [ ] Samples span clean / borderline / trap / nothing-is-wrong, and a comment
      says which is which.

Hygiene:

- [ ] No real student work, anywhere, however anonymised. (FERPA.)
- [ ] No textbook, question-bank or other institution's exam content.
- [ ] A provenance sentence in every task's `description`, and `provenance` in
      every sample's `metadata`.

Green:

- [ ] `make lint-tasks` passes, and you read its output.
- [ ] `make test-python` passes.
- [ ] For a verifiable family: you ran it against the mock and every sample came
      back without an `error`.
- [ ] `AB#<id>` is in every commit message, the PR title and the PR body.
