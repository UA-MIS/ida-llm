# OM 300 exams → benchmark families: what was mapped, and what could not be

This note records how four OM 300 (Introduction to Operations Management) exams
were translated into the four `om300-exam*` task families, so that a reader of
those results knows what the numbers are anchored to. It is written at the
level of concepts and counts.

**It deliberately contains no exam item, option, scenario, number or answer
key**, and no exam asset is committed anywhere in this repository. Why, in §5.

---

## 1. The instruments

Four paper exams, each delivered through the university's LMS and scored by
answer key. Exam 4 is effectively the cumulative final: it re-tests the
forecasting, inventory, control-chart and project-network skills of Exams 1–3
and adds supply-chain and strategy fundamentals.

| exam | scored items | forced-choice | calculated / fill-in |
|---|---|---|---|
| 1 | 27 | 14 |
| 2 | 27 | 12 |
| 3 | 26 | 11 |
| 4 | 35 | 15 |

Forced-choice items are single-answer. Calculated items are formula-based with
a tolerance band on the printed key. Every calculation on every exam is
hand-computable; a spreadsheet was permitted but never required, so no family
asks for a formula or a file.

---

## 2. The families

One family per exam, one directory each, ids prefixed with the directory name.
All four are `verifiable` (an exact or numeric scorer) and synthetic: every
scenario, number and distractor was written for this repository.

| family | rungs | samples | what it covers |
|---|---|---|---|
| `om300-exam1-ops-forecasting` | 7 | operations scope and strategy concepts; forecasting and capacity concepts; labor and multifactor productivity; weighted factor rating; naive, moving-average, weighted moving-average, exponential-smoothing and seasonal forecasts; least-squares trend and forecast error; utilization, efficiency and bottleneck capacity |
| `om300-exam2-project-quality-spc` | 5 | project-management, quality and SPC concepts; activity duration, slack and crash cost; variables charts (x-bar, R); attribute charts (p, c); critical-path strings; in/out-of-control verdicts and reading a chart pair |
| `om300-exam3-inventory-eoq-lean` | 6 | supply-chain strategy and integration concepts; inventory-type and ABC/safety-stock concepts; lean, TPS, 5S and kanban concepts; inventory turnover, holding cost and reorder point; EOQ calculations; EPQ calculations |
| `om300-exam4-ops-analytics` | 8 | cumulative concept sweep; operations metrics; forecasting and error; EOQ/EPQ and cost at a given order size; x-bar and R chart limits; p-chart limits; project networks and crashing; critical-path sequence |

190 samples in all.

---

## 3. How the exam content was mapped

By content area. Every family item keeps the skill an exam item measures and
has its scenario, numbers and wording authored fresh.

| content area | appears on | family |
|---|---|---|
| operations scope, functions, strategy, life cycle, outsourcing | 1, 4 | exam 1 l1, exam 4 l1 |
| forecasting concepts, capacity and bottleneck concepts | 1, 4 | exam 1 l2, exam 4 l1 |
| productivity and percent change | 1, 4 | exam 1 l3, exam 4 l2 |
| weighted factor rating | 1 | exam 1 l4 |
| time-series forecasting methods and error | 1, 4 | exam 1 l5–l6, exam 4 l3 |
| capacity, utilization, bottleneck | 1 | exam 1 l7 |
| project-management concepts, critical path, crashing | 2, 4 | exam 2 l1/l2/l5, exam 4 l7–l8 |
| quality concepts and cost of quality | 2, 4 | exam 2 l1, exam 4 l1 |
| variables and attribute control charts | 2, 4 | exam 2 l3–l5, exam 4 l5–l6 |
| supply chain, sourcing, transport | 3, 4 | exam 3 l1, exam 4 l1 |
| inventory concepts, ABC, safety stock | 3, 4 | exam 3 l2, exam 4 l1 |
| inventory metrics, reorder point | 3, 4 | exam 3 l4, exam 4 l2 |
| EOQ and EPQ | 3, 4 | exam 3 l5–l6, exam 4 l4 |
| lean, TPS, 5S, kanban | 3, 4 | exam 3 l3, exam 4 l1 |

The families are longer than the exams on purpose: each calculation skill is
given several parameterisations, including variants whose nearest wrong method
lands well away from the key, so a score distinguishes the method from a lucky
rounding.

---

## 4. Outcome tagging, and where it differs from MIS 200

Results are filed by programme outcome (`curriculum/slo.yaml`), and the map
marks OM 300 against SLO1 (R), SLO2 (A) and SLO9 (I).

* Calculation families, and the two families that derive a result from data
  (critical-path strings, chart reading), are tagged **SLO2**.
* Forced-choice concept families are tagged **SLO9**.
* **Nothing is tagged SLO1.** Every item on all four exams is recognition or
  calculation; none requires an open-ended appraisal. SLO1 therefore reads "not
  measured yet" for OM 300 rather than being padded with a synthetic extension.
  Unlike MIS 200 there is no `om300-*-problem-solving` family.

The class page reads its units from `frontend/src/lib/units.ts`: four units, one
per exam, each mapped to exactly its own family. Unit 4 is titled "Cumulative
final". Because Unit 4 revisits skills of Units 1–3, the overlap is real, and
it is harmless: a family belongs to one unit only, so no result row appears
under two headings.

---

## 5. Why nothing here is copied from the exam

Exam items are the department's assessment instruments. They are neither
published nor ours to republish, and a benchmark that carried them would also
leak into model training data. So the families keep the *skill* an item
measures and nothing else.

* Scenarios, names, quantities and answer options were written fresh.
* Every item that needs a reference constant (a control-chart factor, a z
  value) prints the constant in the prompt, because a benchmark should test the
  method rather than recall of a formula sheet.
* Each prompt states its answer format (a letter, a number rounded a stated
  way, or a hyphenated path) and each scorer takes the last line.
* Before merge the committed files were compared to the exam texts by word
  eight-gram overlap; matches beyond generic stock phrases were rewritten.

---

## 6. Known limits

* **Figures.** Two exam items depend on pictures (a process-flow diagram and a
  pair of control charts). They were re-expressed as text: a described process
  with the rule for the bottleneck stated in the prompt, and numeric series with
  limits and the run rule stated. This measures the underlying skill, not
  reading a rendered chart.
* **One numeric target per sample.** An exam item with two blanks, or with two
  accepted values, became one item per target, or a forced-choice form.
* **Single tolerance.** The exams score with percentage bands; each family uses
  one absolute tolerance per file, and items are built so the nearest wrong
  method sits outside it.
* **Convention pinning.** Where the course convention is ambiguous (the indexing
  of a trend line's time axis, which form of a rate to report), the prompt pins
  it. An item that left it open would score the model's guess at the
  convention.
* **Instructor key not consulted for letters.** Keys were derived from the
  content and independently verified, not copied from the exam's key.
* **No SLO1 evidence** for OM 300, as in §4.
