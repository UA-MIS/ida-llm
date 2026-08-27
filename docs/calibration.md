# Calibration slices — is our harness measuring what the field measures?

Run a small slice of a public benchmark through this harness against a model
whose score on that benchmark somebody else has already published, and compare
the two numbers.

Code: [`packages/harness/ida_harness/calibration.py`](../packages/harness/ida_harness/calibration.py)
· slices: [`calibration/`](../calibration/)
· tests: [`packages/harness/tests/test_calibration.py`](../packages/harness/tests/test_calibration.py)

---

## The one-paragraph version

A calibration slice is a list of task ids that already exist under
[`tasks/`](../tasks/), a score published for a named `models.yaml` key, and the
citation for that score. `python -m ida_harness.calibration` runs each task
through the ordinary [`run_task`](../packages/harness/ida_harness/runner.py),
folds the results into **one mean weighted by scored samples**, and compares it
to the published figure. Agreement means the path from task YAML through prompt
assembly, sampling params, normalisation, scorer and aggregation is not bending
anything. Disagreement means every score this platform publishes is suspect
until the cause is found.

It is a **sanity check on the measuring instrument**. Nothing it produces is a
benchmark result about a model, and nothing in `calibration/` should ever be
quoted as one.

## ⚠ This is not judge calibration

| | this module | [`docs/llm-judge.md`](llm-judge.md) → "Calibration" |
|---|---|---|
| asks | does our *harness* reproduce a number the field already knows? | does our *judge model* grade like a human does? |
| runs against | `verifiable` tasks, scored by a program | `subjective` tasks, scored by a second model |
| compares to | a published benchmark score | human ratings of the same samples |
| implemented in | `ida_harness.calibration` | `ida_runner.sweeps.run_judge_calibration` |
| costs | one run of the model under test | judge calls, plus human time |

They share a word and nothing else. Do not wire one into the other; a harness
that "calibrates" by asking a judge whether it agrees with itself measures
nothing at all.

---

## The four rules the module enforces

Each exists because the obvious implementation would produce a confident false
statement.

**1. A run with errors never reports agreement.** A mean over the samples that
happened to survive can land anywhere, including plausibly close to the
published number. `error_count > 0` sets `verdict=errors_in_run` and forces
`within_tolerance=False`, whatever the arithmetic says. An `EvalLog` whose
status is `failed` contributes **no measured score at all** — `measured_score`
is `None`, never `0.0`, because *we measured zero* is a claim about the model
and *we measured nothing* is a claim about the run.

**2. Aggregation is weighted by scored samples, not by task.** A reference
spanning an 8-sample task and a 2-sample task is one 10-sample measurement.
Averaging the two task means instead would quietly give each sample of the
smaller task four times the weight — a different statistic from the one every
published benchmark number reports. Errored and unscorable samples are excluded
from the mean and counted separately, exactly as `EvalLog.mean_score` does
inside one task.

**3. The comparison is never nudged.** `delta = measured - published`;
`within_tolerance` is `abs(delta) <= tolerance`, computed on raw floats.
Rounding happens only in `CalibrationReport.table()`, which is why it cannot
flip a verdict. (Corollary: a tolerance you are sitting *exactly* on can fall
either way by one ULP — `0.75 - 0.80` is `-0.050000000000000044`. Choose a
tolerance you are not balanced on; do not ask for an epsilon.)

**4. A published number with no citation is not evidence.** `published_source`
(a URL) and `published_retrieved` (a date) are required, and a reference missing
either fails validation. A `TODO-PLACEHOLDER` citation loads — so a draft slice
can be written and dry-run — but is refused at run time unless
`--allow-placeholder`, and can never be `within_tolerance`.

And one category error worth naming: a number published for model A compared
against a run of model B is not a weak result, it is a result about neither.
`run_calibration` refuses it unless `--allow-model-mismatch` is passed — which
exists for the real case where `models.yaml` names an entry `luna` and the
benchmark names the same underlying model something else — and every outcome
produced that way is printed `CROSS-MODEL`.

## Exit codes

| code | means |
|---|---|
| `0` | every reference was measured and agreed — or a `--dry-run` plan validated |
| `1` | a reference disagreed, errored, measured nothing, or was a placeholder |
| `2` | the slice is unusable, or the comparison was refused |

`1` and `2` are deliberately different: `1` is a **finding** about the harness,
`2` is a **bug in the slice file**. A CI job has to be able to tell them apart.
An empty outcome list is never `ok`, so a calibration that compared nothing
cannot read as a calibration that passed.

---

## Running it against the mock model — free, deterministic, the CI path

The `mock` entry in [`models.yaml`](../models.yaml) needs no key, no GPU and no
network egress. Two things are worth doing on every branch, and neither costs a
cent.

**The test suite.** `packages/harness/tests/test_calibration.py` stubs
`run_task` entirely, so the aggregation and verdict rules are pinned with no
model of any kind involved:

```bash
.venv/bin/python -m pytest packages/harness/tests/test_calibration.py -q
```

**A dry run of every shipped slice.** This resolves the slice file, checks every
`task_id` against the catalog, checks the model key, and prints the plan —
without calling anything:

```bash
python -m ida_harness.calibration \
  --slice calibration/gsm8k-slice.yaml \
  --model mock \
  --dry-run
```

```
REFERENCE                          MODEL          TASKS SAMPLES  NOTE
---------------------------------------------------------------------
gsm8k/template-do-not-cite         mock               2      12  CROSS-MODEL (published for 'luna'); TODO-PLACEHOLDER citation -- no number to compare against

model=mock DRY RUN -- planned 1 reference(s), 12 sample(s); nothing was measured
  note: dry run: no model was called and nothing was measured
  note: would be REFUSED without an explicit flag -- gsm8k/template-do-not-cite: this number is published for model 'luna', ...
  note: would be REFUSED without an explicit flag -- gsm8k/template-do-not-cite: published_source is still a TODO-PLACEHOLDER ...
```

Both notes are correct and both are the point: the shipped file is a template
whose citation is not filled in (see
[`calibration/README.md`](../calibration/README.md)), and it is written for
`luna`, so pointing it at `mock` is a cross-model comparison.

A dry run **reports** every refusal rather than raising on the first one — an
author fixing a slice wants all of its problems in one pass, and a preview that
died on the model key would never mention the missing citation. It still exits
`0`: the preview did what it was asked to do. (An unresolvable `task_id` is the
one thing still fatal in a dry run — that is not a policy refusal, it is a slice
naming tasks that do not exist, and there is nothing to preview.)

Drop `--dry-run` and the same two problems become a refusal, at no cost — exit
`2`, before any model is called:

```
calibration refused: gsm8k/template-do-not-cite: this number is published for
model 'luna', but the run would use 'mock'. ...
```

To actually *measure* the mock model end to end, write your own slice with
`model_key: mock` and a citation. The mock model's answers are a deterministic
hash and mean nothing about any model — a "calibration" of the mock is a
plumbing smoke test of this module, not a calibration, so pass
`--allow-placeholder`, read the measured number off the table, and do not commit
the result as if it were a published figure.

---

## Running it against `luna` — a real calibration

`luna` is the OpenAI-backed entry in [`models.yaml`](../models.yaml). Everything
in this section is about spending real money carefully.

> ### ⚠ The key is TESTING-ONLY and the budget is a **$25 hard cap**
>
> There is no second tranche. $25 is the whole allowance for every real call
> this project makes, calibration included, so a calibration slice competes for
> budget with the benchmark runs the platform actually exists to produce.
>
> **Real calls happen only in a deployed environment where the key is present —
> never from a dev box.** `OPENAI_API_KEY` is projected from Vault into the
> runner and sweep pods (see [`.devops/README.md`](../.devops/README.md) and
> [`docs/provider-keys.md`](provider-keys.md)); it is not in anyone's shell, and
> it should not be put there. A developer's loop is `--model mock` and
> `--dry-run`. If you find yourself exporting the key locally to "just check
> something", check it against `mock` instead.

### Sizing a slice so a run costs cents

Pricing is authored in `models.yaml`, never in code, as USD per **million**
tokens. For `luna`, `cost.input_usd_per_mtok = 0.20` and
`cost.output_usd_per_mtok = 1.20`. The whole arithmetic is one line:

```
cost_usd = S * (T_in * input_usd_per_mtok + T_out * output_usd_per_mtok) / 1_000_000
```

where `S` is the number of samples in the slice — **summed over every task id in
every reference**, which is exactly the number `--dry-run` prints in the
`SAMPLES` column — and `T_in` / `T_out` are the mean prompt and completion
tokens per sample.

**Worked example: the shipped template's two tasks.**
`quantitative-quiz/l1-descriptive-key` (6 samples) plus
`quantitative-quiz/l2-spread-key` (6 samples) is `S = 12`. These tasks carry a
short system prompt and a one-paragraph item, so `T_in ≈ 200`.

`T_out` is the number to be careful with. `luna` is a **reasoning** model
(`serving_stack: openai_reasoning`), and its reasoning tokens are billed as
output and share the same `max_tokens: 4096` budget as the visible answer. A
one-step statistics item is not hard, but "not hard" still buys several hundred
reasoning tokens, so take `T_out ≈ 1,200` rather than the ~300 a non-reasoning
model would use for the same answer:

| | tokens | rate | cost |
|---|---|---|---|
| input | `12 × 200 = 2,400` | `$0.20 / 1M` | `2,400 / 1e6 × 0.20 = $0.00048` |
| output | `12 × 1,200 = 14,400` | `$1.20 / 1M` | `14,400 / 1e6 × 1.20 = $0.01728` |
| **total** | | | **`$0.0178`** — under two cents |

That is **0.071 % of the $25 cap**. The marginal cost of one more sample is
`(200 × 0.20 + 1,200 × 1.20) / 1e6 = $0.00148`, i.e. **$1.48 per thousand
samples** at this shape.

**The bound you can actually promise.** `T_out` is an estimate, but
`serving.sampling.max_tokens` is a hard ceiling the provider enforces, so the
worst case is exact. With `max_tokens: 4096`, output can cost at most
`12 × 4096 × 1.20 / 1e6 = $0.0590`, and the run cannot exceed **`$0.0595`** —
six cents — however much the model thinks. Quote *that* number when asking for
budget; quote the estimate when planning.

**Rules of thumb.**

- **Cap any single calibration run at 1 % of the budget — $0.25.** At the
  estimated $0.00148 a sample that is ~168 samples; at the *guaranteed* worst
  case of `(200 × 0.20 + 4,096 × 1.20) / 1e6 = $0.00496` a sample it is **50
  samples**. Size against the worst case if you want a number you can commit to
  before the run.
- Twelve samples is a smoke test of the machinery, not a calibration. The
  sampling error of a proportion near 0.8 over 12 items is about **0.115**, so
  the honest `tolerance` for a slice that size is wide enough that it can only
  catch gross plumbing faults. A slice you would defend needs a few hundred
  samples — check the `SAMPLES` column with `--dry-run` and price it before you
  spend it.
- **`luna` is not deterministic.** The GPT-5.6 family accepts only
  `temperature: 1.0` (see the note in `models.yaml`), `seed` is best-effort at
  most, and reasoning traces are not replayable. Two calibration runs of the same
  slice will differ, so `tolerance` has to absorb run-to-run variance as well as
  sampling error — and a single run that lands just outside tolerance is a
  prompt to re-run and look, not a verdict.
- Set `tolerance` from the slice size **before** you see the result. A tolerance
  chosen after the fact is a tolerance somebody tuned.
- Calibrate rarely. This is an instrument check, not a nightly. It is
  deliberately not wired into
  [`ida_runner.sweeps`](../services/runner/ida_runner/sweeps.py), because a
  CronJob that re-buys the same published comparison every night spends the cap
  learning nothing.

### The command

Once a slice carries a real number and a real citation:

```bash
python -m ida_harness.calibration \
  --slice calibration/<your-slice>.yaml \
  --model luna
```

```
REFERENCE                          PUBLISHED  MEASURED    DELTA    TOL  SCORED  ERR  VERDICT
--------------------------------------------------------------------------------------------
gsm8k/<your-slice>                    0.8240    0.7917  -0.0323  0.115  12/12     0  WITHIN_TOLERANCE

model=luna references=1 agreed=1 samples=12 scored=12 errors=0 worst_abs_delta=0.0323 cost=$0.017800 ok=True
```

An `ERR` column that is not `0` means the verdict is `ERRORS_IN_RUN` and the
delta beside it — however good it looks — is not a result.

---

## Slice file format

See [`calibration/README.md`](../calibration/README.md) for how to fill one in,
including the part that is actually hard: **benchmark items may never be copied
into this repository** ([`tasks/SCHEMA.md` →
Dataset hygiene](../tasks/SCHEMA.md#dataset-hygiene)), so a reference is a list
of task **ids**, and making a comparison meaningful means having local tasks
that measure the same kind of thing the benchmark does.

```yaml
version: 1
references:
  - benchmark: gsm8k
    slice_id: twelve-item-smoke
    description: why these tasks, and why this tolerance
    model_key: luna                     # the key the number is published FOR
    published_score: 0.824              # normalised to 0..1; "82.4%" -> 0.824
    published_source: https://…         # a URL you opened
    published_retrieved: 2026-08-27     # the day you read it
    tolerance: 0.115                    # from the slice size, not from the result
    task_ids:
      - quantitative-quiz/l1-descriptive-key
      - quantitative-quiz/l2-spread-key
```

## Known limits

- **Nothing here is persisted.** A calibration report is printed and returned;
  it is not written to Postgres or to object storage, and there is no UI for it.
  The individual runs behind it archive normally if an `artifact_store` is
  passed, and `CalibrationOutcome.run_ids` is how you find them.
- **No sweep, by design.** See the "calibrate rarely" note above.
- **`tolerance` is authored, not derived.** The module does not compute a
  confidence interval from the slice size and check the published number against
  it; it checks a number a human wrote down. That is a smaller claim, and it is
  the one the code actually supports.
