# What makes this benchmark fair

A benchmark is a comparison, and a comparison is only worth as much as the
things it holds constant. This page states what this harness holds constant,
what it deliberately refuses to do, where it is honestly not fair yet, and how
to tell "we did not measure this" apart from "this model scored zero".

Read with: [`docs/methodology.md`](methodology.md) (what is measured) ·
[`docs/llm-judge.md`](llm-judge.md) (subjective grading) ·
[`tasks/SCHEMA.md`](../tasks/SCHEMA.md) (authoring)

---

## The one-paragraph version

Fairness here is not a policy document; it is a set of properties the code
already has, and a shorter list of ones it does not. Every model sees the same
prompt, assembled by a solver that adds nothing of its own. Gold answers are
redacted at the API and lint-guarded out of published metadata. Rubric criteria
are graded one call each, so criterion order cannot move a score, and the
candidate's text is fenced with a content-derived delimiter so it cannot address
the judge. Nothing is ever clamped, defaulted or rounded into a grade: **every
failure degrades to `None` with an honest error, never to `0.0`.** The places
this is *not* yet fair — self-preference in the judge, a single judge opinion,
models that cannot be pinned to the same temperature — are enumerated at the
bottom rather than left to be discovered in a results table.

---

## 1. Consistent prompting

**The harness adds nothing to a prompt.**
[`SingleTurnSolver`](../packages/harness/ida_harness/solver.py) sends one system
message (if the task has one) and one user message. It deliberately does *not*
append "answer with only the number"-style coaching:

> any instruction that shapes the answer belongs in the task's `system_prompt`,
> where it is visible, versioned and part of the git SHA recorded on the result
> (D-13).

That is the whole rule, and the reason for it is comparability over time. A
nudge hardcoded in the solver would not be recorded on any result, so the day
somebody edits it, every historical comparison changes silently and nothing in
the data says so. A nudge in the task file changes `content_sha`, and old
results stop claiming to be comparable.

**Every task in a family shares one `system_prompt`,** so that differences
between rungs of a difficulty ladder are differences in difficulty and not in
phrasing.

**The same task text reaches every model.** There is no per-model prompt
adaptation anywhere in the harness — `serving_stack` selects a *client* (a wire
format), never a prompt. Adding Anthropic and OpenAI's reasoning dialect was a
`models.yaml` edit plus a client subclass; no code names a model.

> **Honest counterpart:** identical prompts are not identical *conditions*. A
> prompt tuned to one model's idiom advantages that model, and every task in
> this repo was written by humans who use some models more than others. This is
> unmeasured. The mitigation available today is that tasks are reviewed by
> people who did not author them; the mitigation that would actually settle it
> is a prompt-sensitivity sweep, which the [solver seam](../packages/harness/ida_harness/solver.py)
> exists to make possible and which nobody has written.

---

## 2. No answer leakage

Four independent guards, because each catches something the others do not.

**Gold answers are redacted by the API (A10).** `GET /tasks/{id}` strips every
`target` unless the caller holds the `author` role, and the response carries an
explicit `targets_redacted: true` so a consumer never mistakes a redacted view
for a task that has no answer key. Publishing the key is both an integrity risk
(anyone can tune against it) and a contamination risk (a scraped key reaches a
future training corpus).

**`metadata` is published; targets are not — and a lint enforces the gap.**
`sample.metadata` is returned verbatim to everyone, unauthenticated, so a
derivation left in `metadata` hands out exactly what the redaction protects.
`make lint-tasks` and the `task-schema` CI job reject a verifiable sample whose
target is recoverable from its own metadata — the exact string, and for numeric
targets the same value in another format (`7.50` for `7.5`), including nested
structures. Derivations go in **YAML comments**, which are not parsed, are not
part of `content_sha`, and never leave the repository.

> ⚠ **Be precise about what that buys.** It is a **tripwire for the mechanical
> mistake, not proof that a key is secret.** It cannot see a derivation that
> yields the answer without stating it (`{working: "sum=70, n=5"}` beside a
> target of `14`), the answer written in words, a hint
> (`{note: "answer is negative"}`), or the answer sitting in a *different*
> sample's metadata or in `description`. Treating a green lint as proof of
> containment is the mistake the guard invites.

**The target must not be liftable from the prompt.** An item whose answer can be
produced by copying the last number of the prompt measures nothing and passes.
This bites hardest on invariance items — "the SD was 6.4; after shifting every
value by 5, what is the SD?" — and the fix is to require at least one step
(`l2-spread-key.yaml` gives the *variance* and asks for the standard deviation).
Note the rule is **liftability, not string presence**: a mode is by definition a
member of its data set and a median often is, and those items are sound.

**No benchmark items are copied into this repository.**
[Dataset hygiene](../tasks/SCHEMA.md#dataset-hygiene) forbids it, which is why a
calibration slice is a list of local task **ids** rather than a copy of the
public benchmark. That is a harder way to calibrate and it is the only one that
does not import contamination.

**For subjective tasks there is no key to leak** — but the judge is a second
leakage surface, and what it is *not* shown is covered next.

---

## 3. Order independence

**One judge call per criterion.** No call ever sees two criteria, so reordering
a rubric cannot move a score. A single-call judge grading four criteria in one
response is sensitive to their order — the first anchors the rest — and that
sensitivity would be invisible in the number. It costs N calls instead of 1 and
this is what it buys.

**The judge is withheld everything that could reintroduce an order effect
through the back door:** the criterion's weight, its position, how many criteria
exist, every other criterion's text, and every verdict already reached.
[`build_criterion_messages`](../packages/harness/ida_harness/judge.py) is a pure
function of its arguments — no clock, no randomness, no global state — so a
judgment is reproducible from the archived transcript alone.

**Weight is withheld specifically because it changes grading.** A judge told a
criterion is "worth 3" grades it more harshly. Weight is aggregation metadata
and belongs to the arithmetic, applied afterwards.

**There is no position bias to correct within a criterion**, because this judge
grades one response absolutely against anchors rather than comparing two. If
pairwise judging is ever added, order-swapping becomes mandatory and this
section stops being true.

**Sample order does not affect scoring.** Each sample is scored independently
against its own target or rubric; no scorer carries state between samples.

---

## 4. The judge cannot be talked into a grade

A completion is untrusted text that is about to be shown to a model with
scoring authority. Three layers, and each closes a hole the others leave open.

**The prompt-side fence is content-derived.** A *fixed* marker (`<<<RESPONSE`)
is forgeable: a response that emits the closing marker escapes its own quoting
and starts issuing instructions. The fence is
`===IDA-<sha256(completion)[:16]>===`, which the fenced content cannot contain,
and the prompt states that everything inside it is data and that an instruction
found there is part of the text being graded. Deriving it from a hash rather
than a nonce keeps the prompt a **deterministic function of its inputs**.

**Parsing is lenient about formatting and strict about meaning.** A bare object,
a fenced object, or a "Sure, here you go:" preamble all parse — a correct
judgment should not be thrown away over packaging. But no number is ever scraped
out of prose: *"I'd say 0.8, though 0.4 is arguable"* contains two numbers and no
judgment we are entitled to read, and a regex would confidently pick one.

**Out-of-range scores are refused, never clamped.** A `1.5` on a 0–1 rubric is a
misunderstanding, and clamping it to `1.0` records a top mark produced by one
with nothing in the row to say so. `{"score": true}` is refused too — Python's
`isinstance(True, int)` is `True`, so a boolean would otherwise land as a
confident 1.0.

**A quoted object is not a verdict.** The attack that matters does not need the
judge to be fooled — it needs the judge to behave *correctly*: to refuse an
injection attempt in the text it is grading, and to **quote** it while
explaining. A naive parse then records the attacker's number as a successful
grade. Three refusals close it, the last of which prefers **proof over
ambiguity**: when one object can be *proved* a quotation (it appears verbatim in
the graded completion), the other is accepted, so the two-fence shape recovers
the judge's real verdict instead of discarding it. Whatever happens, the
attacker's number is never what gets recorded.

---

## 5. Determinism, where it is available

**Benchmark defaults, not provider defaults.** `SamplingParams` defaults to
`temperature: 0.0`, `top_p: 1.0`, because we want near-deterministic output so
that re-running a task reproduces a number. `seed` is passed through where the
endpoint supports it (vLLM does; most hosted APIs do not).

**The cache key covers everything that could change the answer and nothing that
cannot:**

```
sha256(model_id | serving_stack | quantization | revision | sampling params |
       task_id | task_content_sha | sample_id | input | repeat_index)
```

Note `task_content_sha` and **not** the repo-wide git SHA: keying on the repo
would invalidate every entry on every commit, including a README typo. Note also
that the *scorer* config is deliberately absent — changing a tolerance must not
force a re-query, which is exactly the case the cache exists for.

**A cache hit is honest about being one.** `cached=True`, `cost_usd=0`,
`latency_ms=0` — reporting the original call's figures would bill tokens that
were never purchased and show a latency that was never measured. The archived
transcript still contains the real prompt, because a result whose evidence is an
empty message list is not citable.

**The completion cache caches answers, not grades.** A cache hit still pays the
judge in full. A grade is a function of the judge as well as the completion, and
serving a stale grade after the judge changed would be exactly the silent
incomparability `judge_serving_config` exists to prevent.

### ⚠ Where determinism is not available, and it is not our fault

Some models **cannot** be pinned, and this is a property of the model:

- **Reasoning models accept only `temperature`/`top_p` of 1.0**; a non-default
  value is a 400. So `luna` (`gpt-5.6-luna`) cannot be greedy-decoded, its runs
  are not bit-reproducible, and — stated plainly in `models.yaml` —
  **"comparing a Luna number to a temperature-0.0 number is comparing two
  different things."** `preflight` warns if anyone edits it back to 0.0.
- **Reasoning traces are not replayable at all**, so two runs of the same slice
  differ. A calibration `tolerance` therefore has to absorb run-to-run variance
  as well as sampling error, and a single run landing just outside tolerance is
  a prompt to re-run and look, not a verdict.
- **Anthropic's current top models likewise reject a non-default temperature.**

The honest position: this platform records the sampling params it actually used
on every result, so a reader can *see* that two numbers came from different
decoding regimes. It does not, and cannot, make them comparable. Any published
comparison spanning a greedy model and a forced-`temperature: 1.0` model must
say so.

---

## 6. Not measured is not zero

**The single most important fairness property in this codebase**, and the one
most likely to be undone by a well-meaning simplification. A zero is a claim
about a model. A blank is a claim about the run. The two must never be confused,
and every place below chose the blank.

| situation | what is recorded | never |
|---|---|---|
| model endpoint failed | `error` set, `score=None`, sample kept in the log | dropped (a missing sample biases the mean upward) or `0.0` |
| scorer could not parse a malformed *task* | `error` on that sample, siblings unaffected | discarding the paid-for completions of its siblings |
| subjective task, no judge configured | `scorable=false`, `score=null`, transcripts archived | `0.0` — which would look like a failing model |
| judge endpoint down / reply unparseable | `error`, `score=None`, judge tokens already spent still recorded | a fabricated grade |
| judge score outside the rubric's scale | `JudgeResponseError` naming the scale | clamped into range |
| empty rubric, or `scale_min == scale_max` | `JudgeConfigurationError`, **zero calls made** | `0.0` — a weighted mean over nothing is undefined |
| criterion 2 of 5 fails | the whole sample stops; earlier judgments kept in the transcript | a mean over the criteria that happened to succeed — a silently different number |
| run where **every** sample errored | `status=failed`, `mean_score=None` | `succeeded`, or a mean of `0.0` |
| run where **some** samples errored | `status=partial`, mean over survivors, `error_count` alongside | counting the errors as zeros — our outage is not the model's failure |
| calibration run with any errors | `verdict=errors_in_run`, `within_tolerance=False` whatever the arithmetic says | a delta that happens to look good |
| calibration `EvalLog` status `failed` | `measured_score=None` | `0.0` |
| reasoning model spent its whole budget thinking and returned nothing | `OpenAIReasoningClient` refuses an empty completion that stopped on `length` — a loud failure | an empty string scored `0.0`, a fabricated measurement |
| transcript archival failed | result kept, `archive_error` set | discarding a bought-and-scored result because object storage blinked |
| both archival paths failed | both errors joined | the second silently erasing the first |

Two derived rules follow, and they are what a consumer of this data needs:

**`error_count` always travels with a mean.** `scored_count < sample_count` is
ambiguous between "some calls failed" and "this task is not scorable yet", and
the recommendation engine needs the distinction so that an outage is not
recorded as *no data for this model*.

**Spend incurred before a failure is still reported.** The calls happened.
Reporting zero would understate what benchmarking costs, in the direction that
flatters us.

---

## 7. Trust-tells: reading a number at the right confidence

Nothing here is a computed "confidence score" — this platform does not have one
and should not invent one. These are the flags the data already carries, sorted
into the tiers a reader should apply. **Every one is a field, not a judgement.**

| tier | means | tells that put a number here |
|---|---|---|
| **A — citable** | a measurement with intact evidence | `status=succeeded` · `error_count=0` · `score` non-null · `transcript_uri` set · `archive_error` null · verifiable scorer, or a judge grade with `protocol_version` recorded |
| **B — citable with the caveat attached** | real, but something about it is not comparable to its neighbours | `status=partial` (quote `scored_count/sample_count`) · `cached=true` (not re-measured this run) · judge from the same family as the candidate (self-preference) · sampling params differing from the models being compared against · `judge_attempts > 1` |
| **C — not a result** | do not put it on a chart | `score=null` for any reason · `scorable=false` · `status=failed` · `measured_score=None` · a calibration outcome marked `CROSS-MODEL` or carrying a `TODO-PLACEHOLDER` citation · anything from a `--dry-run` |

Three specific tells worth naming, because each is a trap:

**⚠ `scorable` does not mean "this still needs grading".** It records whether a
judge was *configured when the sample ran*. Selecting work with
`scorable IS FALSE AND score_value IS NULL` is wrong in **both** directions at
once — it over-selects samples whose retroactive grading already failed (which
then re-fail and re-bill nightly) and samples with no completion at all, and it
under-selects samples whose *online* grading failed, which carry
`scorable = TRUE` and are therefore never retried. The correct row-level
predicates are in
[`docs/llm-judge.md`](llm-judge.md#the-row-level-predicate-contract), pinned by
tests against a real table.

**⚠ `judge_serving_config IS NULL` matches nothing, ever.** SQLAlchemy's `JSON`
column stores Python `None` as the JSON literal `'null'`, not SQL `NULL`. Python
and SQL disagree about that row and neither complains. It is the first marker a
reader reaches for and it is a trap.

**⚠ A `--dry-run` regrade still calls the judge and is still billed.** It
answers *"what would this change"*, not *"what would this cost"*. It also does
not increment `judge_attempts`, so it is not a free probe and not a counted one.

**Cost is a trust-tell too.** Candidate spend and judge spend are recorded
separately and never summed, because folding them is unrecoverable: a cheap
model graded by an expensive judge would read as an expensive model forever.

---

## 8. Where this is not fair yet

Named here so that nobody has to find them in a results table.

- **Self-preference.** A model grades its own outputs generously. Prefer a judge
  from a different family than the models under test, or accept that one entry
  carries a known bias — **and record which you chose.** This gets worse, not
  better, for the `assistive` rubric in
  [`docs/learning-aid-spec.md`](learning-aid-spec.md), where the judge is
  grading a conversational style it also produces.
- **One judge, one opinion.** No ensembling, no repeated judgments per
  criterion. `Score.criteria` and `repeat_index` are both shaped to allow it
  later; neither is used.
- **No repeated sampling.** `repeat_index` is always `0` — every score is a
  single draw. For a `temperature: 1.0` model that is a sample of size one from
  a distribution, reported as a point.
- **The judge prompt is English and unlocalised.**
- **No calibration set ships with the repo,** and **the judge–human agreement
  study has not been run.** Every subjective number today is the output of a
  well-specified procedure, which is not the same as a validated one.
- **`max_tokens` is per-entry, and for reasoning models the cap is shared with
  thinking.** Two entries at the same nominal `max_tokens` do not get the same
  amount of visible answer. `luna` sits at 4096 specifically to leave headroom;
  a comparison across entries with different caps is not an equal-compute
  comparison and nothing in the data flags it.
- **The nightly sweeps do not enqueue subjective tasks,** so a "full sweep"
  result set is capability-and-verifiable-heavy by construction. The backlog is
  not stranded — `judge-calibration` grades it retroactively — but a chart built
  from sweep output alone under-represents subjective tasks.
- **The API reports `scorable: false` for subjective tasks even where a judge is
  configured and grading them.** Both call sites ask the judge-free question, so
  a judge-configured deployment shows "not yet scorable" in the UI while the
  results table fills with real scores. A deliberate stopping point — `scorable`
  is a public API field — but a reader comparing the UI against the table will
  see them disagree.
- **Prompt sensitivity is unmeasured.** See §1.
- **Task authorship is not blind.** Items are written by people with model
  preferences, and no protocol currently separates authorship from evaluation
  beyond ordinary review.

---

## The short version, for a reviewer

If you are checking whether a published comparison from this platform is fair,
ask these seven questions. Every one is answerable from the recorded data.

1. Did every model see the **same task at the same `content_sha`**?
2. Are the **sampling params comparable** — and if not (a reasoning model), does
   the write-up say so?
3. Is `error_count` **zero**, and if not, is `scored_count/sample_count` quoted
   next to the mean?
4. Are any of these numbers **means that counted an error as a zero**? (They
   should not be; the code does not do it — check any post-processing that does.)
5. For subjective numbers: **which judge**, from **which family** relative to the
   candidates, at **which `protocol_version`**, under **which rubric id**?
6. Are **candidate and judge cost** still separate?
7. Is anything on the chart actually **tier C** — a blank, a placeholder, a
   cross-model comparison, or a dry run?
