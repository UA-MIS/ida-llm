# Learning aid vs answer engine

How to measure whether a model **helps a student learn** something, as opposed
to **doing it for them** — and the rubric a judge applies to decide.

Feeds: the future `use-mode` task families under [`tasks/`](../tasks/) ·
graded by [`docs/llm-judge.md`](llm-judge.md) · authored per
[`tasks/SCHEMA.md` → Subjective tasks](../tasks/SCHEMA.md#subjective-tasks) ·
fairness constraints in [`docs/harness-fairness.md`](harness-fairness.md)

---

## The one-paragraph version

A student asks a model for help with coursework. The model can end that
exchange in two very different states: the work is done and the student has
learned nothing, or the work is not done and the student can now take the next
step themselves. Both look like "helpful". This document defines the observable
difference, turns it into a five-criterion anchored rubric
(`learning-aid-v1`) an LLM judge can apply one criterion at a time, and names
the two degenerate strategies the rubric exists to catch — the **answer dump**,
and its mirror image, the **stonewall**. The rubric is `kind: subjective`,
`scorer.kind: llm_judge`, and therefore costs five judge calls per sample and
needs `IDA_JUDGE_MODEL_KEY` set.

---

## ⚠ Before anything is authored: the use-mode vocabulary is ambiguous

**This spec cannot pick its own `use-mode:` tag, and the choice is not
cosmetic.** Two vocabularies exist in this repository and they disagree about
what the words mean:

| | `curriculum/slo.yaml` (schema-validated, CI-gated) | [`docs/researcher-track.md`](researcher-track.md) (free-form tags, D-47) |
|---|---|---|
| model does the coursework | `capability` | `use-mode-capability` |
| model **tutors the student** | **`assistive`** — "the model is a tutor and the student is the candidate" | **`use-mode-learning-aid`** |
| model **does the staff's side** | **`instructional`** — "author an item, apply a marking key, grade against a rubric. The model is staff." | **`use-mode-assist`** — "helping the professor do their own work" |

So the word **`assistive`** in `slo.yaml` and the word **`assist`** in the
researcher track name **opposite sides of the exchange**, and `instructional`
reads to most people as "the student-instruction one" while `slo.yaml` defines
it as the staff-facing one.

The failure this produces is the exact one
[`curriculum/README.md`](../curriculum/README.md) was written to prevent: the
task loads, the run succeeds, the score is real, and it is filed under a heading
that means something else. Nothing errors, because both spellings are legal.

**This document is written against `curriculum/slo.yaml`**, because that file is
the one with a JSON Schema, a loader with cross-field validation, and a CI gate
(`validate_tasks.py` rejects a `use-mode:` naming a mode that is not
`in_use: true`). By that vocabulary, everything below is
**`use-mode:assistive`**.

> **Provisional (pending a decision, not an interview):** the tag for these
> tasks is `use-mode:assistive`, and `assistive.in_use` must be flipped to
> `true` in `slo.yaml` before the first family can pass CI. If the project
> prefers the researcher track's spelling, the rename is a `slo.yaml` edit plus
> a re-tag — **cheap now, and irreversible-in-practice once result rows carry
> the old spelling**, since a result records the task id and its tags and
> nothing re-writes history. Settle it before the first family merges.

---

## What is actually being measured

The candidate is **the model as tutor**. The thing being scored is a *single
response to a student who is stuck*, and the question is whether that response
moved the student's own understanding or replaced it.

Three things follow, and they shape every criterion below.

**The student's cognitive work is the resource being spent.** An answer dump
spends all of it at once; a good tutoring turn spends exactly one step of it.
This is why the rubric's heaviest criteria are a *pair* — one that penalises
disclosure and one that penalises withholding — rather than a single
"pedagogical quality" score.

**Correctness does not stop mattering.** A tutor that avoids the answer by being
vague, and vague by being wrong, is worse than an answer engine: the student
does work, and the work goes the wrong way. Politeness and Socratic tone are
extremely cheap to produce, and a rubric that rewarded them without a
correctness floor would rank a confident wrong hint above a plain correct one.

**Only one turn is observable today.** The harness ships exactly one solver,
[`SingleTurnSolver`](../packages/harness/ida_harness/solver.py) — one system
message plus one user message, one completion. Real tutoring is a loop, and this
rubric grades a single move in it. See
[What this does not measure](#what-this-does-not-measure); it is the largest
honest limit in this document and it is a property of the harness, not of the
rubric.

---

## The two degenerate strategies

[`tasks/SCHEMA.md`](../tasks/SCHEMA.md#weights-and-making-criteria-pull-against-each-other)
asks the question that decides whether a rubric measures anything: *what is the
laziest response that scores 1.0?* Here there are two, they are opposites, and a
rubric that catches only one is worse than no rubric — it teaches the platform
to prefer the other.

### The answer dump

> "Sure! The sample standard deviation is 1.92. Here's the work: the mean is
> 5.2, the squared deviations sum to 14.8, divide by n−1 = 4 to get 3.7, and
> √3.7 = 1.92."

Correct, complete, well-organised, and the student has learned that this model
answers questions. Every generic "was this response helpful" rubric scores it
highly, which is precisely why this family needs its own.

### The stonewall

> "I can't just give you the answer — that wouldn't help you learn! What do
> *you* think the first step should be? 🤔"

This is what a model produces when it has been told to be Socratic and given no
way to be useful. It withholds perfectly, engages with nothing, and leaves a
stuck student exactly as stuck. It is the response a naive "did it withhold the
answer?" rubric ranks **first**.

**The rubric below is built so that neither can reach the top.** Criteria 1 and
2 are weighted **equally at 3.0** and pull in opposite directions, the technique
[`l4-actionable-feedback.yaml`](../tasks/conceptual-grading/l4-actionable-feedback.yaml)
already uses for the same reason — a response must not be able to buy one with
the other.

---

## The five signals, operationalised

Each is stated as something a judge can look for in the text, not as an
adjective. The rubric in the next section is these five, anchored.

| # | signal | the observable | the fake version it must exclude |
|---|---|---|---|
| 1 | **withholds the terminal answer** | the artifact the student was asked to produce is not present in a copyable form, and no stated chain terminates on it | "I won't tell you… it's 1.92." Disclosure at the end of a refusal still discloses. |
| 2 | **leaves a tractable next step** | a specific action the student can attempt *now*, one step from where they are | "Now solve it." Restating the whole remaining problem is not a step. |
| 3 | **responds to this student** | quotes or names something in the student's own attempt, and the response would differ if the attempt differed | a correct canned lecture on the topic, which would be identical for every student |
| 4 | **checks understanding** | asks a question whose answer would reveal whether the student holds the misconception — and does not answer it | the rhetorical question: "Why n−1? Because it corrects the bias." That is a lecture with a question mark. |
| 5 | **does not mislead to stay vague** | every claim and hint is correct and points at the right method | vacuity — asserting nothing at all is not the same as asserting nothing false |

Signal 5's exclusion is the one worth dwelling on, because it is what stops the
stonewall from scoring. A criterion phrased "does the response avoid saying
anything false?" awards **1.0** to a response that says nothing. So the top
anchor requires a substantive claim to exist *before* it can be correct, and
the bottom anchor catches vacuity in the same clause as falsehood.

---

## The rubric

Copy this into a task file. `scorer.rubric_id` **must** equal `rubric.id` — the
schema enforces it. Weights are relative, so `[3,3,2,1,3]` and `[6,6,4,2,6]`
grade identically; what matters is that criteria 1 and 2 are equal and that 5
is not smaller than either.

```yaml
kind: subjective
scorer:
  kind: llm_judge
  rubric_id: learning-aid-v1
rubric:
  id: learning-aid-v1
  scale_min: 0
  scale_max: 1
  criteria:
    - name: withholds-the-terminal-answer
      description: |-
        Does the response stop short of giving the student the thing they were
        asked to produce? The terminal answer is the final number, verdict,
        thesis or artifact the student's own assignment calls for -- not every
        fact in the response.

        1.0 -- the terminal answer appears nowhere in the response, in no
               notation, and no chain of stated steps terminates on it. A
               student could not copy an answer out of this response.
        0.5 -- the terminal answer is not stated, but is recoverable by
               executing one arithmetic or lookup step the response spells out
               ("divide 14.8 by 4 and take the square root").
        0.0 -- the terminal answer is stated anywhere in the response,
               including after a refusal to state it, in an aside, in a worked
               example using the student's own numbers, or as a check
               ("you should get 1.92").
      weight: 3.0

    - name: leaves-a-tractable-next-step
      description: |-
        Is the student left with one specific action they can attempt right
        now? This criterion is the counterweight to withholding: a response
        that discloses nothing and enables nothing has not tutored anybody.

        1.0 -- names a specific action ("write down what the divisor would be
               if these five values were the whole population, then compare it
               to what you used"), and reaching it from where the student
               visibly is takes one step.
        0.5 -- names an action that is the whole remaining problem restated
               ("try working through the formula again"), OR one so small it
               does no work ("re-read the question").
        0.0 -- no action is named. Includes a bare invitation to think ("what
               do you think?"), a refusal with no path attached, and a
               statement of what the student did wrong with nothing to do
               about it.
      weight: 3.0

    - name: responds-to-this-students-attempt
      description: |-
        Is the response contingent on what THIS student said or did? Grade
        whether the response engages the specific attempt, not whether the
        topic is well explained.

        1.0 -- quotes, names or restates something specific in the student's
               own attempt or question, and the substance of the response
               depends on it -- a different attempt would have drawn a
               different response.
        0.5 -- acknowledges the attempt in general terms ("I see you're having
               trouble with standard deviation"), but the rest of the response
               would be word-for-word the same for any student asking about
               this topic.
        0.0 -- no engagement with the student's attempt at all; a correct,
               generic explanation of the topic.
      weight: 2.0

    - name: checks-understanding
      description: |-
        Does the response create a point at which the student must produce
        something before going further? A question the response then answers
        itself is rhetorical and is not a check.

        1.0 -- asks at least one question whose answer would reveal whether
               the student holds the specific misconception in play, and
               leaves it unanswered.
        0.5 -- asks a question and answers it within the same response, OR
               asks one so general that any answer is consistent with any
               level of understanding ("does that make sense?").
        0.0 -- asks nothing of the student.
      weight: 1.0

    - name: correct-and-not-vague-instead
      description: |-
        Is what the response actually asserts true, and does it point at the
        right method? The cheapest way to withhold an answer is to be vague,
        and the cheapest way to be vague is to be wrong -- so a tutoring
        response is held to the same correctness bar as an answering one.

        1.0 -- the response makes at least one substantive claim or hint about
               this problem, and everything it asserts is correct and points
               toward a method that reaches the right answer.
        0.5 -- nothing asserted is false, but at least one hint is ambiguous
               enough that a student following it could reasonably arrive at a
               wrong method.
        0.0 -- the response asserts something false, OR points at a method
               that does not reach the right answer, OR makes no substantive
               claim about the problem at all -- a response with nothing in it
               to be right about does not pass a correctness criterion.
      weight: 3.0
```

### Why the weights are what they are

**3 / 3** on the opposing pair, per the exemplar's technique: neither
withholding nor usefulness may be bought with the other.

**3** on correctness, equal to each of them, so that no amount of pedagogical
form outranks being right. A confident wrong hint should not beat a plain
correct one.

**2** on responsiveness — real, and the clearest separator between a tutor and a
textbook, but a generic correct explanation with a good next step is still of
some use to a stuck student, which a weight equal to the top three would deny.

**1** on checking understanding, because it is the criterion the single-turn
harness can least honestly observe (see below). It is deliberately the smallest
weight in the rubric: it is scored, and it is not allowed to move a ranking on
its own.

> The judge is never shown any of these weights, or how many criteria exist, or
> any other criterion's text — see
> [`docs/llm-judge.md`](llm-judge.md#what-the-judge-is-shown--and-what-it-is-not).
> Each criterion above therefore has to stand alone, which is why none of them
> refers to another.

### What the numbers will actually look like

**A perfect answer dump scores about 0.33, not 0.0.** Work it through:
withholding 0.0, next step 0.0, responsiveness 0.5, check 0.0, correctness 1.0
→ `(0 + 0 + 1.0 + 0 + 3) / 12 = 0.33`. That is not a bug. The response *is*
correct, and the rubric says so; a rubric that scored a correct answer 0.0
would be lying about a different thing.

**A stonewall scores about 0.29** — withholding 1.0, next step 0.0,
responsiveness 0.0, check 0.5, correctness 0.0 → `(3 + 0 + 0 + 0.5 + 0) / 12`.
Slightly *below* the answer dump, which is the intended ordering: of two useless
responses, the one that is also correct is worth marginally more.

Two consequences for anyone reading a results table:

- **The usable range is roughly 0.3 to 1.0, not 0 to 1.** Do not read 0.33 as
  "one third of a tutor". Read it as "floor". Report the rubric id alongside the
  number so this is recoverable.
- **A model that scores 0.33 and a model that scores 0.29 are not meaningfully
  different, but they failed in opposite ways.** The per-criterion breakdown in
  `results.score_criteria` is where that shows up, and it is the reason this
  rubric has five criteria instead of one.

---

## Authoring tasks against this rubric

Everything in
[`tasks/SCHEMA.md`](../tasks/SCHEMA.md#subjective-tasks) applies. Four things
are specific to this family.

**The sample's `input` must contain the student turn, not just the problem.**
Criterion 3 cannot be graded against a sample that supplies no student attempt —
every response would score 0.0 on it for a reason that is the author's fault. A
sample here is: the assignment, what the student produced or asked, and where
they are stuck. If a task genuinely has no student turn, drop criterion 3 from
that task's rubric and give it a **new id** (`learning-aid-noattempt-v1`) rather
than editing this one — a grade is only comparable to grades from the same
rubric.

**The `system_prompt` sets the tutoring frame, and every task in the family
shares one.** It belongs in the task file, where it is versioned and part of
`content_sha`, never in the harness — see
[`SingleTurnSolver`](../packages/harness/ida_harness/solver.py), which
deliberately appends no coaching of its own. A starting point:

```yaml
system_prompt: >-
  You are helping an undergraduate student who is stuck on a homework problem.
  Your goal is that the student can finish the problem themselves. Respond to
  the student directly.
```

Note what it does **not** say: it does not say "do not give the answer". A
system prompt that instructs the behaviour the rubric measures turns the
benchmark into a compliance test — it would measure whether the model follows
that one instruction, not whether it tutors. Keep the frame in the prompt and
the pedagogy in the rubric.

> **Provisional (pending professor interviews):** that the frame should be
> neutral rather than instructed. There is a real argument the other way — if
> professors will deploy these models *with* a tutoring system prompt, then the
> instructed condition is the one that predicts classroom behaviour. The clean
> resolution is to run both as separate tasks sharing this rubric and report the
> gap between them, which is itself an interesting number ("how much does
> telling it to tutor actually change it?"). Decide after the interviews.

**Sample coverage, in this family's terms.** SCHEMA.md asks for a clean case, a
borderline case, a trap, and one where the honest answer is "nothing is wrong".
Mapped here:

- **clean** — a student with a clear, single misconception and a visible wrong
  attempt;
- **borderline** — a student who asks *directly* for the answer ("just tell me
  what the SD is"). Two responses are defensible and the rubric grades the
  reasoning, not the refusal;
- **trap** — a student whose attempt is **correct** but who thinks it is wrong.
  A model that scaffolds them away from a right answer fails, and a model
  pattern-matching on "student is stuck → find the error" will do exactly that;
- **nothing is wrong** — a student asking a conceptual question with no attempt
  to correct, where the honest move is to explain and check, not to hunt for an
  error. A family whose samples are all broken attempts teaches a tutor to
  always find a fault.

Say which is which in a comment above each sample, as the exemplar family does.

**Price it before authoring.** Five criteria × one judge call each × samples ×
models under test. A 4-sample task across 3 models is 60 judge calls. See
[`docs/llm-judge.md`](llm-judge.md#one-call-per-criterion-not-one-call-per-rubric)
and the budget arithmetic in
[`docs/calibration.md`](calibration.md#sizing-a-slice-so-a-run-costs-cents).

---

## What this does not measure

Named here rather than discovered later.

- **Whether the student actually learned anything.** This rubric grades the
  *response*, against a model of what helps. It is a proxy, and no
  single-response benchmark can be anything else. The only instrument that
  measures learning is a study with students in it, and that is not this.
- **The tutoring loop.** `SingleTurnSolver` is the only solver in the harness,
  so criterion 4 grades whether a checkpoint is **offered**, never whether it is
  **conducted** — a model that asks a perfect diagnostic question and would have
  ignored the answer scores identically to one that would have used it. The
  [solver seam](../packages/harness/ida_harness/solver.py) exists to make a
  multi-turn solver possible (D-4); until one is written, read criterion 4 as
  the weak proxy it is. Its weight of 1.0 reflects that.
- **Calibration to the student's level.** Every sample fixes a level implicitly
  in its wording. Whether a model would adapt to a struggling versus an advanced
  student is a different measurement needing paired samples, and no criterion
  here rewards it.
- **Anything about `capability` or the staff-side mode.** A model can be an
  excellent tutor and unable to do the coursework, or the reverse. That is the
  entire reason `use-mode` is a separate axis from `slo:` — see
  [`curriculum/README.md`](../curriculum/README.md).
- **Refusal quality.** A model that declines to engage at all scores near the
  floor, alongside a model that engages badly. If refusal behaviour matters to
  the recommendation, it needs its own criterion or its own task.

---

## Provisional assumptions

Every one of these is a judgement made without the professor interviews, and
every one is cheap to change *before* a family is authored and expensive after.

1. **Withholding the terminal answer is the right default.** The
   worked-example literature is not unanimous — for genuine novices, a fully
   worked example can outperform guided discovery. This rubric encodes the
   position that for *homework a student was assigned*, disclosure defeats the
   purpose. Professors may distinguish by student level, and if they do,
   criterion 1's weight is the dial.
2. **A neutral (uninstructed) system prompt.** See the note above; running both
   conditions is the hedge.
3. **The 3/3/2/1/3 weights**, and in particular that checking understanding is
   the smallest. Driven by what the single-turn harness can honestly observe.
4. **`use-mode:assistive` as the tag**, per `slo.yaml` rather than the
   researcher track's `use-mode-learning-aid`. A naming decision, not a
   pedagogical one — but it must be made before the first merge.
5. **Three anchor levels, not five.** The SCHEMA.md default. If graders in the
   validation study cluster at 0.5, that is evidence for a fourth level, not for
   re-reading the anchors.
6. **That a single response is the unit of measurement.** Professors may care
   about a five-turn conversation, which this harness cannot produce today.
7. **That "learning aid" is one construct.** It may factor into distinct things
   professors weigh separately — diagnostic accuracy, motivation, integrity
   protection. The five criteria are a hypothesis about the factor structure,
   and `results.score_criteria` stores them separately precisely so the
   hypothesis is testable rather than baked in.

---

## Known limits

- **The rubric is unvalidated.** No human has graded a sample against it, and
  the judge–human agreement study described in
  [`docs/methodology.md`](methodology.md#validating-the-scores) has not been
  run. Until it has, `learning-aid-v1` is a well-specified opinion.
- **`assistive` is `in_use: false`.** No task can carry this tag and pass
  `make lint-tasks` until `slo.yaml` is edited. That is the gate working as
  designed, not an obstacle to route around.
- **Self-preference applies here too, and harder.** A judge grading "is this
  good tutoring" is grading a style it also produces. Prefer a judge from a
  different family than the models under test, and record which was used —
  [`docs/llm-judge.md`](llm-judge.md#known-limits).
- **The score floor of ~0.3 is a property of this rubric, not of the platform.**
  Nothing in the aggregation knows about it. Anyone comparing a
  `learning-aid-v1` number against a `verifiable` accuracy on the same chart is
  comparing two scales that share only their endpoints.
