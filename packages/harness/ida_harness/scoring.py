"""Scorers: completion + gold answer -> :class:`~ida_core.contracts.Score`.

Design rules, in priority order:

1. **A scorer never raises for a bad completion.**  A model that answers
   "I don't know" gets ``value=0.0`` with an explanation, not an exception.
   Exceptions are reserved for *our* bugs (misconfigured scorer).
2. **Normalisation is per-task, explicit, and symmetric.**  See
   :class:`~ida_core.contracts.Normalisation`.  Nothing is stripped, lowered or
   collapsed unless the task said so -- and whatever is done to the completion
   is done to the target too.  An asymmetric comparison silently marks correct
   answers wrong, which in a benchmarking platform is data corruption that
   propagates all the way into a recommendation.
3. **A bad JUDGE response is never turned into a score.**  The converse of
   rule 1, and it lives in :mod:`ida_harness.judge`: a judge that returns
   garbage, or a score outside the rubric's scale, degrades that sample with an
   honest error.  Nothing is clamped or defaulted into a grade.
4. **``explanation`` shows the compared values.**  A reviewer reading the UI
   must be able to see *why* a sample failed without opening the transcript.
"""

from __future__ import annotations

import re
import string
from typing import Protocol, runtime_checkable

from ida_core.contracts import (
    Normalisation,
    Score,
    ScorerKind,
    ScorerSpec,
    TaskSample,
    TaskSpec,
)
from ida_harness.errors import ScoringError
from ida_harness.judge import JudgeVerdict, LLMJudge

_WHITESPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def normalise(text: str, rules: Normalisation) -> str:
    """Apply a task's normalisation rules, in a fixed order.

    Order matters and is part of the contract:
    ``take_last_line`` -> ``strip`` -> ``collapse_whitespace`` ->
    ``strip_punctuation`` -> ``lowercase``.  Taking the last line first is what
    lets a chain-of-thought answer be graded on its conclusion.
    """
    out = text
    if rules.take_last_line:
        lines = [ln for ln in out.splitlines() if ln.strip()]
        out = lines[-1] if lines else ""
    if rules.strip:
        out = out.strip()
    if rules.collapse_whitespace:
        out = _WHITESPACE.sub(" ", out).strip()
    if rules.strip_punctuation:
        out = out.translate(str.maketrans("", "", string.punctuation))
        if rules.collapse_whitespace:
            out = _WHITESPACE.sub(" ", out).strip()
    if rules.lowercase:
        out = out.lower()
    return out


def extract_number(text: str) -> float | None:
    """Pull the **last** number out of ``text``; ``None`` if there is none.

    Last, not first: models restate the question before answering, so the first
    number is usually an input.  Thousands separators are handled; currency
    symbols and units are ignored by virtue of the regex only matching digits.
    """
    matches = _NUMBER.findall(text)
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", ""))
    except ValueError:  # pragma: no cover - regex guarantees parseability
        return None


@runtime_checkable
class Scorer(Protocol):
    """The scorer interface.  Implement this to add a scoring strategy.

    A scorer is constructed from a :class:`~ida_core.contracts.ScorerSpec` (its
    task-level configuration) and then called once per sample.
    """

    kind: ScorerKind

    def score(self, completion: str, target: str | None) -> Score:
        """Grade one completion.  Must not raise for ordinary bad output."""


class ExactMatchScorer:
    """String equality after the task's normalisation.

    ``value`` is 1.0 or 0.0 -- there is no partial credit, by design.  A task
    that wants partial credit is a ``subjective`` task with a rubric.
    """

    kind = ScorerKind.EXACT_MATCH

    def __init__(self, spec: ScorerSpec) -> None:
        self._rules = spec.normalisation

    def score(self, completion: str, target: str | None) -> Score:
        if target is None:
            raise ScoringError("exact_match requires a target; task validation should prevent this")
        got = normalise(completion, self._rules)
        want = normalise(target, self._rules)
        passed = got == want
        return Score(
            scorer=self.kind,
            value=1.0 if passed else 0.0,
            passed=passed,
            explanation=(
                f"exact match: got {got!r}, want {want!r}"
                if not passed
                else f"exact match: {got!r}"
            ),
            details={"normalised_completion": got, "normalised_target": want},
        )


class NumericMatchScorer:
    """Compare the last number in the completion to the target, within tolerance.

    Passes when ``|got - want| <= tolerance`` **or**
    ``|got - want| <= relative_tolerance * |want|``.  Both default to 0, i.e.
    exact numeric equality, so a task must opt in to slack.

    A completion containing no number scores 0.0 with an explanation -- that is
    a model failure, not a harness failure (rule 1 in the module docstring).
    """

    kind = ScorerKind.NUMERIC_MATCH

    def __init__(self, spec: ScorerSpec) -> None:
        self._rules = spec.normalisation
        self._tolerance = spec.tolerance
        self._relative_tolerance = spec.relative_tolerance

    def score(self, completion: str, target: str | None) -> Score:
        if target is None:
            raise ScoringError(
                "numeric_match requires a target; task validation should prevent this"
            )
        # BOTH sides get the same normalisation (B3). Previously only the
        # completion was normalised, so a task's rules could shift one side of
        # the comparison and not the other -- while ExactMatchScorer, three
        # classes up, normalises both. Two scorers that look alike must behave
        # alike. (ScorerSpec independently forbids strip_punctuation here,
        # because '.' and ',' are numerically significant.)
        got_text = normalise(completion, self._rules)
        want_text = normalise(target, self._rules)
        got = extract_number(got_text)
        want = extract_number(want_text)
        if want is None:
            raise ScoringError(
                f"numeric_match target {target!r} contains no number (normalised to {want_text!r})"
            )

        if got is None:
            return Score(
                scorer=self.kind,
                value=0.0,
                passed=False,
                explanation=f"no number found in completion {got_text[:120]!r}; want {want}",
                details={"target": want, "extracted": None},
            )

        delta = abs(got - want)
        allowance = max(self._tolerance, self._relative_tolerance * abs(want))
        passed = delta <= allowance
        return Score(
            scorer=self.kind,
            value=1.0 if passed else 0.0,
            passed=passed,
            explanation=(
                f"numeric match: got {got}, want {want} (|delta|={delta:g}, allowed={allowance:g})"
            ),
            details={
                "target": want,
                "extracted": got,
                "delta": delta,
                "allowance": allowance,
            },
        )


class LLMJudgeScorer:
    """Rubric-graded scoring by a judge model, bound to **one sample**.

    Why binding, and why it is not a wart
    -------------------------------------
    A programmatic scorer is a function of ``(completion, target)`` and nothing
    else.  A rubric judgment is not: it is a function of the completion, the
    prompt the completion was answering, and the rubric.  Rather than widen the
    :class:`Scorer` protocol -- which would force every scorer to accept context
    two of the three do not use -- the judge scorer takes its context at
    construction, so ``score(completion, target)`` still means exactly what it
    means everywhere else.  ``target`` is always ``None`` here (subjective tasks
    forbid targets, enforced on :class:`~ida_core.contracts.TaskSpec`) and is
    accepted only to satisfy the protocol.

    Two ways in, one implementation
    -------------------------------
    :meth:`grade` returns the full :class:`~ida_harness.judge.JudgeVerdict` --
    score *plus* the judge's token usage, cost and transcript.  That is what
    :func:`ida_harness.runner.run_task` uses, because a grade that costs money
    has to be accounted for.  :meth:`score` is the protocol-shaped view for
    callers that only want the number, and raises
    :class:`~ida_harness.errors.ScoringError` when the judge could not produce
    one -- there is no fallback score, by design.

    Constructed with no judge (``build_scorer(spec)``, the API's validation
    path), it is inert and says so when called.  That keeps a task whose scorer
    is ``llm_judge`` loadable and validatable on a deployment that has no judge
    configured, which is the state the platform ships in.
    """

    kind = ScorerKind.LLM_JUDGE

    def __init__(
        self,
        spec: ScorerSpec,
        *,
        judge: LLMJudge | None = None,
        task: TaskSpec | None = None,
        sample: TaskSample | None = None,
        run_id: str | None = None,
    ) -> None:
        self._spec = spec
        self._judge = judge
        self._task = task
        self._sample = sample
        self._run_id = run_id

    @property
    def is_bound(self) -> bool:
        """True when this scorer has everything it needs to actually grade."""
        return self._judge is not None and self._task is not None and self._sample is not None

    def grade(self, completion: str) -> JudgeVerdict:
        """Grade ``completion``, returning score **and** accounting.

        Raises :class:`~ida_harness.errors.ScoringError` only when this scorer
        was never bound to a judge -- that is a programming error.  A judge that
        fails or answers unusably comes back as a verdict with ``score=None``
        and an ``error``, never as an exception.
        """
        if not self.is_bound:
            raise ScoringError(
                "llm_judge scoring needs a judge model, a task and a sample; this scorer "
                "was built without them. Pass judge=/task=/sample= to build_scorer, or "
                "give run_task a judge= (see ida_harness.judge.build_judge)."
            )
        assert self._judge is not None and self._task is not None  # noqa: S101 - is_bound
        assert self._sample is not None  # noqa: S101 - is_bound
        return self._judge.grade(
            task=self._task, sample=self._sample, completion=completion, run_id=self._run_id
        )

    def score(self, completion: str, target: str | None = None) -> Score:
        """:class:`Scorer`-protocol view.  ``target`` is unused and must be ``None``.

        Discards the judge's usage and cost, so it is the wrong entry point for
        anything that persists a result -- use :meth:`grade` there.
        """
        if target is not None:
            raise ScoringError(
                f"llm_judge scored a sample carrying target {target!r}; subjective tasks "
                "must not have targets and TaskSpec validation should have caught this"
            )
        verdict = self.grade(completion)
        if verdict.score is None:
            raise ScoringError(verdict.error or "the judge produced no score")
        return verdict.score


_SCORERS: dict[ScorerKind, type] = {
    ScorerKind.EXACT_MATCH: ExactMatchScorer,
    ScorerKind.NUMERIC_MATCH: NumericMatchScorer,
    ScorerKind.LLM_JUDGE: LLMJudgeScorer,
}


def build_scorer(
    spec: ScorerSpec,
    *,
    judge: LLMJudge | None = None,
    task: TaskSpec | None = None,
    sample: TaskSample | None = None,
    run_id: str | None = None,
) -> Scorer:
    """Construct the scorer a task asked for.

    The keyword arguments are the judge's binding context and are ignored by the
    programmatic scorers, which genuinely do not need them -- passing them to a
    ``numeric_match`` task is harmless rather than an error, so a caller does not
    have to branch on scorer kind before building one.

    Raises :class:`~ida_harness.errors.ScoringError` for an unknown kind --
    unreachable via validated task files, reachable if someone constructs a
    ``ScorerSpec`` by hand.
    """
    try:
        cls = _SCORERS[spec.kind]
    except KeyError:
        raise ScoringError(f"no scorer registered for kind {spec.kind!r}") from None
    if cls is LLMJudgeScorer:
        return LLMJudgeScorer(spec, judge=judge, task=task, sample=sample, run_id=run_id)
    return cls(spec)
