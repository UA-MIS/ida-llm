# The intake pipeline: cleaning real course material

`docs/sensitive-material.md` (D-49) turns on one sentence — **cleaning on intake
is the gate**. Cleaned material may live in our database, be used as task
content, be sent to a model provider and appear in public results. Uncleaned
material may do none of those things.

This page is how that gate is implemented and how you use it.

| what | where |
|---|---|
| the cleaning itself | [`packages/core/ida_core/deid.py`](../packages/core/ida_core/deid.py) |
| provenance, the cleaned/uncleaned flag, the seam | [`packages/core/ida_core/intake.py`](../packages/core/ida_core/intake.py) |
| the tool a human runs | [`tools/deid_material.py`](../tools/deid_material.py) |

Both modules live in `ida_core` for the same reason the gold-answer leak check
does: a rule that binds only when somebody remembers to run a CLI binds nowhere.
Everything that can reach material — the API, the runner, the harness — imports
from there.

---

## Cleaning a file (the path that exists today)

There is **no automated ingest endpoint yet**. Today intake is a person with an
export, so the tool is the front door:

```bash
tools/deid_material.py raw.txt \
  --reference "MIS 200 Fall 2024, midterm item 12" \
  --roster ~/private/roster.txt \
  -o cleaned/item12
```

That writes two files:

- `cleaned/item12.txt` — the cleaned text;
- `cleaned/item12.provenance.json` — the reference, the **SHA-256 of the raw
  source**, and the cleaning report. Never the content, cleaned or raw.

and prints counts of what was removed. It never prints the material — not the
input, not a diff, not an example of what was taken. A terminal is scrollback and
a CI job is a public log.

To check a file without writing anything (this is the form for a hook or a CI
job — exit 1 means identifiers are present):

```bash
tools/deid_material.py suspect.txt --check
```

> **The roster is PII.** It is a list of the people in a course. Keep it outside
> the repo, pass it by path, never commit it. `Roster.__repr__` is redacted so it
> cannot leak through a traceback, and neither the tool nor the library ever
> echoes it.

---

## Cleaning in code

```python
from ida_core.deid import Roster
from ida_core.intake import IntakePipeline, require_cleaned

pipeline = IntakePipeline(roster=Roster(names))
material = pipeline.ingest_text(reference="MIS 200 F24 midterm item 12", text=raw)

material.text                    # safe: DB, task content, model calls, public results
material.provenance.sha256       # the pointer back to the source
material.to_task_sample("item-12")  # a TaskSample carrying the § 4 provenance pointer
```

And at any point where material could be stored, prompted or published:

```python
cleaned = require_cleaned(candidate, purpose="a model call")
```

`require_cleaned` raises `UncleanedMaterialError` for a `str`, a `dict`, a
`RawMaterial` — anything that did not come through the pipeline. That is the
"material that arrived without cleaning is not usable" rule: **there is no flag
to forget to set, because the absence of the `CleanedMaterial` type is the flag.**

---

## What it catches, and what it honestly does not

**Catches**, by pattern: email addresses, US phone numbers, US SSNs, labelled
identifier fields (`Student ID:`, `CWID:`, `NetID:`), bare 8–10 digit identifier
runs, `@handle` usernames, labelled submission timestamps, honorific-led names
(`Dr. Achterberg`), labelled name fields — and, **with a roster**, every roster
name anywhere in the text including the `Last, First` export form.

**Does not catch:**

- **Re-identification by content.** `tasks/SCHEMA.md` § 1 says it plainly: the
  standard is higher than deleting a name, because a short answer is often
  re-identifiable from what it says. *"The student who missed the midterm for the
  away game in Baton Rouge"* survives this pipeline intact. **A human reads
  cleaned material before it is published.** No regex closes this.
- **Free-text names with no roster.** Without one, a name mid-sentence is just a
  capitalised word. Supply a roster or accept that names remain — the report
  records which happened, every time.
- **Non-US phone formats and identifier schemes this code has never seen.** Use
  `DeidConfig.extra_patterns` rather than assuming coverage.
- **Anything outside the text**: filenames, PDF author metadata, an image of a
  signature, a spreadsheet's second sheet.

Every one of these is written into `DeidReport.residual_risk` on **every call**,
so a stored report also stores the reasons it is not a clean bill of health. A
green `--check` means "these detectors find nothing", never "this is safe".

**It over-redacts on purpose.** A bare eight-digit number goes whether it was a
CWID or a count. For a privacy gate that is the correct direction to be wrong in.
The negative fixtures pin how far it goes: a year, a decimal, a section number
and a point allocation all survive untouched. Pass `--keep-bare-numeric-ids` when
the material is numeric *data* rather than a roster export.

---

## Two properties worth knowing

**Idempotency is structural.** Cleaning already-clean material is a no-op, and
not by luck: every span already matching `[REDACTED:...]` is marked protected
before detection runs, and any detection overlapping a protected span is
discarded. So a placeholder is inert input whatever label precedes it, and the
second pass reports *zero detections* rather than merely producing the same
bytes. `IntakePipeline.ingest` on already-clean material returns the same object.

**Re-cleaning is not skipped.** `ingest` re-runs the detectors even on
`CleanedMaterial`, and returns a new object if a wider roster or newer ruleset
finds more — with the **original provenance preserved**, because the pointer must
keep resolving to the source. "Already cleaned" must not mean "exempt from a
better detector": the rows most in need of re-cleaning are the ones already
marked clean. That is what `DEID_RULESET_VERSION` and `INTAKE_PIPELINE_VERSION`
are for — two numbers, because "re-run the detectors" and "re-ingest the
material" are different remediations.

---

## The repo is stricter than the database

Do not read *cleaned* as *committable*.

| | may hold cleaned real material? |
|---|---|
| our **database** | **yes** — that is what D-49 decided |
| **`tasks/**.yaml`** | **no** — not even de-identified |

`tasks/SCHEMA.md` § "No real student work" is the tighter rule and it is
unchanged by this pipeline: a short answer is re-identifiable from its content,
so cleaning does not make it redistributable, and cleaning does not launder
copyright either. For repo-committed task content the answer is still a
**synthetic stand-in plus a provenance pointer** — which is what
`tasks/conceptual-grading/` already does.

`CleanedMaterial.to_task_sample()` therefore builds an **in-memory** sample for
database-held material. `tools/deid_material.py` refuses to write under `tasks/`
at all, checked on the resolved path, with no override flag — because that is
exactly the distinction a tired person collapses at 2am.

---

## Still open

- **No automated ingest endpoint.** The module and the gate exist; the
  `POST /materials` handler that would call them does not. When it is built it
  calls `IntakePipeline.ingest_text` and stores a `CleanedMaterial`; nothing in
  these modules changes.
- **No database table for cleaned material.** `CleanedMaterial` is a contract,
  not a row. Persisting it needs a table and an Alembic migration.
- **Exam question text remains a question for the human**, not something cleaning
  solves — see the residual question at the end of
  [`sensitive-material.md`](sensitive-material.md). Gold answers are already
  redacted behind the `author` role; a real exam *question* published in a task
  spec retires that exam. The safe default stays: synthetic stand-ins.
