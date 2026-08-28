"""The recommendation flow: interrogate first, recommend only with receipts.

**The product idea, in one paragraph.** "What's the best AI?" has no useful
answer, and handing back a mushy best guess is how a recommendation engine loses
a skeptic permanently.  So this engine does the opposite of guessing: it asks
targeted questions, and when it still does not have what it needs it *says what
is missing and stops*.  That refusal is not a failure mode — it is the same
"no evidence, no confident answer" principle the benchmark applies to models,
turned around and applied to the professor's own inputs.

**There are three ways to get no recommendation, and they are different.**
Collapsing them would waste the whole mechanism, so each is its own status:

``need_more_context``
    We have not been told enough.  The gaps are named, question by question, and
    answering them is all that stands in the way.
``no_eligible_model``
    We understood perfectly, and a *hard* constraint the professor stated (data
    must stay on campus; free tools only) eliminates every model available
    today.  The honest answer is which constraint did it — never a cloud model
    offered anyway with a footnote.
``insufficient_evidence``
    We understood, models qualify, but this platform has not benchmarked them on
    anything resembling the task.  We name the tasks we would need to run.

**Rule-based on purpose (v1).** Every judgement below is a readable rule over
the benchmark data — no model is called to produce a recommendation.  A
recommendation engine that asks an LLM which LLM to use has exactly the
credibility problem this project exists to fix, and a professor cannot audit it.
The rules are dull, inspectable, and each one names the evidence it used.

**Why the intake is adaptive rather than a fixed form.** A busy professor
bounces off a ten-question wall (direction D in the sprint planning doc): every
question here declares what it *depends on*, so a researcher is never asked
about FERPA and someone using a tool themselves is never asked about student
guardrails.  :func:`applicable_questions` is the single place that decides what
is asked — the frontend renders it, and this module re-derives it server-side so
a client that skips a question cannot skip the gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ida_api.leaderboard import (
    NOT_REAL_MODEL_TAGS,
    ON_CAMPUS_TAGS,
    RESIDENCY_LABEL,
    ModelResult,
    TaskLeaderboard,
    data_residency,
)
from ida_api.trust import Confidence
from ida_core.contracts import ModelEntry, TaskKind

# ==========================================================================
# The question tree
# ==========================================================================


class IntakeOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    detail: str | None = None


class IntakeCondition(BaseModel):
    """ "Ask this only if question ``question_id`` was answered with one of ``values``."."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    values: list[str]


class IntakeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    detail: str | None = None
    options: list[IntakeOption]
    required: bool = True
    """Required *when it applies*.  A question whose condition is unmet is never
    required, however this flag is set — see :func:`applicable_questions`."""

    why_it_matters: str
    """Shown next to the question.  A professor who can see why a question
    changes the answer tolerates far more questions than one who cannot."""

    depends_on: IntakeCondition | None = None
    branch_note: str | None = None
    """Displayed when the question appears *because of* a previous answer — this
    is where the FERPA branch explains itself in the professor's own terms."""


QUESTIONS: list[IntakeQuestion] = [
    IntakeQuestion(
        id="role",
        prompt="Which hat are you wearing right now?",
        detail="About half of faculty come to this as researchers, not teachers. The two get different answers.",
        why_it_matters="Teaching tasks and scholarship tasks are benchmarked separately; we would rather ask than assume you teach.",
        options=[
            IntakeOption(
                value="teacher", label="Teaching", detail="Courses, assessment, students."
            ),
            IntakeOption(
                value="researcher", label="Research", detail="Papers, data, grants, literature."
            ),
            IntakeOption(value="both", label="Both", detail="We will ask about each in turn."),
        ],
    ),
    IntakeQuestion(
        id="beneficiary",
        prompt="Is this for your own work, or for your students to use?",
        why_it_matters="A tool you use yourself and a tool you put in front of students need different settings, different guardrails, and sometimes a different model.",
        depends_on=IntakeCondition(question_id="role", values=["teacher", "both"]),
        options=[
            IntakeOption(value="for_me", label="For me", detail="I will be the one using it."),
            IntakeOption(
                value="for_students",
                label="For my students",
                detail="Students will use it directly.",
            ),
            IntakeOption(value="both", label="Both"),
        ],
    ),
    IntakeQuestion(
        id="teaching_task",
        prompt="What do you want help with?",
        why_it_matters="This is what we look up in the benchmark. Everything after it is about which of the measured models fits your situation.",
        depends_on=IntakeCondition(question_id="role", values=["teacher", "both"]),
        options=[
            IntakeOption(
                value="grading",
                label="Grading student work",
                detail="Marking short answers, applying a rubric, partial credit.",
            ),
            IntakeOption(
                value="quiz_generation",
                label="Writing quiz or exam items",
                detail="New items, parameterised variants, distractors.",
            ),
            IntakeOption(
                value="feedback",
                label="Writing feedback to students",
                detail="Formative comments on submitted work.",
            ),
            IntakeOption(value="content_slides", label="Course content and slides"),
            IntakeOption(
                value="tutoring",
                label="Tutoring or explaining concepts",
                detail="A study aid that helps a student get there, rather than answering for them.",
            ),
            IntakeOption(value="data_analysis", label="Quantitative work and analysis"),
        ],
    ),
    IntakeQuestion(
        id="research_task",
        prompt="What part of your research do you want help with?",
        why_it_matters="Research tasks are benchmarked separately from teaching tasks; a model that grades well is not automatically a good literature reviewer.",
        depends_on=IntakeCondition(question_id="role", values=["researcher", "both"]),
        options=[
            IntakeOption(value="literature_review", label="Literature review and summarising"),
            IntakeOption(value="drafting_editing", label="Drafting and editing papers"),
            IntakeOption(value="research_data_analysis", label="Data analysis and statistics"),
            IntakeOption(value="coding_for_research", label="Writing code for research"),
            IntakeOption(value="grant_writing", label="Grant writing"),
        ],
    ),
    IntakeQuestion(
        id="student_data",
        prompt="Will this touch student work, grades, or anything that identifies a student?",
        why_it_matters="This is the question that most often changes the answer. It decides whether a cloud model is on the table at all.",
        depends_on=IntakeCondition(question_id="role", values=["teacher", "both"]),
        options=[
            IntakeOption(value="yes", label="Yes"),
            IntakeOption(
                value="no", label="No", detail="Nothing a student wrote, and no names or IDs."
            ),
            IntakeOption(
                value="unsure", label="I'm not sure", detail="We will treat this as a yes."
            ),
        ],
    ),
    IntakeQuestion(
        id="ferpa_hard_requirement",
        prompt="Does that student data have to stay on campus?",
        branch_note=(
            "Because student work is involved, FERPA is in play. We can bias toward models "
            "we run on our own hardware, so student data never leaves campus — no third "
            "party ever sees it. That is a recommendation only this project can make, "
            "because we have the campus GPUs."
        ),
        why_it_matters="If it is a hard requirement we will not offer you a cloud model at all, even a better-scoring one.",
        depends_on=IntakeCondition(question_id="student_data", values=["yes", "unsure"]),
        options=[
            IntakeOption(
                value="yes",
                label="Yes — it must stay on campus",
                detail="Hard requirement. Cloud models are ruled out.",
            ),
            IntakeOption(
                value="no",
                label="No — I remove identifiers first",
                detail="You de-identify before pasting anything.",
            ),
            IntakeOption(
                value="unsure",
                label="I'm not sure",
                detail="We will treat this as a hard requirement.",
            ),
        ],
    ),
    IntakeQuestion(
        id="unpublished_data",
        prompt="Would you be putting in unpublished data, or work you have not released yet?",
        why_it_matters="It is not FERPA, but it is the same shape of problem: some vendors' terms allow training on what you send. Unpublished work is worth keeping on campus for exactly the same reason student data is.",
        depends_on=IntakeCondition(question_id="role", values=["researcher", "both"]),
        options=[
            IntakeOption(value="yes", label="Yes"),
            IntakeOption(value="no", label="No — it is already public"),
        ],
    ),
    IntakeQuestion(
        id="subject_level",
        prompt="What level are you working at?",
        why_it_matters="Our benchmark tasks are graded on a difficulty ladder. A model that handles introductory items can fail on graduate ones, so we match the evidence to your level.",
        options=[
            IntakeOption(
                value="intro_undergrad", label="Introductory undergraduate", detail="e.g. MIS 200"
            ),
            IntakeOption(value="advanced_undergrad", label="Advanced undergraduate"),
            IntakeOption(value="graduate", label="Graduate"),
            IntakeOption(value="mixed", label="A mix"),
        ],
    ),
    IntakeQuestion(
        id="stakes",
        prompt="How bad is a mistake here?",
        why_it_matters="This sets the bar we recommend against. For anything that lands on a transcript we will only recommend where a program — not another AI — checked the answers.",
        options=[
            IntakeOption(
                value="high",
                label="Serious",
                detail="It affects a grade of record, or goes out to students unreviewed.",
            ),
            IntakeOption(
                value="medium",
                label="Moderate",
                detail="I review the output before it counts for anything.",
            ),
            IntakeOption(
                value="low", label="Low", detail="Brainstorming, first drafts, throwaway work."
            ),
        ],
    ),
    IntakeQuestion(
        id="budget",
        prompt="Free and campus-hosted only, or is paid on the table?",
        why_it_matters="We will not lead with a paid model if free is a hard limit for you — and on campus hardware, free is often the honest answer anyway.",
        options=[
            IntakeOption(value="free_or_local_only", label="Free or campus-hosted only"),
            IntakeOption(
                value="modest_paid",
                label="A small amount is fine",
                detail="Personal or small departmental spend.",
            ),
            IntakeOption(value="department_budget", label="There is a budget"),
        ],
    ),
    IntakeQuestion(
        id="surface",
        prompt="Where would you actually use this?",
        required=False,
        why_it_matters="The model is only half of a recommendation. Telling you to 'use Claude' when you needed a web page to type into is not an answer.",
        options=[
            IntakeOption(
                value="chat_web",
                label="A website I type into",
                detail="ChatGPT, Claude, and the like.",
            ),
            IntakeOption(value="desktop_app", label="A desktop or phone app"),
            IntakeOption(
                value="lms_integrated", label="Inside our LMS", detail="Blackboard, Canvas."
            ),
            IntakeOption(value="api_integration", label="Wired into something with code"),
            IntakeOption(
                value="unsure",
                label="I don't know yet",
                detail="We will suggest the simplest thing that works.",
            ),
        ],
    ),
    IntakeQuestion(
        id="ai_trust",
        prompt="How much do you trust AI for this today?",
        required=False,
        why_it_matters="Purely about how we present the answer. A skeptic gets the evidence first; nothing about the recommendation itself changes.",
        options=[
            IntakeOption(
                value="skeptical", label="Not much", detail="Show me the proof before the advice."
            ),
            IntakeOption(value="curious", label="Open to it"),
            IntakeOption(value="confident", label="I use it already"),
        ],
    ),
]

QUESTIONS_BY_ID: dict[str, IntakeQuestion] = {q.id: q for q in QUESTIONS}


def applicable_questions(answers: dict[str, str]) -> list[IntakeQuestion]:
    """The questions that actually apply, given what has been answered so far.

    The single source of truth for "what is being asked".  The frontend calls
    the equivalent client-side helper to draw the form, and this function runs
    again server-side before any gate — so a client that omits a question it was
    supposed to ask cannot talk its way past the completeness check.
    """
    applicable: list[IntakeQuestion] = []
    for question in QUESTIONS:
        condition = question.depends_on
        if condition is None or answers.get(condition.question_id) in condition.values:
            applicable.append(question)
    return applicable


# ==========================================================================
# Mapping an answer onto the benchmark
# ==========================================================================


@dataclass(frozen=True)
class TaskArea:
    """One thing a professor might want help with, and how to find evidence for it.

    ``match_tags`` / ``match_domains`` are matched against the *task catalog*
    rather than hardcoding task ids, so authoring a new task family into an
    existing area is a YAML edit here too.  ``match_use_modes`` reads the
    ``use-mode:`` facet from ``project-direction-2026-08-26.md`` the moment task
    files start carrying it; until then it simply matches nothing.
    """

    value: str
    label: str
    match_tags: frozenset[str] = frozenset()
    match_domains: frozenset[str] = frozenset()
    match_use_modes: frozenset[str] = frozenset()
    prompt_template: str = ""
    default_surface: str = "chat_web"
    student_facing_guardrails: tuple[str, ...] = ()


GRADING_TEMPLATE = """You are helping me grade {level} student answers in {subject}.

Marking key:
<<<
[paste your marking key or rubric here]
>>>

Student answer:
<<<
[paste one student answer here]
>>>

Do all of the following, in this order:
1. List which points from the marking key the answer does and does not contain.
2. Propose a mark out of [total], and show how you arrived at it point by point.
3. Say explicitly what you were unsure about.

Do not invent credit for anything not in the key. If the answer is correct by a
route the key did not anticipate, say so rather than marking it wrong.
I will review every mark before it counts.
"""

QUIZ_TEMPLATE = """Write {n} new quiz items for {level} students in {subject}.

Here is one existing item I am happy with, as the pattern to follow:
<<<
[paste one of your own items, with its answer]
>>>

For each new item give me:
- the item text
- the correct answer, with the working
- three plausible wrong answers, and for each one, the specific mistake a student
  would have made to arrive at it

Keep the difficulty the same as my example. Do not reuse my numbers.
"""

FEEDBACK_TEMPLATE = """Write formative feedback on this {level} {subject} submission.

Submission:
<<<
[paste the student's work — remove their name first]
>>>

Rules:
- Point to what the student actually did, quoting their own words.
- Name the single most useful thing to fix next, and why it matters.
- Do NOT rewrite the work or give the answer away; the student has to make the fix.
- Two short paragraphs, addressed to the student, plain language.
"""

TUTORING_TEMPLATE = """Act as a tutor for a {level} student studying {subject}.

The student will ask you about: [topic]

Rules you must follow:
- Never give the final answer outright. Ask what they have tried first.
- Give one hint at a time, then wait for their attempt.
- When they are wrong, name the misconception rather than just correcting it.
- If they ask you to just do it, decline and offer the next hint instead.
- End by asking them to explain the idea back in their own words.
"""

ANALYSIS_TEMPLATE = """Help me with a {level} {subject} analysis.

The data / summary statistics:
<<<
[paste them here]
>>>

What I want: [state the question]

Show every step of the working, name the method you chose and why that one,
and state the assumptions it needs. Flag anything in the data that would make
the method inappropriate. I will check the arithmetic.
"""

CONTENT_TEMPLATE = """Draft course content for {level} students in {subject}.

Topic: [topic]
Learning outcome it should serve: [paste the outcome from your syllabus]

Give me an outline first, before any prose, so I can redirect it.
Flag anywhere you are unsure of the disciplinary content.
"""

LITERATURE_TEMPLATE = """Summarise this paper for me.

<<<
[paste the abstract, or the sections you care about]
>>>

Give me:
- the claim, in one sentence
- the method, and what it can and cannot support
- what is genuinely new versus what is restated from prior work
- anything the authors concede as a limitation

Quote the paper for each point. If something is not in the text I gave you, say
so rather than filling it in from memory.
"""

DRAFTING_TEMPLATE = """Edit this passage from a paper I am writing.

<<<
[paste the passage]
>>>

Target venue / audience: [state it]

Tighten it without changing any claim. Flag any sentence where you think the
claim is stronger than the evidence I have given. Show me your edit and a short
note on each substantive change. Do not add citations.
"""

RESEARCH_CODE_TEMPLATE = """Help me write analysis code.

Language / environment: [state it]
What the data looks like: [describe columns and types]
What I need the code to do: [state it]

Give me the code with comments, then list the ways it could silently give a
wrong answer on data shaped slightly differently from what I described.
"""

GRANT_TEMPLATE = """Help me with a section of a grant proposal.

Programme / solicitation: [name it, and paste the review criteria if you have them]
Section: [e.g. broader impacts]
My draft or notes:
<<<
[paste]
>>>

Rewrite to address the stated review criteria explicitly, and tell me which
criteria my text currently does not touch at all.
"""

TASK_AREAS: dict[str, TaskArea] = {
    "grading": TaskArea(
        value="grading",
        label="Grading student work",
        match_tags=frozenset({"conceptual-grading", "grading", "marking"}),
        match_domains=frozenset({"assessment"}),
        match_use_modes=frozenset({"professor-assist"}),
        prompt_template=GRADING_TEMPLATE,
        student_facing_guardrails=(
            "Grading is not a student-facing use. If students see the output, they see "
            "their own mark and your review of it — never the raw model output.",
        ),
    ),
    "quiz_generation": TaskArea(
        value="quiz_generation",
        label="Writing quiz or exam items",
        match_tags=frozenset(
            {"quantitative-quiz", "item-generation", "distractor-design", "arithmetic"}
        ),
        match_domains=frozenset({"quantitative-methods"}),
        match_use_modes=frozenset({"professor-assist"}),
        prompt_template=QUIZ_TEMPLATE,
    ),
    "feedback": TaskArea(
        value="feedback",
        label="Writing feedback to students",
        match_tags=frozenset({"feedback"}),
        match_domains=frozenset({"writing"}),
        match_use_modes=frozenset({"professor-assist"}),
        prompt_template=FEEDBACK_TEMPLATE,
    ),
    "content_slides": TaskArea(
        value="content_slides",
        label="Course content and slides",
        match_tags=frozenset({"content", "slides", "course-content"}),
        match_use_modes=frozenset({"professor-assist"}),
        prompt_template=CONTENT_TEMPLATE,
    ),
    "tutoring": TaskArea(
        value="tutoring",
        label="Tutoring or explaining concepts",
        match_tags=frozenset({"tutoring", "learning-aid", "scaffolding"}),
        match_use_modes=frozenset({"student-learning-aid"}),
        prompt_template=TUTORING_TEMPLATE,
        student_facing_guardrails=(
            "Set it up as a tutor, not an answer engine — the template below refuses to "
            "hand over answers, and that refusal is the whole point.",
            "Tell students plainly that it can be confidently wrong, and that checking it "
            "against the course material is part of the exercise.",
            "Do not have students paste anything identifying themselves or a classmate.",
        ),
    ),
    "data_analysis": TaskArea(
        value="data_analysis",
        label="Quantitative work and analysis",
        match_tags=frozenset(
            {
                "descriptive-statistics",
                "inference",
                "regression",
                "spread",
                "normal-distribution",
                "hypothesis-testing",
                "sampling",
            }
        ),
        match_domains=frozenset({"statistics", "quantitative-methods", "mathematics"}),
        prompt_template=ANALYSIS_TEMPLATE,
    ),
    "literature_review": TaskArea(
        value="literature_review",
        label="Literature review and summarising",
        match_tags=frozenset({"literature-review", "summarisation"}),
        match_use_modes=frozenset({"researcher-assist"}),
        prompt_template=LITERATURE_TEMPLATE,
    ),
    "drafting_editing": TaskArea(
        value="drafting_editing",
        label="Drafting and editing papers",
        match_tags=frozenset({"drafting", "editing", "academic-writing"}),
        match_use_modes=frozenset({"researcher-assist"}),
        prompt_template=DRAFTING_TEMPLATE,
    ),
    "research_data_analysis": TaskArea(
        value="research_data_analysis",
        label="Data analysis and statistics",
        match_tags=frozenset(
            {"descriptive-statistics", "inference", "regression", "hypothesis-testing"}
        ),
        match_domains=frozenset({"statistics", "quantitative-methods"}),
        prompt_template=ANALYSIS_TEMPLATE,
    ),
    "coding_for_research": TaskArea(
        value="coding_for_research",
        label="Writing code for research",
        match_tags=frozenset({"research-code"}),
        prompt_template=RESEARCH_CODE_TEMPLATE,
        default_surface="api_integration",
    ),
    "grant_writing": TaskArea(
        value="grant_writing",
        label="Grant writing",
        match_tags=frozenset({"grant-writing"}),
        match_use_modes=frozenset({"researcher-assist"}),
        prompt_template=GRANT_TEMPLATE,
    ),
}

LEVEL_LABEL: dict[str, str] = {
    "intro_undergrad": "introductory undergraduate",
    "advanced_undergrad": "advanced undergraduate",
    "graduate": "graduate",
    "mixed": "mixed-level",
}

SURFACE_LABEL: dict[str, str] = {
    "chat_web": "The vendor's web chat",
    "desktop_app": "The vendor's desktop or phone app",
    "lms_integrated": "Inside your LMS",
    "api_integration": "Wired in through the API",
    "on_campus_chat": "The campus-hosted chat endpoint",
}


def matched_task_ids(area: TaskArea, boards: list[TaskLeaderboard]) -> list[str]:
    """Which benchmark tasks speak to this area."""
    matches: list[str] = []
    for board in boards:
        tags = {t.lower() for t in board.tags}
        use_modes = {v.lower() for v in board.facets.get("use_mode", [])}
        if (
            tags & area.match_tags
            or board.domain.lower() in area.match_domains
            or use_modes & area.match_use_modes
        ):
            matches.append(board.task_id)
    return matches


# ==========================================================================
# Response shapes
# ==========================================================================

RecommendationStatus = Literal[
    "ok", "need_more_context", "no_eligible_model", "insufficient_evidence"
]


class Gap(BaseModel):
    """One thing we still need before we will answer."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    prompt: str
    why_it_matters: str


class Receipt(BaseModel):
    """A single citable measurement behind a claim (D-3).

    ``run_id`` is the whole point: the professor can open the exact run and read
    the transcripts, the scorer and the serving config that produced the number
    we just used to advise them.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_title: str
    task_kind: TaskKind
    model_key: str
    run_id: str
    mean_score: float | None
    scored_count: int
    sample_count: int
    confidence: Confidence
    trust_label: str


class CostNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: Literal["free", "campus_hosted", "paid"]
    label: str
    detail: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float


class Constraint(BaseModel):
    """Something the professor told us that narrowed the field, said out loud."""

    model_config = ConfigDict(extra="forbid")

    label: str
    detail: str
    hard: bool
    """A hard constraint eliminates models outright.  A soft one only reorders."""


class Recommendation(BaseModel):
    """The package, not just a model name."""

    model_config = ConfigDict(extra="forbid")

    model_key: str
    display_name: str
    headline: str
    why: list[str]
    surface: str
    surface_label: str
    surface_rationale: str
    cost: CostNote
    data_residency: str
    data_residency_label: str
    prompt_template: str
    guardrails: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    receipts: list[Receipt] = Field(default_factory=list)
    evidence_score: float | None = None
    """Mean of this model's scores on the matched tasks, weighted by how many
    samples each was scored on.  Shown, not hidden, because a recommendation
    whose ranking basis is invisible is a black box."""

    verifiable_evidence: bool
    """True when at least one receipt comes from a program-checked task."""


class ContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str


class RecommendationRequest(BaseModel):
    """``POST /recommend``.  Just the answers, keyed by question id.

    A flat ``dict[str, str]`` rather than a field per question on purpose: the
    question tree is data (see :data:`QUESTIONS`), and adding a question should
    not be a schema change in two places.  Unknown ids and unknown option values
    are rejected by :func:`validate_answers` before anything is evaluated, so
    the looseness of the type is not looseness at the boundary.
    """

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, str] = Field(default_factory=dict)


class RecommendationResponse(BaseModel):
    """``POST /recommend``."""

    model_config = ConfigDict(extra="forbid")

    status: RecommendationStatus
    message: str
    context_summary: list[ContextItem] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    primary: Recommendation | None = None
    alternatives: list[Recommendation] = Field(default_factory=list)
    matched_task_ids: list[str] = Field(default_factory=list)
    missing_benchmarks: list[str] = Field(default_factory=list)
    """Tasks we would need to run before we could answer this well."""

    what_would_change_this: list[str] = Field(default_factory=list)
    """Concrete, honest next steps — never "try again later"."""


# ==========================================================================
# The engine
# ==========================================================================


@dataclass
class _Candidate:
    entry: ModelEntry
    results: list[tuple[TaskLeaderboard, ModelResult]] = field(default_factory=list)

    @property
    def evidence_score(self) -> float | None:
        """Sample-weighted mean of this model's scores on the matched tasks.

        Weighted by ``scored_count`` rather than a flat mean so a model measured
        on forty answers is not outvoted by one measured on two.
        """
        weighted = 0.0
        weight = 0
        for _, result in self.results:
            if result.mean_score is None or result.scored_count == 0:
                continue
            weighted += result.mean_score * result.scored_count
            weight += result.scored_count
        return weighted / weight if weight else None

    @property
    def has_verifiable_evidence(self) -> bool:
        return any(
            board.kind is TaskKind.VERIFIABLE and result.mean_score is not None
            for board, result in self.results
        )

    @property
    def scored_results(self) -> list[tuple[TaskLeaderboard, ModelResult]]:
        return [(b, r) for b, r in self.results if r.mean_score is not None]


def _cost_note(entry: ModelEntry, residency: str) -> CostNote:
    rates = entry.cost
    if rates.input_usd_per_mtok == 0 and rates.output_usd_per_mtok == 0:
        if residency == "on_campus":
            return CostNote(
                tier="campus_hosted",
                label="Free to you — runs on campus hardware",
                detail=(
                    "No per-use charge. The cost is the hardware the university already "
                    "owns, not a bill you receive."
                ),
                input_usd_per_mtok=0.0,
                output_usd_per_mtok=0.0,
            )
        return CostNote(
            tier="free",
            label="No per-token cost recorded",
            detail="The registry records no rates for this model.",
            input_usd_per_mtok=0.0,
            output_usd_per_mtok=0.0,
        )
    return CostNote(
        tier="paid",
        label=f"${rates.input_usd_per_mtok:.2f} in / ${rates.output_usd_per_mtok:.2f} out per million tokens",
        detail=(
            "A million tokens is roughly 700,000 words. For typical grading or item "
            "writing a professor's whole semester lands well inside a single-digit "
            "dollar figure — but check with your department before putting anything "
            "recurring on a card."
        ),
        input_usd_per_mtok=rates.input_usd_per_mtok,
        output_usd_per_mtok=rates.output_usd_per_mtok,
    )


def _resolve_surface(answers: dict[str, str], area: TaskArea, residency: str) -> tuple[str, str]:
    """Pick the surface and say why.

    An on-campus model is not reachable through a vendor's web chat, so a stated
    preference for "a website I type into" cannot be honoured for one — and
    silently returning ``chat_web`` anyway would be advice that does not work.
    """
    stated = answers.get("surface")
    if residency == "on_campus" and stated in (None, "", "unsure", "chat_web", "desktop_app"):
        return (
            "on_campus_chat",
            "This model runs on university hardware, so you reach it through the campus "
            "endpoint rather than a vendor's website. Ask the platform team for the URL.",
        )
    if stated in (None, "", "unsure"):
        return (
            area.default_surface,
            "You did not have a preference, so this is the simplest thing that works: "
            "no code, nothing to install.",
        )
    return (stated, "This is where you said you would use it.")


def _context_summary(answers: dict[str, str], areas: list[TaskArea]) -> list[ContextItem]:
    items: list[ContextItem] = []
    role = answers.get("role")
    if role:
        items.append(
            ContextItem(
                label="Role",
                value={
                    "teacher": "Teaching",
                    "researcher": "Research",
                    "both": "Teaching and research",
                }.get(role, role),
            )
        )
    if areas:
        items.append(ContextItem(label="Task", value=", ".join(a.label for a in areas)))
    if answers.get("beneficiary"):
        items.append(
            ContextItem(
                label="Who uses it",
                value={
                    "for_me": "You",
                    "for_students": "Your students",
                    "both": "You and your students",
                }.get(answers["beneficiary"], answers["beneficiary"]),
            )
        )
    if answers.get("subject_level"):
        items.append(
            ContextItem(
                label="Level",
                value=LEVEL_LABEL.get(answers["subject_level"], answers["subject_level"]),
            )
        )
    if answers.get("student_data"):
        items.append(
            ContextItem(
                label="Student data",
                value={"yes": "Yes", "no": "No", "unsure": "Unsure — treated as yes"}.get(
                    answers["student_data"], answers["student_data"]
                ),
            )
        )
    if answers.get("stakes"):
        items.append(
            ContextItem(
                label="Stakes",
                value={
                    "high": "Serious — affects a grade of record",
                    "medium": "Moderate — you review the output",
                    "low": "Low",
                }.get(answers["stakes"], answers["stakes"]),
            )
        )
    if answers.get("budget"):
        items.append(
            ContextItem(
                label="Budget",
                value={
                    "free_or_local_only": "Free or campus-hosted only",
                    "modest_paid": "Small spend acceptable",
                    "department_budget": "Departmental budget",
                }.get(answers["budget"], answers["budget"]),
            )
        )
    return items


def _selected_areas(answers: dict[str, str]) -> list[TaskArea]:
    areas: list[TaskArea] = []
    for key in ("teaching_task", "research_task"):
        value = answers.get(key)
        if value and value in TASK_AREAS:
            areas.append(TASK_AREAS[value])
    return areas


def validate_answers(answers: dict[str, str]) -> list[str]:
    """Reject unknown question ids and unknown option values.

    Returned as a list of human-readable problems rather than raised, so the
    route can turn the whole set into one 422 instead of one per round trip.
    """
    problems: list[str] = []
    for question_id, value in answers.items():
        question = QUESTIONS_BY_ID.get(question_id)
        if question is None:
            problems.append(f"unknown question {question_id!r}")
            continue
        if value in ("", None):
            continue
        if value not in {option.value for option in question.options}:
            problems.append(f"{value!r} is not an option for question {question_id!r}")
    return problems


def evaluate(
    answers: dict[str, str],
    *,
    boards: list[TaskLeaderboard],
    registry: list[ModelEntry],
) -> RecommendationResponse:
    """Turn intake answers plus benchmark data into a recommendation, or a refusal.

    Read top to bottom: each block is one reason we might not answer, in the
    order the reasons become knowable.
    """
    answers = {k: v for k, v in answers.items() if v not in (None, "")}
    areas = _selected_areas(answers)
    summary = _context_summary(answers, areas)

    # ── 1. do we know enough to even look? ──────────────────────────────────
    gaps = [
        Gap(question_id=q.id, prompt=q.prompt, why_it_matters=q.why_it_matters)
        for q in applicable_questions(answers)
        if q.required and not answers.get(q.id)
    ]
    if gaps:
        return RecommendationResponse(
            status="need_more_context",
            message=(
                "I can't answer this well yet — a recommendation built on a guess about "
                f"your situation is worth nothing. I still need {len(gaps)} thing(s):"
            ),
            context_summary=summary,
            gaps=gaps,
            what_would_change_this=["Answer the questions above and ask again."],
        )

    # ── 2. what did they tell us that narrows the field? ────────────────────
    constraints: list[Constraint] = []
    require_on_campus = False
    require_free = False

    student_data = answers.get("student_data")
    ferpa = answers.get("ferpa_hard_requirement")
    if student_data in ("yes", "unsure"):
        if ferpa in ("yes", "unsure"):
            require_on_campus = True
            constraints.append(
                Constraint(
                    label="Student data must stay on campus",
                    detail=(
                        "You told us student work is involved and that it cannot leave "
                        "campus"
                        + (
                            " — and where you were unsure, we treated that as a yes, "
                            "because the cautious reading is the only safe default with "
                            "FERPA."
                            if ferpa == "unsure" or student_data == "unsure"
                            else "."
                        )
                        + " Cloud models are excluded outright, however well they score."
                    ),
                    hard=True,
                )
            )
        else:
            constraints.append(
                Constraint(
                    label="Student data, de-identified first",
                    detail=(
                        "You remove identifiers before pasting anything. That makes a "
                        "cloud model possible, but de-identification has to actually "
                        "happen every time — a campus-hosted model removes that step, "
                        "and the risk of forgetting it."
                    ),
                    hard=False,
                )
            )

    if answers.get("unpublished_data") == "yes":
        constraints.append(
            Constraint(
                label="Unpublished research data",
                detail=(
                    "Some vendors' terms permit training on what you send. We weight "
                    "campus-hosted models up for unpublished work, for the same reason "
                    "we do for student data."
                ),
                hard=False,
            )
        )

    if answers.get("budget") == "free_or_local_only":
        require_free = True
        constraints.append(
            Constraint(
                label="No per-use cost",
                detail="Only models with no per-token charge are considered.",
                hard=True,
            )
        )

    if answers.get("stakes") == "high":
        constraints.append(
            Constraint(
                label="Serious consequences if it is wrong",
                detail=(
                    "For a use this consequential we only recommend where a program — "
                    "not another AI — checked the answers. An AI-judged score is not "
                    "enough to put behind a grade of record."
                ),
                hard=True,
            )
        )

    # ── 3. which models survive the hard constraints? ───────────────────────
    eligible: list[ModelEntry] = []
    for entry in registry:
        tags = {t.lower() for t in entry.tags}
        if tags & NOT_REAL_MODEL_TAGS:
            continue  # never recommend a deterministic echo stub
        if not entry.enabled:
            continue
        if require_on_campus and not (tags & ON_CAMPUS_TAGS):
            continue
        if require_free and (entry.cost.input_usd_per_mtok or entry.cost.output_usd_per_mtok):
            continue
        eligible.append(entry)

    if not eligible:
        blockers = []
        if require_on_campus:
            blockers.append("no model that runs on campus hardware is available to run today")
        if require_free:
            blockers.append("no free model is available today")
        return RecommendationResponse(
            status="no_eligible_model",
            message=(
                "I understood your situation, and I am not going to recommend anything: "
                + " and ".join(blockers or ["no model in the registry is currently enabled"])
                + ". Offering you a model that breaks a requirement you just stated "
                "would be worse than offering you nothing."
            ),
            context_summary=summary,
            constraints=constraints,
            what_would_change_this=[
                "Stand up the campus vLLM deployment — it is registered but not yet enabled, "
                "and it is the model this recommendation is waiting on."
                if require_on_campus
                else "Enable a model in the registry that meets these constraints.",
                "If the requirement is softer than stated — for example you de-identify "
                "student work before pasting it — change that answer and ask again.",
            ],
        )

    # ── 4. is there benchmark evidence for what they asked about? ───────────
    if not areas:
        return RecommendationResponse(
            status="need_more_context",
            message="I need to know what you want help with before I can look anything up.",
            context_summary=summary,
            gaps=[
                Gap(
                    question_id="teaching_task",
                    prompt=QUESTIONS_BY_ID["teaching_task"].prompt,
                    why_it_matters=QUESTIONS_BY_ID["teaching_task"].why_it_matters,
                )
            ],
        )

    matched_ids: list[str] = []
    for area in areas:
        for task_id in matched_task_ids(area, boards):
            if task_id not in matched_ids:
                matched_ids.append(task_id)
    boards_by_id = {b.task_id: b for b in boards}

    candidates: list[_Candidate] = []
    for entry in eligible:
        candidate = _Candidate(entry=entry)
        for task_id in matched_ids:
            board = boards_by_id[task_id]
            for result in board.results:
                if result.model_key == entry.key:
                    candidate.results.append((board, result))
        candidates.append(candidate)

    with_evidence = [c for c in candidates if c.scored_results]

    if answers.get("stakes") == "high":
        with_evidence = [c for c in with_evidence if c.has_verifiable_evidence]

    if not with_evidence:
        measured_here = {
            task_id
            for task_id in matched_ids
            if any(r.mean_score is not None for r in boards_by_id[task_id].results)
        }
        unmeasured = [t for t in matched_ids if t not in measured_here]
        high_stakes = answers.get("stakes") == "high"
        return RecommendationResponse(
            status="insufficient_evidence",
            message=(
                (
                    "I won't recommend a model for something this consequential on "
                    "AI-judged evidence alone. We have not yet measured any eligible "
                    "model on a program-checked task that resembles what you described."
                )
                if high_stakes
                else (
                    "I understood your situation, but this platform has not benchmarked "
                    "any eligible model on a task resembling "
                    + " or ".join(a.label.lower() for a in areas)
                    + " yet. I'm not going to guess — a recommendation with no evidence "
                    "behind it is exactly what this project exists to replace."
                )
            ),
            context_summary=summary,
            constraints=constraints,
            matched_task_ids=matched_ids,
            missing_benchmarks=unmeasured or matched_ids,
            what_would_change_this=(
                [
                    "Run the benchmark for these tasks: " + ", ".join(unmeasured[:8])
                    if unmeasured
                    else "Author a task family covering "
                    + " / ".join(a.label.lower() for a in areas)
                    + ", then benchmark it.",
                ]
                + (
                    [
                        "Or, if you review every output before it counts, change the "
                        "stakes answer — that lets AI-judged evidence back a suggestion."
                    ]
                    if high_stakes
                    else []
                )
            ),
        )

    # ── 5. rank, and build the package ──────────────────────────────────────
    prefer_on_campus = (
        require_on_campus
        or answers.get("unpublished_data") == "yes"
        or student_data in ("yes", "unsure")
    )

    def rank_key(candidate: _Candidate) -> tuple:
        score = candidate.evidence_score or 0.0
        residency_bonus = (
            1
            if prefer_on_campus
            and any(
                t.lower() in {"local", "campus", "on-prem", "self-hosted"}
                for t in candidate.entry.tags
            )
            else 0
        )
        return (-residency_bonus, -score, candidate.entry.key)

    with_evidence.sort(key=rank_key)
    packaged = [
        _package(candidate, answers, areas, constraints, prefer_on_campus)
        for candidate in with_evidence
    ]
    primary = packaged[0]
    alternatives = packaged[1:3]

    return RecommendationResponse(
        status="ok",
        message=(
            f"Based on {sum(len(c.scored_results) for c in with_evidence)} measured "
            f"result(s) on benchmark tasks matching what you described "
            f"({len(matched_ids)} such task(s) exist; not all have been run yet), "
            "here is what I would use — and the evidence behind it."
        ),
        context_summary=summary,
        constraints=constraints,
        primary=primary,
        alternatives=alternatives,
        matched_task_ids=matched_ids,
        missing_benchmarks=[
            t
            for t in matched_ids
            if not any(r.mean_score is not None for r in boards_by_id[t].results)
        ],
        what_would_change_this=[
            "Open any receipt below to read the actual transcripts, the scorer that "
            "produced the number, and the exact serving configuration.",
            "If your situation is different from the summary above, change the answer "
            "and ask again — several of these answers change the recommendation.",
        ],
    )


def _package(
    candidate: _Candidate,
    answers: dict[str, str],
    areas: list[TaskArea],
    constraints: list[Constraint],
    prefer_on_campus: bool,
) -> Recommendation:
    entry = candidate.entry
    residency = data_residency(entry)
    area = areas[0]
    level = LEVEL_LABEL.get(answers.get("subject_level", ""), "undergraduate")
    # A BRACKETED PLACEHOLDER, NOT THE TASK LABEL. We ask what LEVEL a professor
    # teaches at, never which subject -- and substituting the task label
    # produced "students in writing quiz or exam items", a sentence that reads
    # like the template was generated by something that was not paying
    # attention. The professor fills this in; everything else is already filled.
    subject = "[your subject]"
    surface, surface_rationale = _resolve_surface(answers, area, residency)

    receipts = [
        Receipt(
            task_id=board.task_id,
            task_title=board.title,
            task_kind=board.kind,
            model_key=result.model_key,
            run_id=result.run_id,
            mean_score=result.mean_score,
            scored_count=result.scored_count,
            sample_count=result.sample_count,
            confidence=result.trust.confidence,
            trust_label=result.trust.tier_label,
        )
        for board, result in sorted(
            candidate.scored_results, key=lambda pair: -(pair[1].mean_score or 0.0)
        )
    ]

    why: list[str] = []
    best = receipts[0] if receipts else None
    if best is not None and best.mean_score is not None:
        why.append(
            f"It scored {best.mean_score:.2f} on “{best.task_title}” "
            f"({best.scored_count} of {best.sample_count} samples scored) — "
            + (
                "a program checked those answers against a key, so no AI judged this number."
                if best.task_kind is TaskKind.VERIFIABLE
                else "graded by an AI judge against a written rubric, which is a second opinion rather than a measurement."
            )
        )
    if len(receipts) > 1:
        why.append(
            f"The same pattern holds across {len(receipts)} benchmark tasks matching what "
            "you described, not one lucky result."
        )
    if residency == "on_campus":
        why.append(
            "It runs on university hardware, so nothing you paste ever reaches a third "
            "party — the reason we can put it in front of student work at all."
        )
    elif prefer_on_campus:
        why.append(
            "⚠ This is a third-party hosted model. It is here because no campus-hosted "
            "model qualified, and it means anything you paste leaves the university."
        )

    caveats: list[str] = []
    seen: set[str] = set()
    for _, result in candidate.scored_results:
        for caveat in result.trust.caveats:
            if caveat not in seen:
                seen.add(caveat)
                caveats.append(caveat)
    if "testing-only" in {t.lower() for t in entry.tags}:
        caveats.append(
            "This registry entry is flagged testing-only and runs under a spend cap. "
            "Treat it as an evaluation endpoint, not a departmental rollout."
        )
    if candidate.evidence_score is not None and candidate.evidence_score < 0.6:
        caveats.append(
            f"Its own best score here is {candidate.evidence_score:.2f}. That is what "
            "the evidence says — we are showing you the best measured option, not a good one."
        )

    guardrails: list[str] = []
    if answers.get("beneficiary") in ("for_students", "both"):
        guardrails.extend(area.student_facing_guardrails)
        guardrails.append(
            "Anything students use should be introduced with what it is for and what it "
            "is not for — an unexplained tool is the version that becomes a shortcut."
        )
    if answers.get("stakes") == "high":
        guardrails.append(
            "You said a mistake here is serious: review every output before it counts. "
            "Nothing in this benchmark supports leaving it unsupervised."
        )

    return Recommendation(
        model_key=entry.key,
        display_name=entry.display_name,
        headline=f"Use {entry.display_name} for {area.label.lower()}",
        why=why,
        surface=surface,
        surface_label=SURFACE_LABEL.get(surface, surface),
        surface_rationale=surface_rationale,
        cost=_cost_note(entry, residency),
        data_residency=residency,
        data_residency_label=RESIDENCY_LABEL[residency],
        prompt_template=area.prompt_template.format(level=level, subject=subject, n=5),
        guardrails=guardrails,
        caveats=caveats,
        receipts=receipts,
        evidence_score=candidate.evidence_score,
        verifiable_evidence=candidate.has_verifiable_evidence,
    )
