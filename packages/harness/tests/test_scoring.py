"""Tests for the three deterministic rubric kinds.

These are cheap and they gate a real invariant: the schema in tasks/SCHEMA.md
PROMISES particular scoring semantics, and a rubric author reading that doc has
no other way to know the code agrees with it.
"""

import pytest

from ida_harness.scoring import JudgeScoringUnavailable, score_response


class TestExact:
    def test_matches_ignoring_case_by_default(self):
        assert score_response({"kind": "exact"}, "Paris", "  paris ") == 1.0

    def test_case_sensitive_when_asked(self):
        rubric = {"kind": "exact", "case_sensitive": True}
        assert score_response(rubric, "Paris", "paris") == 0.0
        assert score_response(rubric, "Paris", "Paris") == 1.0

    def test_wrong_answer_scores_zero(self):
        assert score_response({"kind": "exact"}, "Paris", "London") == 0.0


class TestContains:
    def test_any_match_scores_one(self):
        rubric = {"kind": "contains", "any_of": ["scattering", "Rayleigh"]}
        assert score_response(rubric, None, "It is due to RAYLEIGH effects.") == 1.0

    def test_no_match_scores_zero(self):
        rubric = {"kind": "contains", "any_of": ["scattering"]}
        assert score_response(rubric, None, "Because the ocean reflects.") == 0.0


class TestNumeric:
    def test_within_tolerance(self):
        assert score_response({"kind": "numeric", "tolerance": 0.5}, 42, "41.8") == 1.0

    def test_outside_tolerance(self):
        assert score_response({"kind": "numeric", "tolerance": 0.5}, 42, "45") == 0.0

    def test_zero_tolerance_is_exact(self):
        rubric = {"kind": "numeric", "tolerance": 0}
        assert score_response(rubric, 42, "42") == 1.0
        assert score_response(rubric, 42, "42.0001") == 0.0

    def test_non_numeric_response_scores_zero_rather_than_raising(self):
        # A garbage reply is a WRONG ANSWER, not a harness error. Raising here
        # would abort an entire suite because one model rambled.
        assert score_response({"kind": "numeric", "tolerance": 0}, 42, "forty-two") == 0.0


def test_judge_refuses_rather_than_inventing_a_number():
    # The important negative test. A scorer that returned a plausible float for a
    # judge rubric without asking a model would poison every stored result.
    with pytest.raises(JudgeScoringUnavailable):
        score_response({"kind": "judge", "judge_model": "mock-echo"}, None, "anything")


def test_unknown_kind_is_an_error():
    with pytest.raises(ValueError, match="unknown rubric kind"):
        score_response({"kind": "vibes"}, None, "x")
