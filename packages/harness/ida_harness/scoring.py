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
3. **``explanation`` shows the compared values.**  A reviewer reading the UI
   must be able to see *why* a sample failed without opening the transcript.
"""

from __future__ import annotations

import re
import string
from typing import Protocol, runtime_checkable

from ida_core.contracts import Normalisation, Score, ScorerKind, ScorerSpec
from ida_harness.errors import ScoringError

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
    """Rubric-graded scoring by a judge model.  **Interface only in the skeleton.**

    Per **D-5** the judge is *not* a separate service: it is a code path inside
    the harness that calls another model through the same
    :class:`~ida_harness.client.OpenAICompatibleClient`.  When implemented it
    will:

    1. render the rubric + the sample input + the completion into a judge prompt,
    2. call the configured judge model with a structured-output constraint,
    3. map the per-criterion scores onto ``[0, 1]`` using the criterion weights,
    4. put the judge's own transcript in ``Score.details`` so the grade is
       traceable to evidence (D-3).

    Until then, tasks whose scorer is ``llm_judge`` are loaded, validated, and
    reported as **not yet scorable** (:attr:`ida_core.contracts.TaskSpec.is_scorable`
    is False); the runner records a :class:`~ida_core.contracts.ResultRecord`
    with ``scorable=False`` and ``score=None`` rather than calling this class.
    Calling :meth:`score` is therefore a programming error, and it says so.
    """

    kind = ScorerKind.LLM_JUDGE

    def __init__(self, spec: ScorerSpec) -> None:
        self._spec = spec

    def score(self, completion: str, target: str | None) -> Score:
        raise NotImplementedError(
            "LLM-as-judge scoring is not implemented in the walking skeleton. "
            "Subjective tasks are loaded and validated but recorded with "
            "scorable=False and score=None. See LLMJudgeScorer's docstring for "
            "the intended implementation."
        )


_SCORERS: dict[ScorerKind, type] = {
    ScorerKind.EXACT_MATCH: ExactMatchScorer,
    ScorerKind.NUMERIC_MATCH: NumericMatchScorer,
    ScorerKind.LLM_JUDGE: LLMJudgeScorer,
}


def build_scorer(spec: ScorerSpec) -> Scorer:
    """Construct the scorer a task asked for.

    Raises :class:`~ida_harness.errors.ScoringError` for an unknown kind --
    unreachable via validated task files, reachable if someone constructs a
    ``ScorerSpec`` by hand.
    """
    try:
        cls = _SCORERS[spec.kind]
    except KeyError:
        raise ScoringError(f"no scorer registered for kind {spec.kind!r}") from None
    return cls(spec)
