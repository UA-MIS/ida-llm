# `calibration/` — published numbers we check our harness against

Each file here is a **calibration slice**: a small set of task ids that already
live in [`tasks/`](../tasks/), paired with a score somebody else published for a
named model, plus the citation for that score.
[`ida_harness.calibration`](../packages/harness/ida_harness/calibration.py) runs
the tasks through the ordinary harness and compares the two numbers.

The question is **"is our plumbing skewing results?"** — not "how good is this
model". If our measured score and the published score agree, the path from task
YAML through prompt assembly, sampling params, normalisation, scorer and
aggregation is not bending anything. If they disagree by more than the slice's
tolerance, every score this platform publishes is suspect until the cause is
found.

> This is **not** LLM-judge calibration. That lives in
> [`docs/llm-judge.md`](../docs/llm-judge.md) and
> `ida_runner.sweeps.run_judge_calibration`, and asks whether a judge model
> agrees with a human. The two share a word and nothing else.

Full usage, the mock/CI path and the cost arithmetic for a real run:
[`docs/calibration.md`](../docs/calibration.md).

## ⚠ What ships here is a TEMPLATE, and its number is a placeholder

`gsm8k-slice.yaml` contains **no real published number and no real citation**.
Its `published_source` is a `TODO-PLACEHOLDER(...)` marker — the same convention
`models.yaml` uses for values that are authored but not yet real — and until it
is replaced the file means nothing.

Fabricating a plausible-looking benchmark figure and a plausible-looking URL
would have made the directory *look* finished while making the platform's
central claim — that it does not publish numbers it cannot support — false in
its own repository. So the file is shipped visibly unfinished instead.

The loader and the runner enforce this rather than trusting a comment:

| | behaviour |
|---|---|
| `load_calibration_slice` | **accepts** a `TODO-PLACEHOLDER` citation, so a draft slice can be written and `--dry-run` |
| `load_calibration_slice` | **rejects** an empty `published_source`, a missing `published_retrieved`, or a `published_source` that is neither a URL nor a placeholder marker |
| `run_calibration` | **refuses** a placeholder reference unless `allow_placeholder=True` |
| `run_calibration` with `--allow-placeholder` | runs, reports `verdict=placeholder`, and the outcome **can never be `within_tolerance`** — so CI cannot go green on a stub |

## Filling one in

Two things are needed, and the second is the harder one.

**1. A number and a citation you actually retrieved.** Open the paper, model
card or leaderboard row, read the score, normalise it to 0..1 (`82.4%` →
`0.824`), and record the URL *and* the date you read it. The date is required
separately from the URL because leaderboards are edited in place: a delta that
appears six months later should be attributable to a moved goalpost rather than
blamed on the harness.

**2. Local tasks that measure the same thing the benchmark measures.** This is
where the shipped template is deliberately, visibly wrong: its `task_ids` point
at two rungs of the undergraduate-statistics `quantitative-quiz` ladder, which
are *not* GSM8K items. They are there so the ids resolve and the machinery runs
end to end — nothing more.

Benchmark items **may not be copied into this repository**
([`tasks/SCHEMA.md` → Dataset hygiene](../tasks/SCHEMA.md#dataset-hygiene)):
`tasks/` is committed publicly and served by an unauthenticated API, so
republishing a benchmark's questions here is republication. A slice is a list of
**ids**, never content. That leaves two honest routes:

- author task files whose items are of the same *kind* as the benchmark's (the
  idea of a grade-school multi-step arithmetic word problem is not anyone's
  property; a particular dataset's wording is), or
- point `task_ids` at a locally generated set held outside the repo and pass
  `--tasks-dir` at that directory, so the items never enter version control.

Either way, say which one you did in the reference's `description`. A slice
whose provenance is unstated is the same problem as a score whose source is
unstated.

## Choosing `tolerance`

From the slice size, before you see the result — never from what makes the run
pass. The sampling error of a small slice dominates everything else: over 12
samples, a proportion near 0.8 has a standard error of about 0.115, so a
tolerance of 0.02 fails on noise alone and a tolerance of 0.4 cannot detect a
broken scorer. Twelve samples is a smoke test of the machinery. A slice you
would actually defend as calibration needs a few hundred, which is a budget
question — see the cost arithmetic in
[`docs/calibration.md`](../docs/calibration.md).

Write the reasoning in `description`. A tolerance nobody can explain is a
tolerance somebody tuned.
