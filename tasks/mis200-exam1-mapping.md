# MIS 200 Exam 1 → benchmark families: what was mapped, and what could not be

This note records how a real MIS 200 Exam 1 was translated into the
`mis200-*` task families, so that a reader of those results knows what the
numbers are anchored to. It is written at the level of concepts and counts.

**It deliberately contains no exam item, option, scenario or answer key**, and
no exam asset is committed anywhere in this repository. Why, in §4.

---

## 1. The instrument

One 32-item paper, 100 points, delivered through the university's LMS.

| shape | items | points each |
|---|---|---|
| Multiple choice, single answer | 18 | 3 |
| Fill-in-the-blank (term supplied from a list) | 6 | 3 |
| True/false | 3 | 3 and 2 |
| Multiple choice, select-all | 1 | 3 |
| Spreadsheet formula, free text | 5 | 4 |

Subject matter, by count of items: information-systems concepts and business
models (13), competitive-strategy frameworks (6), platform and network
economics (5), organisational levels of IS use (3), spreadsheet formula
authoring (5). One item is an ungraded warm-up.

Every non-spreadsheet item is forced-choice or a supplied-term blank. **No item
on the paper requires the student to produce extended reasoning.** That single
fact drives §3.

---

## 2. Two numbering systems that both call themselves "SLO"

The exam ships with an instructor-authored question/outcome matrix. Its
outcome numbers are the **course** learning objectives — a nine-item list
specific to MIS 200, covering topics like "explain how and why information
systems are used in business today" and "perform basic tasks in Excel".

They are **not** the programme outcomes in `curriculum/slo.yaml`, which are the
BScBA-wide SLO1–SLO9 the `slo:` tag is validated against. The two lists are the
same length and both are called SLOs in their own documents, and they do not
mean the same thing.

The collision is not cosmetic. Reading the instructor's numbers as `slo:` tags
would produce, among others:

| instructor's number | means, in the course | would have been filed as | actually is |
|---|---|---|---|
| 8 | Perform basic tasks in Excel | SLO8 Oral Communication | **SLO2** Quantitative Literacy |
| 2 | Describe components and users of IS | SLO2 Quantitative Literacy | **SLO9** General Business Knowledge |
| 3 | How businesses use IS to compete | SLO3 Global Perspective | **SLO9** General Business Knowledge |

The first row is the dangerous one. The five spreadsheet items are the only
items on this paper that measure the outcome MIS 200 is an *assessment point*
for, and a mechanical ingest would have filed all five under Oral
Communication — an outcome `curriculum/slo.yaml` marks
`text_benchmarkable: false` precisely because a text benchmark cannot measure
it. The validator would have caught that particular case, because it refuses a
non-benchmarkable outcome. It would **not** have caught rows two and three:
`slo:SLO3` on an IS-competition item is a valid tag naming the wrong outcome,
and it would have failed silently, which is the failure mode
`curriculum/slo.yaml` was written to prevent.

**Every `slo:` tag in the `mis200-*` families was assigned from the programme
outcome statements directly. The instructor's matrix was used only to confirm
which course topic each item was testing.**

---

## 3. The mapping, and the hole in it

MIS 200's published coverage is SLO1 (Reinforced), SLO2 (Assessment point),
SLO9 (Introduced).

**SLO2 — Quantitative Literacy.** The five spreadsheet items, and only those.
They ask for a formula over a supplied layout, which is the outcome's
"using appropriate software, data sources, and tools" clause. Mapped to
`mis200-spreadsheet-formulas/`.

**SLO9 — General Business Knowledge.** The 26 forced-choice and fill-in items.
Breadth over recall across IS and business concepts, which is what
`curriculum/slo.yaml` says a wide forced-choice family measures well. Mapped to
`mis200-is-concepts/`.

**SLO1 — Problem Solving. Not assessed by this instrument.** Several items wear
a business scenario, but each still asks the student to select the intended
concept from four options. SLO1 names assessing a problem, *choosing* a tool
and *proposing* a solution, and `curriculum/slo.yaml` records it as judged
rather than checked for exactly this reason. A scenario-dressed
single-best-answer item measures recognition of the concept the scenario was
built to illustrate. It does not measure problem solving.

`mis200-is-problem-solving/` therefore takes the course's *subject matter* and
raises it to the level SLO1 names. It is an extension, not an ingest, and the
task file says so in its own header and description.

> **Finding for the department.** MIS 200 is marked R for SLO1, and Exam 1
> does not assess it. That is not a defect — reinforcement need not be examined
> on every instrument — but if a comparison between model scores and cohort
> performance on SLO1 is wanted, this paper cannot supply the cohort half. The
> course's later case or project work is where that instrument would come from.

---

## 4. Why nothing here is copied from the exam

Every item in the `mis200-*` families was written for its file. The concepts
and the distractor *strategy* are the course's; the scenarios, the option
wording and the distractors are not. Three reasons, in order of how much they
cost if ignored.

**The exam is live.** It is a current-term paper in an active course shell.
`tasks/` is committed to a public repository and served by an unauthenticated
API. Publishing its items verbatim would put a live exam and its answer key in
front of the students sitting it. This is the reason that would matter even if
the other two did not exist.

**A copied benchmark stops measuring.** Anything published here is scrapeable
and lands in the next training corpus. An item a model has memorised measures
memorisation. Adapting the item keeps the skill and drops the string, which is
the only version of this benchmark that still means something in two years.

**It is someone's assessment material.** `tasks/SCHEMA.md` §2 already forbids
reproducing another institution's exam, and instructs authors that where an
item must resemble a familiar one, the wording *and* the numbers both change.
That rule was written for textbooks; it applies at least as strongly here.

Provenance is recorded as `synthetic` throughout — the items were authored for
these files — with each family's `description` stating that the skill targets
derive from the exam blueprint. `instructor-authored` would be the wrong value:
it is reserved for material a staff member wrote for this purpose *and agreed
to publish*, and no such agreement covers this paper.

No student work of any kind was involved. The zip that was analysed contained
the blank paper, the answer key and a spreadsheet asset — no submissions, no
grades, no roster.

---

## 5. Known limits of the first batch

**Formula scoring is brittle.** `=B2*C2` and `=C2*B2` are the same formula and
the repository's verifiable scorers (`exact_match`, `numeric_match`) cannot
express "any of these". The exam's own key accepts five spellings of one
answer. `mis200-spreadsheet-formulas/` works around this by using
subtraction and division — where exactly one operand order is right — for five
of its six single-cell items, and by pinning the order in the stem of the one
multiplication item. The workaround holds for this batch and bounds what later
batches can ask: a genuinely commutative item cannot be scored fairly until a
set-valued scorer exists.

**Two of 32 items are not worth authoring.** The ungraded warm-up measures
nothing. The select-all item cannot be scored by `exact_match` without fixing
an option order, and partial credit — which the exam gives — has no
representation in the current scorer set.

**Coverage so far.** 5 tasks, 27 samples: SLO2 ×2 tasks (11 samples), SLO9 ×2
(12), SLO1 ×1 (4). This is a first batch sized to prove the approach, not the
whole paper.
