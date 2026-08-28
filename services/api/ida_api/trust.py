"""The trust tell: how much a single benchmark number is worth.

This module exists because of the one sentence the whole project stands on --
*"we can say accurate honestly"* -- and because a score of ``0.91`` printed
without qualification is not an honest sentence.  Two numbers on the results
page can look identical and mean completely different things:

- ``0.91`` on a **verifiable** task means a *program* compared the model's
  answer to a gold answer.  Nothing judged anything; the number is a count.
- ``0.91`` on a **subjective** task means *another language model* graded the
  answer against a rubric.  That is evidence, but it is evidence of a kind a
  professor should weight differently -- and it is exactly the kind a skeptical
  professor is right to weight differently.

``docs/Methodology/Verifiable vs. subjective.md`` draws that line for the
platform.  This module is that line rendered: every score the UI shows carries a
:class:`TrustTell` saying which kind it is, how confident we are, and -- when we
are not confident -- *why not*, in words a non-technical reader can act on.

**The rule the confidence tiers encode.** Confidence is never an opinion about
the model.  It is a statement about the *measurement*: what kind of scorer ran,
how many samples it actually scored, and whether anything failed along the way.
A high-scoring model measured on two samples gets ``low``; that is the point.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ida_core.contracts import TaskKind

Confidence = Literal["high", "moderate", "low", "none"]

VERIFIABLE_HIGH_CONFIDENCE_SAMPLES = 5
"""Scored samples a verifiable task needs before we call the number ``high``.

Five is the sample count `tasks/SCHEMA.md` recommends per task ("enough that one
lucky guess does not read as competence"), so the bar is the authoring
convention rather than a number invented here.  Below it the score is still
shown -- hiding a real measurement would be its own dishonesty -- but it is
labelled for what it is: a thin one.
"""

SUBJECTIVE_MODERATE_CONFIDENCE_SAMPLES = 5
"""A judged task cannot reach ``high`` at all -- see :func:`assess`."""


class TrustTell(BaseModel):
    """How to read one number, attached to the number itself.

    Deliberately not a bare enum.  A badge alone ("subjective") tells a
    professor a fact about our taxonomy; what they need is what to *do* with the
    number, which is what :attr:`headline` and :attr:`caveats` carry.
    """

    model_config = ConfigDict(extra="forbid")

    kind: TaskKind
    """Which side of the taxonomy produced this score."""

    scorer: str
    """The scorer that actually ran: ``exact_match``, ``numeric_match``, ``llm_judge``."""

    tier_label: str
    """The badge text.  Short enough to sit next to a number."""

    headline: str
    """One sentence: what kind of evidence this is."""

    confidence: Confidence
    """How much this particular measurement supports its number."""

    confidence_label: str
    """The confidence badge text."""

    confidence_reason: str
    """Why that tier -- always about the measurement, never about the model."""

    caveats: list[str] = []
    """Everything a reader should know before repeating this number."""


def _verifiable_headline(scorer: str) -> str:
    return (
        "Verifiable — a program compared the model's answer to a known correct "
        f"answer ({scorer}). No AI judged this score."
    )


SUBJECTIVE_HEADLINE = (
    "Subjective — there is no single correct answer, so another language model "
    "graded this against a written rubric. Treat it as an informed second "
    "opinion, not a measurement."
)


def assess(
    *,
    kind: TaskKind,
    scorer: str,
    scorable: bool,
    unscorable_reason: str | None,
    mean_score: float | None,
    scored_count: int,
    sample_count: int,
    error_count: int,
) -> TrustTell:
    """Classify one (task, model) measurement.

    Every branch below answers the same question -- *how much does this number
    support itself?* -- and none of them looks at how high the score is.  A
    ``1.00`` measured on one sample and a ``0.30`` measured on forty get their
    confidence from the sample counts, not from the values.
    """
    tier_label = "Verifiable" if kind is TaskKind.VERIFIABLE else "Subjective (AI-scored)"
    headline = _verifiable_headline(scorer) if kind is TaskKind.VERIFIABLE else SUBJECTIVE_HEADLINE
    caveats: list[str] = []

    # ── is there a number at all? ───────────────────────────────────────────
    #
    # ⚠ THE ABSENCE OF A SCORE IS TESTED FIRST, AND `scorable` IS NOT ALLOWED TO
    # OVERRIDE A SCORE THAT EXISTS. This ordering was wrong once and the result
    # was visible on the results page: a run carrying `mean_score: 0.86` rendered
    # the number AND the sentence "No score exists for this pair", because
    # `scorable` was checked first and short-circuited.
    #
    # `scorable` is a property of the TASK AND THIS DEPLOYMENT (a subjective task
    # is unscorable while no judge model is configured), not of the run. So it
    # can be False for a run that was genuinely scored when a judge WAS
    # configured, or that was graded retroactively (see ida_harness.regrade). The
    # run's own number is the fact; `scorable` is context about it, and context
    # never gets to contradict the fact -- it becomes a caveat instead.
    #
    # Three different things produce a MISSING score, and a UI that shows one
    # em-dash for all three teaches the reader that a blank means nothing in
    # particular. Each gets its own sentence.
    if mean_score is None or scored_count == 0:
        if not scorable:
            reason = (
                unscorable_reason
                or "This task cannot be scored yet, so there is no number to trust."
            )
        elif error_count > 0:
            reason = (
                f"Every one of the {error_count} attempted sample(s) failed before it could "
                "be scored, so nothing was measured here."
            )
        else:
            reason = "No sample of this task has been scored for this model yet."
        return TrustTell(
            kind=kind,
            scorer=scorer,
            tier_label=tier_label,
            headline=headline,
            confidence="none",
            confidence_label="Not scored",
            confidence_reason=reason,
            caveats=["No score exists for this pair — this is not a score of zero."],
        )

    # ── a score exists on a task the platform calls unscorable today ────────
    #
    # Not a contradiction to hide: the run really was graded, and the task
    # really cannot be graded right now. Saying both is the only honest option,
    # and it tells a reader why re-running would NOT reproduce this number.
    if not scorable:
        caveats.append(
            "This run carries a score, but the platform cannot grade this task today"
            + (f" ({unscorable_reason})" if unscorable_reason else "")
            + " — the score was produced when grading was available. Re-running now "
            "would not reproduce it."
        )

    # ── a partial measurement is a real caveat, on either side ──────────────
    if error_count > 0:
        caveats.append(
            f"{error_count} of {sample_count} sample(s) failed and are excluded from this "
            "average — they are not counted as wrong, so the score covers only part of "
            "the task."
        )
    if scored_count < sample_count and error_count == 0:
        caveats.append(f"Only {scored_count} of {sample_count} sample(s) carry a score.")

    if kind is TaskKind.VERIFIABLE:
        if scored_count >= VERIFIABLE_HIGH_CONFIDENCE_SAMPLES and error_count == 0:
            confidence: Confidence = "high"
            confidence_label = "High confidence"
            confidence_reason = (
                f"A program checked {scored_count} answers against a gold key and all "
                "of them completed. There is no judgement call in this number."
            )
        elif scored_count >= VERIFIABLE_HIGH_CONFIDENCE_SAMPLES:
            confidence = "moderate"
            confidence_label = "Moderate confidence"
            confidence_reason = (
                f"Checked against a gold key on {scored_count} answers, but "
                f"{error_count} sample(s) failed, so this covers part of the task."
            )
        else:
            confidence = "low"
            confidence_label = "Low confidence — thin evidence"
            confidence_reason = (
                f"Only {scored_count} answer(s) were scored. The check itself is exact, "
                "but that is too few samples to separate skill from luck."
            )
    else:
        # A judged score never reaches `high`, however many samples there are.
        # More samples reduce sampling noise; they do nothing about the fact
        # that the grader is a language model whose agreement with real
        # professors is a number this project has not yet measured. Promoting a
        # judged score to `high` on volume alone would be the single most
        # misleading thing this page could do.
        caveats.append(
            "Scored by an AI judge, not by a professor. We have not yet measured how "
            "well this judge agrees with human graders on this task."
        )
        if scored_count >= SUBJECTIVE_MODERATE_CONFIDENCE_SAMPLES and error_count == 0:
            confidence = "moderate"
            confidence_label = "Moderate confidence"
            confidence_reason = (
                f"An AI judge graded {scored_count} answers against a written rubric. "
                "Rubric grading is reproducible, but it is still a judgement."
            )
        else:
            confidence = "low"
            confidence_label = "Low confidence — thin evidence"
            confidence_reason = (
                f"An AI judge graded only {scored_count} answer(s)"
                + (f", and {error_count} failed" if error_count else "")
                + ". Too thin to draw a conclusion from."
            )

    return TrustTell(
        kind=kind,
        scorer=scorer,
        tier_label=tier_label,
        headline=headline,
        confidence=confidence,
        confidence_label=confidence_label,
        confidence_reason=confidence_reason,
        caveats=caveats,
    )
