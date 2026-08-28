# The researcher track

**Status: specification plus the task content it depends on.** The task
families named here are authored and validate in CI. The recommendation branch
is a *specification* — there is no recommendation engine in this repository yet
(README, "Known gaps" #4: *half of D-3 is not built*), so nothing below claims
to describe running code. Where a control or a capability does not exist, it is
named as a gap rather than assumed.

Read alongside [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) (how to author a task)
and [`docs/sensitive-material.md`](sensitive-material.md) (what may enter this
repository, and the cloud-versus-local rule this document extends).

---

## Why there is a second track at all

The platform's framing has been a teaching one: grading, quiz generation,
feedback. Roughly half of a university's faculty are **researchers**, and to
them "which model grades short answers best?" is not a question they have.

Their question has the same shape and different content: *which model should I
use for my scholarship, and can I trust it with work that is not published yet?*

So the benchmark and the recommendation grow a **research track** alongside the
teaching track. Many professors are both, which is why this is a **lens the user
toggles, not a second product**: one platform, one results store, one evidence
trail, and a fork early in the intake that decides which tasks the
recommendation is computed over.

Two things follow, and this document supplies both:

1. **Task families that measure scholarship work** — authored, in `tasks/`.
2. **A researcher branch of the recommendation** — its inputs, its output shape,
   and its data-sensitivity rule — specified here for whoever builds the engine.

---

## 1. The task families

Three families ship with this document. Together they cover the scholarship
tasks a researcher actually hands to a model: reading the literature, doing the
analysis, and writing the paper.

| family | kind | rungs | what it measures |
|---|---|---|---|
| [`tasks/research-analysis/`](../tasks/research-analysis/) | verifiable | 6 | data-analysis reasoning and coding for research: summary statistics, effect sizes, multiplicity correction, power, tracing an analysis script, and repairing a buggy one |
| [`tasks/research-synthesis/`](../tasks/research-synthesis/) | subjective | 4 | literature work: faithful summarisation of one abstract, synthesis across four, appraisal of a design, and a related-work paragraph from a closed source set |
| [`tasks/scholarly-writing/`](../tasks/scholarly-writing/) | subjective | 4 | producing the researcher's own prose: an abstract from a results table, editing an overclaim, making a methods section reproducible, and answering reviewers |

### The candidate set, ranked and provisional

The three families above are the first three rows of a longer list. The ranking
is by *benchmarkable value* — how much a researcher would act on the answer,
divided by how hard the task is to measure honestly — and it is **provisional
until the researcher interviews report** (board #23, synthesis #43). Nothing
here should be read as settled.

| # | scholarship task | status | why here |
|---|---|---|---|
| 1 | data analysis and coding for research | **built** (`research-analysis`) | the only one of the set that is cleanly *verifiable*, so it costs nothing to run and discriminates sharply. Highest value per unit of measurement effort. |
| 2 | summarising dense literature | **built** (`research-synthesis` l1-l2) | universal across fields, and the failure mode (claim inflation) is both common and consequential. |
| 3 | drafting and editing academic prose | **built** (`scholarly-writing`) | the task researchers report handing to a model most often; the overclaim and fabrication failures are directly measurable. |
| 4 | critical appraisal of a design | **built** (`research-synthesis` l3) | included because it is where generic scepticism masquerades as competence, and that is invisible unless measured. |
| 5 | hypothesis generation | not built | high value, hard to score: novelty and plausibility resist an anchored rubric, and a judge model grading "is this a good hypothesis" is measuring its own priors. Needs a scoring spike before it is worth authoring. |
| 6 | grant writing | not built | high value to researchers, but hard to make synthetic without collapsing into a general writing-quality benchmark with no research content in it. Also the most field-specific of the set. |
| 7 | systematic-review screening (include/exclude against criteria) | not built | would be **verifiable** — inclusion against stated criteria has a right answer — which makes it the cheapest unbuilt candidate and the one to author next. |

> Rows 5-7 are named so that the gap is visible rather than implied. Row 7 in
> particular is the recommendation for the next family: it is verifiable,
> cheap to run, and covers a task no built family touches.

Each family is a difficulty ladder in the sense
[`tasks/SCHEMA.md`](../tasks/SCHEMA.md) defines: one rung per file, each rung
adding exactly one stated demand, rung 1 nearly free and the top rung genuinely
hard. The header comment of every file says what its rung adds.

### The two failure modes these families are built around

A researcher-facing benchmark that only asked "is the output good?" would miss
the two things that actually make a model unusable for scholarship, so both are
scored explicitly and repeatedly:

- **Fabrication.** A citation, a figure, a software version or a methods detail
  that the model supplied rather than found. It is the failure that reads as an
  *improvement* — the paragraph is better after the fabrication than before —
  and it is a research-integrity incident rather than an inconvenience.
  `research-synthesis/l4` and `scholarly-writing/l3` are built entirely on it,
  each pairing a no-fabrication criterion against a usefulness criterion at
  equal weight so that neither can be bought with the other.
- **Claim inflation.** An association rendered as a cause, a null rendered as
  "promising", a single-site result rendered as general. `research-synthesis/l1`
  and `scholarly-writing/l2` measure it directly, and
  `scholarly-writing/l1` catches its most consequential form — leading an
  abstract with a significant secondary outcome when the primary was null.

Every subjective family also carries at least one sample where **the honest
response is that nothing is wrong**. Without it, a model that appends a caveat
to everything is never penalised, and reflexive hedging is exactly what makes an
AI-assisted literature review worthless.

### Content hygiene

Everything in these families is **synthetic**, written for the file, and
labelled as fictional inside the prompt the model sees. That is a stricter line
than [`tasks/SCHEMA.md`](../tasks/SCHEMA.md) §Dataset-hygiene requires, and it
is drawn for reasons specific to this track:

- **No real unpublished research or IP enters the repository.** The researcher
  audience exists *because* unpublished work is sensitive; a benchmark that
  ingested a colleague's in-progress manuscript to measure summarisation would
  be the exact hazard it is meant to help them avoid.
- **Sources are labelled A/B/C/D rather than by an invented author-year.** An
  invented citation that looks real is a hazard on its own — this repository is
  public, and a fabricated `Okonjo & Braddock (2021)` in it could be scraped,
  cited, or trained on. Letters are also what make attribution *checkable* by a
  judge that sees only the prompt and the response.
- **Fictional identifiers are marked as fictional in the text itself**
  (`DRKS-FICTIONAL-0001` in `scholarly-writing/l3`), so nothing here can be
  mistaken for a real trial registration.

Nothing in these families is derived from MIS 200 material, from any course, or
from any person's work.

---

## 2. The tag vocabulary: how the fork reaches the tasks

The recommendation engine has to answer "which tasks is this recommendation
computed over?" **before** it can compute anything. The intake fork is only
meaningful if the answer is machine-readable, and today there are exactly two
task fields a consumer can select on:

| field | published by | already documented as |
|---|---|---|
| `domain` | `GET /tasks` | *"Academic domain… Used by the recommender (D-3)"* — `ida_core.contracts` |
| `tags` | `GET /tasks` | family membership and ladder rung — `tasks/SCHEMA.md` |

`domain` is one string and is already spoken for by subject matter
(`statistics`, `assessment`, `research-methods`). So the persona fork lives in
**`tags`**, which is a free list and is exposed by the API.

**The vocabulary, as used by the families in this document:**

| tag | meaning | on which families |
|---|---|---|
| `persona-researcher` | the task represents work a researcher does on their own scholarship | all three researcher families |
| `persona-teacher` | the task represents work a teacher does for a course | *not yet applied* — see the gap below |
| `use-mode-assist` | the model is helping the professor do their own work | all three researcher families |
| `use-mode-capability` | the model is being asked whether it can simply *do* the outcome (the integrity-risk question) | *not yet applied* |
| `use-mode-learning-aid` | the model is helping a student learn rather than handing over the answer | *not yet applied* |

The `persona-*` and `use-mode-*` axes are independent, and both are needed: a
teacher and a researcher can both want assist-mode help, and a single task can
belong to only one persona but any number of tasks can share a use-mode.

> **Gap, stated rather than assumed.** The existing families
> (`quantitative-quiz`, `conceptual-grading`) are **not** tagged
> `persona-teacher`, and this change does not tag them. Adding a tag to an
> existing task changes its `content_sha`, which is the value
> `ida_harness.regrade` compares before grading an archived run — so
> retro-tagging the exemplars would make already-finished runs un-regradable.
> That is a deliberate decision to make in its own commit, not a side effect of
> adding a new family. **Until it happens, a consumer must treat "absence of
> `persona-researcher`" as the teaching track**, not "absence of
> `persona-teacher`". Whoever builds the engine should read that as a
> temporary asymmetry with a known fix, not as the intended contract.

---

## 3. The recommendation branch for researchers

### 3.1 The intake fork

This is the researcher half of the persona + purpose fork (**D-47**), and it is
specified here to be **absorbed by the recommendation-intake spec** (board #55),
which owns the flow as a whole. What follows is the branch semantics that spec
needs, not a competing design for it.

The intake asks **which hat, and for whom**, before it recommends anything.
Two questions, in this order:

1. **Which role are you asking as?** *teacher* / *researcher* / *both*
2. **Who is the model for?** *me* / *my students*

The second question is only asked of the teaching branch — "for my students" has
no researcher analogue, and asking it anyway is how an intake makes a researcher
feel the product is not for them. A user who answers *both* gets both branches
reported separately rather than averaged; averaging a teaching score and a
research score produces a number that describes nobody.

The researcher branch then asks one question the teaching branch does not, and
it is the one that changes the answer most:

3. **Will the material you send be unpublished work, your own data, or anything
   under an IP or confidentiality obligation?** *yes* / *no* / *some of it*

### 3.2 What the branch selects

| the user answered | tasks the recommendation is computed over |
|---|---|
| researcher, any scholarship task | tasks tagged `persona-researcher` |
| researcher, specifically "analysis / code" | `domain: research-methods` — the `research-analysis` ladder |
| researcher, specifically "literature" | `research-synthesis` |
| researcher, specifically "writing / revision" | `scholarly-writing` |
| teacher | tasks **not** tagged `persona-researcher` (see the gap in §2) |
| both | both sets, reported as two panels |

### 3.3 The output shape

A researcher recommendation is three things, and the third is what the platform
exists for:

1. **A model**, named as a `models.yaml` key.
2. **A surface** — the deployment the researcher should use it through, which is
   where the privacy rule in §4 binds. Same model, different surface, different
   answer.
3. **The receipts** — the specific task ids, rungs and result rows the
   recommendation rests on, at a granularity a professor can click into. This is
   D-3's evidence-traceability requirement and it is already supported by the
   data model: `results` carries the score, the serving config, the task content
   hash and the evidence pointer (README, Known gaps #4).

Two rules that are particular to the research branch:

- **Report the ladder, not the mean.** A researcher choosing a model for
  analysis needs to know that it holds up through `l4` and breaks at `l6`. A
  single mean over six rungs answers a question nobody asked — this is the same
  argument `tasks/SCHEMA.md` makes for one rung per file, carried through to the
  output.
- **A subjective family with no judge configured must report a blank, never a
  zero.** `IDA_JUDGE_MODEL_KEY` is unset by default, so
  `research-synthesis` and `scholarly-writing` currently produce
  `scorable: false` and `score: null`
  ([`docs/llm-judge.md`](llm-judge.md)). A recommendation that renders that as
  0.0 would report a good model as a failing one. Two of the three researcher
  families are subjective, so this is not an edge case on this branch — it is
  the default state.

---

## 4. The research-privacy rule

This is the researcher analogue of the FERPA story, and it is **not the same
rule**. FERPA is a legal regime about education records with a defined
de-identification standard. Unpublished research is a matter of **priority,
confidentiality obligation and IP** — there is no de-identification that makes a
novel result safe to disclose, because the result *is* the sensitive thing.

The surface catalog (board #25) is where the licensing and policy detail for
this belongs; what follows is the rule the *recommendation* needs, not a
substitute for that catalog.

That difference has one practical consequence: the intake pipeline's
de-identification path
([`docs/intake-pipeline.md`](intake-pipeline.md)) is the right control for
course material and is **the wrong control here**. You cannot clean a
hypothesis.

### The rule

| what the researcher is sending | recommended surface |
|---|---|
| published work, public datasets, their own writing about published results | any enabled model, cloud included |
| unpublished data, an in-progress manuscript, a grant application before submission, anything under an NDA or a collaborator's embargo | **local or on-campus inference only** |
| "some of it" | the recommendation is computed for the sensitive case — the stricter branch wins |

The stricter branch wins by default because the failure is silent and
irreversible: nothing tells a researcher that a paragraph of their unpublished
methods went into a provider's logs, and nothing takes it back.

### The honest gap

> **There is no local inference surface available today.** Campus vLLM
> ("Sparks") is **deferred and unreachable** — the tenant egress policy grants
> `:443` only, vLLM defaults to `:8000`, and the NetworkPolicy lives in
> `platform-infra` (`docs/sensitive-material.md` §5,
> `infra/inference/README.md`). `models.yaml` currently enables exactly two
> entries: `mock` (deterministic, not a language model) and `luna` (a hosted
> OpenAI model on a $25 test cap).
>
> So the sensitive branch of this rule has **no model to recommend**. The
> correct behaviour for the engine, until that changes, is to say so plainly —
> *"for unpublished work we have no benchmarked local option yet; here is what we
> would recommend once one exists, and here is what we can tell you about the
> cloud options if you decide the material is not sensitive"* — and never to
> quietly fall back to a cloud model because the local list was empty. A
> recommendation that fails open on a privacy question is worse than no
> recommendation.
>
> This is also the strongest argument the researcher track supplies for
> prioritising local inference: it is the difference between a recommendation
> and an apology.

### What this does not change

Nothing here touches the platform's own data handling, which is already settled
and stricter than this document needs: run execution is gated by
`auth_mode=token` (D-49), every transcript is archived and published by design,
and answer keys are redacted from `GET /tasks/{id}` unless the caller holds the
`author` role. The rule above is about **what we advise a researcher to do with
their own material**, not about what this repository stores.

---

## 5. Scope: what this document deliberately does not decide

The recommendation **flow and its UI are being built separately**. This document
supplies the researcher-side *content* and *contract* and stops there. In
particular it does not specify:

- the intake's screens, wording or component structure;
- how the recommendation is scored or ranked across models;
- the results-display layout, beyond the two reporting rules in §3.3 that are
  properties of the data rather than of the design.

Where §3.1 gives question wording, treat it as the *semantics the branch needs*
— which distinctions must be drawn before a recommendation can be computed —
not as approved copy.

---

## 6. Open questions

- **When do the existing families get `persona-teacher`?** It needs its own
  commit and an accepted `content_sha` change (§2). Doing it at the same time as
  a judge-calibration run would waste the run.
- **Does a researcher branch need a "for my collaborators" mode?** The
  teaching branch has "for my students" with guardrails. Multi-institution
  collaborations have a real analogue — material that is fine for one
  institution's tooling and not another's — and nothing here covers it.
- **How is a null result scored?** Three of the samples in these families turn
  on treating an informative null honestly, and it is currently a rubric
  criterion rather than a reported dimension. If "does not inflate a null" is as
  important as it looks, it may deserve to be visible in the output rather than
  averaged into a rubric score.
- **Which scholarship tasks are missing?** Grant writing and hypothesis
  generation are named in the project direction and are not covered by these
  three families. Grant writing in particular is hard to make synthetic without
  becoming a writing-quality benchmark with no research content in it.
