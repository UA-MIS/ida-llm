# Benchmark methodology

What this platform measures, how a measurement becomes a number, what that
number is allowed to mean, and how we intend to find out whether it is true.

Read with: [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) (authoring) ·
[`docs/llm-judge.md`](llm-judge.md) (subjective scoring) ·
[`docs/calibration.md`](calibration.md) (harness calibration) ·
[`docs/harness-fairness.md`](harness-fairness.md) (what makes a comparison fair)

---

## The one-paragraph version

A benchmark task is a YAML file of samples anchored to a **Student Learning
Outcome** and a **use mode**. Every task is exactly one of two `kind`s:
**`verifiable`**, where a gold answer exists and a program grades it, or
**`subjective`**, where no gold answer exists and a rubric is graded by a second
model. That split is the platform's spine — it decides how a task can ever be
scored, what it costs to run, and how much a resulting number can be trusted.
Scores aggregate as a mean over *scored* samples, never over attempted ones, and
every score carries the serving config and task content hash that make it a
number *about something*. The verifiable path ships and runs today; the
subjective path ships and is off until an operator configures and pays for a
judge model. Neither has yet been validated against human graders — that study
is designed below and has not been run.

---

## The two axes

Every benchmark task is filed on both, and neither is derivable from the other.

### Axis 1 — the outcome (`slo:SLO1` … `slo:SLO9`)

The nine BScBA Student Learning Outcomes, held as validated data in
[`curriculum/slo.yaml`](../curriculum/slo.yaml) with a JSON Schema, a loader and
a CI gate. Two outcomes — **SLO5 Teamwork** and **SLO8 Oral Communication** —
are marked `text_benchmarkable: false` and the validator refuses any task
claiming them. That is a decision recorded in the file, not a gap: a single-turn
text prompt can at best measure whether a model can *write about* teamwork, and
filing that under Teamwork would be the most misleading thing this repository
could publish. A benchmark covering seven outcomes must not be mistaken for a
programme that has seven.

### Axis 2 — the use mode (`use-mode:<id>`)

*What is being asked of the model.* An outcome is not one question: "can the
model do the coursework" and "can the model help a student do it" have different
right answers and very different consequences, and a platform that averaged them
would answer neither.

| mode | the model is | the candidate is | status |
|---|---|---|---|
| `capability` | the student | the model | **in use** — every authored family today |
| `assistive` | a tutor | the student's understanding | declared, `in_use: false` — spec'd in [`docs/learning-aid-spec.md`](learning-aid-spec.md) |
| `instructional` | staff (authors items, applies a marking key, grades) | the model | declared, `in_use: false` |

> ⚠ **The vocabulary is currently ambiguous and must be settled before a second
> family is authored.** [`docs/researcher-track.md`](researcher-track.md) uses
> `use-mode-assist` for the *staff-facing* mode that `slo.yaml` calls
> `instructional`, and `use-mode-learning-aid` for the *student-facing* mode
> that `slo.yaml` calls `assistive`. The two spellings name opposite sides of
> the exchange. This document and the learning-aid spec follow `slo.yaml`,
> because that is the file with the CI gate. See
> [the callout in the learning-aid spec](learning-aid-spec.md#-before-anything-is-authored-the-use-mode-vocabulary-is-ambiguous).

The axes are independent by construction, which is why `use-mode` is a separate
tag rather than a suffix on the outcome. A model can be excellent at tutoring
SLO2 and unable to do SLO2 itself; averaging those is how a recommendation ends
up recommending the wrong thing.

**Group by `tags`, drill down by sample `metadata`.** Both spellings of each
fact are required to agree — `check_task_tags` rejects a task whose tag says
`SLO2` and whose sample metadata says `SLO9` — because two spellings of one fact
is a drift risk and a silent one.

---

## Verifiable scoring

**Ask first whether the task can be verifiable, and prefer it wherever that is
honest.** It costs nothing to run, needs no judge model, and produces a number
whose derivation a reviewer can check by hand. The decision procedure is in
[`tasks/SCHEMA.md`](../tasks/SCHEMA.md#the-decision-procedure), and its middle
step is the one worth learning: *many subjective-looking tasks become verifiable
if you constrain the question.* "Write a good multiple-choice distractor" has no
single answer; "here is a question and here is the specific misconception — what
number does a student holding it produce?" has exactly one. Naming the
misconception moved the task across the line.

> **Provenance.** The task-type taxonomy underneath this split — which question
> shapes belong on which side, and why multiple-choice items are a poor fit for
> `verifiable` because they can be gamed by elimination — was worked out
> separately in
> [`docs/Methodology/Verifiable vs. subjective.md`](Methodology/Verifiable%20vs.%20subjective.md).
> That note is the authoring-side view; this section is the scoring-side view of
> the same decision.

### The two scorers

| | `exact_match` | `numeric_match` |
|---|---|---|
| compares | strings, after normalisation | the **last** number in the completion |
| result | 1.0 or 0.0, no partial credit | 1.0 or 0.0, within tolerance |
| tolerance | n/a | `tolerance` (absolute) or `relative_tolerance`; passes on **either**; both default to `0` |

`numeric_match` takes the **last** number because models restate the question
before answering, so the first number is usually an input. The standard recipe
is `take_last_line: true` plus a `system_prompt` that pins the output format —
which is what lets a model show its working and still be graded on its
conclusion.

**Normalisation is explicit, ordered and symmetric.** Nothing is stripped,
lowered or collapsed unless the task says so, the order is fixed
(`take_last_line` → `strip` → `collapse_whitespace` → `strip_punctuation` →
`lowercase`), and **whatever is applied to the completion is applied to the
target too**. An asymmetric comparison silently marks correct answers wrong,
which in a benchmarking platform is data corruption that propagates all the way
into a recommendation.
([`scoring.py`](../packages/harness/ida_harness/scoring.py))

### Tolerance is an assessment decision, not a config value

This is the part of verifiable scoring that decides whether an item measures
anything, and it is easy to get silently wrong in the permissive direction.

A tolerance must be **wide enough to admit a correctly-rounded correct answer**
and **narrow enough to reject the nearest wrong method**. The second half is the
one people forget. The procedure — work out what the most plausible wrong method
yields, write down the distance, keep the tolerance an order of magnitude below
it, and record the distance in a comment beside the target — is what makes 43
hand-computed gold answers reviewable rather than merely present.

> A tolerance wide enough to swallow a method error is a tolerance that stopped
> measuring anything, and it fails **silently**, which is the worst way to fail.

**Item validity is part of the methodology, not a detail of authoring.** An item
with two defensible answers and one key is not a hard item, it is an *invalid*
one — "compute the IQR" has at least four defensible answers because at least
four quartile methods are in common use. Every convention an item depends on is
pinned in the prompt, and external reference values (a `P(Z < 1.28)`) are
supplied in the prompt, because otherwise the benchmark measures which table the
model memorised.

---

## Subjective scoring

A `subjective` task has no gold answer and is graded against a **rubric** by a
second model. The full contract is [`docs/llm-judge.md`](llm-judge.md); the
methodologically load-bearing parts are these.

**One judge call per criterion.** Not one per rubric. It costs N calls instead
of 1 and buys three things: **order independence** (no call sees two criteria,
so reordering a rubric cannot move a score), **no self-anchoring** (a judge that
has just written "0.2" is reluctant to then write "0.9" about the same text),
and **isolated failure** (a malformed reply costs one criterion, not the
rubric).

**The judge is shown the criterion and withheld everything that could bias it** —
not its weight (a judge told a criterion is "worth 3" grades it more harshly),
not its position, not how many criteria exist, not any other criterion's text or
verdict.

**Anchors reach the judge verbatim.** The anchor levels live inside the
criterion's `description`, and that whole string is inserted uncut; a test fails
if anything starts summarising it, because summarising would silently regrade
every task using the rubric.

**Anchors are observable behaviour, not adjectives.** "Thorough", "appropriate",
"clear" — two judges read those differently and the difference becomes noise in
the results. The exemplar's anchors are *countable* ("one absent point", "two or
more"), which is what makes two graders agree.

**Aggregation.** Each criterion is normalised from the rubric's scale onto
`[0, 1]`, then combined as a weighted mean:

```
normalised_i = (raw_i - scale_min) / (scale_max - scale_min)
value        = Σ(wᵢ · normalisedᵢ) / Σ wᵢ
```

Weights are relative — `[2,2,1,1]` and `[4,4,2,2]` produce the same number — and
`Score.passed` stays `None`, because a rubric-weighted score is graded by
construction and forcing it through a threshold would put a cutoff nobody chose
into every downstream comparison.

**Rubrics are versioned, never edited in place.** A grade is only comparable to
grades from the same rubric id, and editing one in place additionally makes
finished runs un-regradable — `regrade` compares the task's recorded
`content_sha` against the current one and refuses.

**Grading is off by default.** With no `IDA_JUDGE_MODEL_KEY`, subjective runs
record `scorable=false`, `score=null` and archive their transcripts, and are
gradable later from those transcripts without re-calling the model under test. A
blank is honest; a zero would look like a failing model.

---

## Aggregation: what a mean is a mean over

One rule, and it is the same at every level: **the denominator is scored
samples, never attempted ones.**

- Within a task, `EvalLog.mean_score` averages over samples that produced a
  score. Errored and unscorable samples are excluded and counted separately —
  **our outage is not the model's failure**, and counting an error as 0.0 would
  attribute a network fault to the model.
- Across tasks, [`calibration.py`](../packages/harness/ida_harness/calibration.py)
  weights by **scored samples, not by task**. A reference spanning an 8-sample
  and a 2-sample task is one 10-sample measurement; averaging the two task means
  would quietly give each sample of the smaller task four times the weight — a
  different statistic from the one every published benchmark reports.
- `error_count` travels with every mean, because `scored_count < sample_count`
  is otherwise ambiguous between "some calls failed" and "this task is not
  scorable yet", and those must never be confused.

**A run whose samples all errored is `failed`, never `succeeded`,** and reports
no measured score at all — `None`, never `0.0`. *We measured zero* is a claim
about the model; *we measured nothing* is a claim about the run. The full
inventory of places this platform refuses to emit a zero is in
[`docs/harness-fairness.md`](harness-fairness.md#not-measured-is-not-zero).

---

## What a score is a number *about*

A number with no referent is not evidence, so every result carries its referent
by value (**D-1**, **D-13**):

| stamped on every result | why |
|---|---|
| `serving_config` — model id, serving stack, quantization, revision, **effective** sampling params | the same model id at two temperatures is two measurements |
| `task_content_sha` | the canonical hash of *this task*; edit the task, and old results stop claiming comparability |
| `task_git_sha` | repo provenance |
| `harness_version` | the code that produced it |
| `judge_serving_config`, `judge_usage`, `judge_cost_usd` (subjective) | a grade is a function of the judge too, and is priced at a different model's rate |
| `score_details.protocol_version` (`ida-judge/1`) | grades are comparable **within** a protocol version; the constant bumps when the judge prompt changes, so old grades stop claiming comparability to new ones |

Candidate spend and judge spend are recorded separately and **never summed for
you**. Folding them would be unrecoverable: a cheap model graded by an expensive
judge would read as an expensive model forever.

---

## Validating the scores

Three different things get called "validation" around this project and they
check different objects. Confusing them is how a platform ends up asking a judge
whether it agrees with itself.

| | **harness calibration** | **judge calibration** | **item validity** |
|---|---|---|---|
| the question | does our *harness* reproduce a number the field already knows? | does our *judge model* grade like a human? | does this *item* separate right from wrong? |
| object under test | the measuring instrument end to end | the judge | the task file |
| runs against | `verifiable` tasks | `subjective` tasks | either |
| compared to | a published benchmark score | human ratings of the same samples | the nearest wrong method |
| implemented in | [`ida_harness.calibration`](../packages/harness/ida_harness/calibration.py) | `ida_runner.sweeps.run_judge_calibration` (grading path) | `make lint-tasks` + review |
| status | **ships; no real slice authored yet** | **record shape ships; study not run** | **enforced by convention and review** |
| docs | [`calibration.md`](calibration.md) | below | [`SCHEMA.md`](../tasks/SCHEMA.md#choosing-a-tolerance) |

### Harness calibration — shipped

Run a slice of a public benchmark through this harness against a model whose
score somebody else has published, and compare. Agreement means the path from
task YAML through prompt assembly, sampling, normalisation, scorer and
aggregation is not bending anything. **Disagreement means every score this
platform publishes is suspect until the cause is found.**

Four refusals make the check honest, each because the obvious implementation
would produce a confident false statement: a run with errors never reports
agreement whatever the arithmetic says; aggregation is weighted by scored
samples; the comparison is never nudged (rounding happens only in the printed
table, so it cannot flip a verdict); and a published number with no citation is
not evidence — `published_source` and `published_retrieved` are required and a
`TODO-PLACEHOLDER` cannot be `within_tolerance`. Comparing a number published
for model A against a run of model B is refused outright: that is not a weak
result, it is a result about neither.

**Set `tolerance` from the slice size before you see the result.** A tolerance
chosen afterwards is a tolerance somebody tuned. And note the honest limit: the
module checks a number a human wrote down; it does not derive a confidence
interval from the slice size. That is a smaller claim, and it is the one the
code supports.

### Judge calibration — designed, not run

**The record shape a validation study needs already exists**, which is worth
stating so nobody builds it twice. `results.score_criteria` holds one row per
criterion per grade — `name`, `value` normalised to `[0,1]`, `weight`, and the
judge's `explanation` — so "how does the judge score criterion X across all
samples?" is a query, not a re-run, and the weighted total is reconstructible
from the rows alone (pinned by test). A human-agreement study therefore needs a
table of human ratings joined on `(run_id, sample_id, criterion)` **and nothing
from us**.

What has not happened is the study. Its design, all of it provisional:

**1. Sample the samples.** Draw from graded rows stratified by task family and
by judge score, deliberately over-sampling the middle of the range — agreement
at the extremes is cheap and uninformative, and the 0.5 anchor is where rubrics
actually fail.

> **Provisional (pending professor interviews and grader availability):** 100–150
> (sample, criterion) pairs, which at three-to-five criteria per rubric is 25–50
> distinct responses. Sized to what Nick's graders can be asked for, not from a
> power calculation.

**2. Two or more independent graders per pair.** Independent is the operative
word: graders must not see the judge's score, the judge's rationale, each
other's ratings, or which model produced the response. They see what the judge
sees — the task, the prompt, the response, and the one criterion's anchors
verbatim — and nothing else. Anything more and the study measures agreement with
a suggestion.

**3. Report human–human agreement first.** This is the step most easily skipped
and the one that makes the rest interpretable. **Human–human agreement is the
ceiling**, not 1.0. If two trained graders agree at α = 0.6 on a criterion, a
judge that agrees with them at α = 0.55 is essentially at ceiling, and a rubric
that produced α = 0.6 among humans is a rubric with a specification problem —
which is a finding about the *anchors*, not about the judge. Diagnose the rubric
before blaming the model.

> **Provisional:** the statistic. Anchors are ordinal with three levels
> (1.0 / 0.5 / 0.0), so quadratic-weighted Cohen's κ per criterion pair, or
> Krippendorff's α with an ordinal difference function when grader counts vary
> per item. Report per criterion, never pooled — a rubric can have one
> unusable criterion and four excellent ones, and a pooled number hides exactly
> that.

**4. Pre-register the threshold.** Write down, before seeing results, what
judge–human agreement would make the judge usable — expressed as a fraction of
the human–human ceiling, not as an absolute. This mirrors the tolerance rule in
harness calibration for the same reason: a threshold chosen afterwards is a
threshold somebody tuned.

**5. Report per criterion and act per criterion.** A criterion where the judge
disagrees with humans is a criterion to rewrite (usually its anchors are not
countable), not a reason to discard the rubric. Bump the rubric id when you
rewrite it.

**Cost is not incidental to this design.** Judging is one call per criterion per
sample, and human grading is the scarcer resource — Nick provides graders "as
needed", which is a budget, not an infinity. Size the study against grader hours
first and judge dollars second.

### The first real judged run — what it exercised (2026-08-28)

The subjective path first ran against a **real** judge — not the canned mock — in
a single bounded run over the full catalogue. It is **not** a validation study:
no human graded anything, so it moves nothing in the table above out of its
"not run" status. But it exercised two paths the mock never could, and both are
worth recording so they are not re-discovered.

**Graceful degradation under an unparseable reply is not hypothetical.** A small
fraction of judge calls — a handful of criteria, well under one percent of all
judge calls that run — returned a reply the strict parser rejected
(`JudgeResponseError`). Every one degraded exactly as
[`docs/llm-judge.md`](llm-judge.md#nothing-becomes-a-grade-by-accident)
specifies: the affected sample recorded `score=null`, its raw reply was archived
verbatim, the *other* criteria on the same sample still scored, and nothing was
fabricated to fill the gap. Those samples remain gradable later from their transcripts, bounded by
`results.judge_attempts` (migration `0005`) so a permanently-unparseable sample
cannot be re-nominated forever. This is the "isolated failure" property of
one-call-per-criterion and the *our outage is not the model's failure* rule of
[aggregation](#aggregation-what-a-mean-is-a-mean-over), observed rather than
asserted.

**The counterweight items were confirmed by a real judge — an item-validity
result, not a judge–human one.** Several subjective families carry
*counterweight* samples: inputs authored so that the reflex answer which aces a
paired sample **fails** here (for example, a scenario supplying a lawful route
so that "breach the constraint" is the wrong move). They exist to catch a rubric
that rewards a single reflex regardless of whether it fits — and a canned mock
judge, which returns the same number to every input, can never test them. Under
the real judge, every counterweight sample scored **well above the `0.5` midpoint
anchor**: the rubric rewarded the restrained, correct answer instead of
penalising it. That closes a gap the mock left open, but it belongs in the
**item-validity** column of the table above, not the judge-calibration one — it
shows the anchors are not one-sided, not that the judge grades like a human. The
human-agreement study is still un-run.

---

## What this methodology does not claim

- **No number here has been validated against a human.** Neither calibration
  study has run. Every score the platform currently produces is the output of a
  well-specified procedure, which is not the same as a correct one.
- **The subjective path measures agreement with a rubric, not truth.** If the
  rubric is wrong, a perfectly-behaving judge reproduces the error at scale and
  with high confidence — which is the failure mode item validity and judge
  calibration exist to catch, and neither has caught anything yet because
  neither has been run.
- **Cross-model comparability has known holes**, most of them properties of the
  models rather than of the harness — a reasoning model forced to
  `temperature: 1.0` is not comparable to a greedy-decoded one. They are
  enumerated in [`docs/harness-fairness.md`](harness-fairness.md).
- **Two of the nine outcomes are out of scope, on purpose**, and seven-outcome
  coverage must not be reported as programme coverage.
- **Only `capability` has authored families.** The other two use modes are
  declared vocabulary and a spec. Any statement about how models perform as
  tutors or as staff is, today, a hypothesis.
