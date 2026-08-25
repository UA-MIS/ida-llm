"""Rubric scoring.

Three of the four rubric kinds are implemented here and they are deliberately
boring -- deterministic, dependency-free, and unit-tested. `judge` is not
implemented: it requires a model call, so it belongs to the runner's judge code
path, and stubbing it with a plausible-looking number here would be the worst
possible outcome (a scorer that returns a value nobody asked a model for).
"""

from __future__ import annotations

from typing import Any


class JudgeScoringUnavailable(NotImplementedError):
    """Raised when judge scoring is attempted without a model-backed judge."""


def score_response(rubric: dict[str, Any], gold: Any, response: str) -> float:
    """Score a model response against a rubric. Returns a float in [0.0, 1.0]."""
    kind = rubric.get("kind")

    if kind == "exact":
        expected = str(gold)
        actual = response.strip()
        if not rubric.get("case_sensitive", False):
            expected, actual = expected.casefold(), actual.casefold()
        return 1.0 if actual == expected.strip() else 0.0

    if kind == "contains":
        haystack = response.casefold()
        return 1.0 if any(str(n).casefold() in haystack for n in rubric["any_of"]) else 0.0

    if kind == "numeric":
        try:
            actual_value = float(response.strip())
        except (TypeError, ValueError):
            # A non-numeric answer to a numeric task scores 0 -- it is wrong, not
            # an error. Raising here would abort a whole suite on one bad reply.
            return 0.0
        return 1.0 if abs(actual_value - float(gold)) <= float(rubric["tolerance"]) else 0.0

    if kind == "judge":
        raise JudgeScoringUnavailable(
            "judge rubrics are scored by a model, not by this function -- "
            "call the runner's judge path with the rubric's judge_model"
        )

    raise ValueError(f"unknown rubric kind: {kind!r}")
