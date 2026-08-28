# Sensitive course material: how it is cleaned, stored and used

**Status: ratified (D-49).** This is the storage and handling rule for real
MIS 200 course material. It replaces an earlier, stricter draft that kept all
real material out of the system entirely; the human ratified a revision, and the
gate is now **cleaning on intake**, not exclusion.

It is written from what this system *actually does today*, verified against
`origin/main` and the running cluster. Where a control does not exist yet, it is
named as a gap rather than assumed.

---

## The rule in one paragraph

We have permission to take real course material into our own database. Real
material is **de-identified and sanitised at the point of intake**; once cleaned
it may live in our database, pass through model calls, and appear in public
results. Cleaning is the gate. The benchmark is *meant* to be public, so the
results view stays open — but **triggering a run spends real money**, and that is
the thing that gets locked.

---

## What the system actually does

**1. The results view is public, and that is intended.**

`ida-llm.capstone.uamishub.com` carries no auth middleware and answers
anonymously with run detail and transcripts. That is **not** a defect — a public
benchmark that nobody can read is not a benchmark. **Do not gate the results UI.**

**2. Gold answers are already protected.**

`GET /tasks/{id}` redacts every `target` by default (A10). `?include_targets=true`
requires the `author` role, and the anonymous principal deliberately does *not*
hold it — so the answer key is already fail-shut, not fail-open. Publishing every
answer key would be both an integrity risk and a training-contamination risk.

**3. Run execution is *not* protected — and it spends money.**

`POST /runs` (`enqueue_runs`) enqueues benchmark runs against real providers.
`services/api/ida_api/auth.py` is an explicit placeholder (D-5, `auth_mode="disabled"`),
and its anonymous principal holds **`reader` and `runner`** — `runner` being, in
its own words, *"enqueue runs (spends money)"*.

Today that is contained by accident of routing rather than by design: the API has
**no public Ingress** (only `ida-llm-frontend` and `ida-llm-agile` are routed),
and the frontend proxies just three read-only routes. So nothing on the internet
can currently trigger a run. **That containment disappears the moment the API is
routed publicly or a "run this" button is added** — which is exactly what the
results work is heading toward.

**4. Everything a model sees is archived and published.**

`ida_core.artifacts` treats the object-store layout as a contract: every sample
transcript, judge transcript and eval log is written to
`s3://<bucket>/runs/<run_id>/…`, and that is what the public UI reads. There is
no "run without keeping the transcript" mode, by design.

**→ Whatever goes into a model call becomes public. That is why cleaning happens
on intake, not later.**

---

## The decision

### 1. Where material lives

**In our own database**, de-identified on intake. We have permission to hold it.

The intake pipeline is a real piece of work, not a promise. The **cleaning and
the gate now exist** — `ida_core.deid` (the redaction) and `ida_core.intake`
(provenance, the cleaned/uncleaned flag, `require_cleaned`), driven by
`tools/deid_material.py`; see [`intake-pipeline.md`](intake-pipeline.md). What
does *not* exist yet is an automated ingest endpoint and a table to persist
cleaned material into: intake today is a person running that tool.

Material that has not been through it is **not** yet cleaned material and must
not be used as task content or sent to a model. That is enforced by type rather
than by a flag somebody has to remember to set — `require_cleaned` refuses a
`str`, a `dict` or a `RawMaterial`, so material that skipped intake cannot reach
a store, a prompt or a publish path by omission.

### 2. Cleaning on intake is the gate

At intake, strip anything that identifies a person: student names, IDs, emails,
usernames, submission timestamps tied to an individual, and free-text that
re-identifies by content. Instructor-identifying material is treated the same
way unless the instructor has agreed to be named.

FERPA is the floor here and `tasks/SCHEMA.md` § 1 states it plainly: the
de-identification standard is **higher than deleting a name**, because
short-answer text is often re-identifiable from its content. If a passage cannot
be cleaned without destroying it, use a synthetic stand-in (§4).

**Cleaned material may:** live in our database, be used as task content, be sent
to model providers, and appear in public results.
**Uncleaned material may not** do any of those things.

### 3. What may enter the git repository

The database and the repo are different questions. The repo is the stricter one:
`tasks/SCHEMA.md` § Dataset hygiene is written on the assumption that everything
in `tasks/` is public, and that remains the standing rule.

**May:** official published curriculum material (the BSCBA curriculum map is
public program documentation); the SLO list derived from it; synthetic task
content; cleaned material that is genuinely safe to redistribute.
**May not:** copyrighted textbook or question-bank content — cleaning does not
launder copyright; anything not yet through the intake pipeline.

### 4. Provenance pointers and synthetic stand-ins

Still good practice, and still required for anything we do not clean or cannot
share:

- author the task body as a **synthetic stand-in** imitating the shape of the real
  item — this is what `tasks/conceptual-grading/` already does;
- carry the provenance sentence `tasks/SCHEMA.md` § 3 requires —
  `CleanedMaterial.provenance_sentence()` generates it;
- name the source in per-sample `metadata` by **reference and SHA-256**, never by
  content — `CleanedMaterial.provenance_metadata()` produces exactly that shape,
  and refuses to let a caller overwrite it (a forged pointer reads as verified,
  which is worse than no pointer).

The hash lets someone with authorised access confirm which item a task derives
from without the repo carrying the item.

### 5. Cloud API vs local inference

**Cleaned material may go to cloud providers.** The earlier blanket prohibition
is lifted.

Local inference (campus "Sparks" vLLM) remains **deferred and unreachable** —
`infra/inference/README.md`; the tenant egress policy grants `:443` only, vLLM
defaults to `:8000`, and the NetworkPolicy lives in `platform-infra`. It is now a
*capability we want*, not a *precondition we are blocked on*: it would let us
handle material we choose not to clean, or cannot clean well enough.

### 6. The control that actually matters: gate run execution

**Require auth to trigger a run on prod.** Not to view results — to spend money.

This is our application's work, not the platform's: `auth.py` already defines the
`runner` role for exactly this, and every protected route already depends on
`current_principal`, so it is an edit to that file plus a config flag rather than
a sweep through the handlers. The specific change is to stop granting `runner` to
the anonymous principal and to validate a real token.

It pairs with the cost interlocks already in place: nightly sweeps suspended in
all environments (D-43), and `test_only_the_mock_is_enabled` keeping hosted
models off by deliberate act.

---

## Known gaps

| gap | consequence | owner |
|---|---|---|
| **Run execution is unauthenticated** — anonymous principal holds `runner` | anyone who can reach the API can spend real tokens; contained today only because the API has no public route | this repo (tracked as its own story) |
| Intake cleaning **module** built; no automated **ingest endpoint** or table to persist cleaned material | intake runs only when a human runs `tools/deid_material.py`; nothing ingests on its own, and cleaned material has no row to live in | this repo |
| De-identification is pattern-based: it cannot detect **re-identification by content** | a short answer can identify its author through what it says; cleaned ≠ anonymous, so a human must read cleaned material before it is published | standing limit, restated in every `DeidReport` |
| Personal names in free text need a **roster** to be caught reliably | material cleaned without one keeps mid-sentence names; re-ingesting with a roster finds them | whoever runs intake |
| Local inference unreachable (egress netpol) | no option for material we choose not to clean | `platform-infra` |
| `tasks/SCHEMA.md` says the repo is public; it is currently **private** | rules are correct either way, but the stated premise is wrong today | this repo (docs) |

### ⚠️ Residual question for the human

Cleaning removes **student** PII. It does not address a separate question:
**exam questions and answer keys becoming publicly visible.**

Gold answers are already redacted behind the `author` role (A10), so the answer
key is covered. What is *not* covered is the **question text** of a real exam
appearing in a public task spec — which matters because professors reuse exams,
and a publicly readable question retires it.

This is a call for the human and the instructor, not something cleaning solves.
The safe default until they decide: **use synthetic stand-ins for exam items**
(§4), which costs about ten minutes per task and keeps the family redistributable.

**Note also:** gating run execution does **not** gate viewing. Results stay public
by design (§ "What the system actually does", 1).
