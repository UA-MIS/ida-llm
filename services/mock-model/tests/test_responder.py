"""Responder rules. Determinism is the property that makes the tracer bullet meaningful."""

from __future__ import annotations

import json

import pytest

from ida_mock_model.responder import (
    Responder,
    estimate_tokens,
    evaluate_arithmetic,
    format_number,
)


class TestEvaluateArithmetic:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("What is 17 + 25?", 42.0),
            ("What is 12 * 12?", 144.0),
            ("What is 12 x 12?", 144.0),
            ("What is 8 - 19?", -11.0),
            ("What is 7 / 2?", 3.5),
            ("7/2", 3.5),
            ("  3   +   4  ", 7.0),
            ("no arithmetic here", None),
            ("What is 1 / 0?", None),
        ],
    )
    def test_cases(self, text: str, expected: float | None) -> None:
        assert evaluate_arithmetic(text) == expected

    def test_does_not_execute_the_input(self) -> None:
        """The prompt is untrusted. eval() here would be an RCE, even in a mock."""
        assert evaluate_arithmetic("__import__('os').system('echo pwned')") is None

    def test_first_expression_wins(self) -> None:
        assert evaluate_arithmetic("2 + 2 and also 10 * 10") == 4.0


class TestFormatNumber:
    @pytest.mark.parametrize(
        "value,expected", [(42.0, "42"), (-11.0, "-11"), (3.5, "3.5"), (0.0, "0")]
    )
    def test_cases(self, value: float, expected: str) -> None:
        assert format_number(value) == expected


class TestResponder:
    def test_arithmetic_is_answered_correctly(self) -> None:
        assert Responder().answer("A quiz item reads: What is 17 + 25?") == "42"

    def test_is_deterministic(self) -> None:
        responder = Responder()
        assert responder.answer("tell me about history") == responder.answer(
            "tell me about history"
        )

    def test_fallback_is_stable_across_instances(self) -> None:
        assert Responder().answer("abc") == Responder().answer("abc")

    def test_fallback_differs_by_prompt(self) -> None:
        responder = Responder()
        assert responder.answer("abc") != responder.answer("xyz")

    def test_script_overrides_everything(self) -> None:
        """How a test forces a WRONG answer to prove a scorer can actually fail."""
        responder = Responder(script={"What is 2 + 2?": "banana"})
        assert responder.answer("What is 2 + 2?") == "banana"

    def test_script_lookup_ignores_surrounding_whitespace(self) -> None:
        responder = Responder(script={"hello": "hi"})
        assert responder.answer("  hello  ") == "hi"


class TestEstimateTokens:
    def test_is_stable(self) -> None:
        assert estimate_tokens("abcdefgh") == estimate_tokens("abcdefgh")

    def test_never_zero(self) -> None:
        assert estimate_tokens("") == 1
        assert estimate_tokens("a") == 1

    def test_grows_with_length(self) -> None:
        assert estimate_tokens("a" * 400) > estimate_tokens("a" * 40)


class TestJudgeProtocol:
    """The mock answers the REAL judge protocol, deterministically.

    Without this the end-to-end subjective path is untestable except by
    asserting that it fails: the judge would ask this service to grade a
    criterion and get back ``mock response 8f3a2b1c``, which the harness
    correctly refuses.

    Everything here is read out of the prompt the harness actually builds, so a
    change to the judge prompt's shape breaks these loudly rather than leaving a
    hand-written fixture answering a question nobody asks any more.
    """

    def _prompt(
        self,
        *,
        criterion: str = "specificity",
        scale: str = "scale: 0.0 to 1.0",
        completion: str = "Some feedback.",
    ) -> str:
        from ida_harness.judge import JUDGE_PROTOCOL_VERSION

        return (
            f'<judge-protocol version="{JUDGE_PROTOCOL_VERSION}"/>\n'
            "## The response under evaluation\n"
            f"{completion}\n"
            "## The one criterion you are grading\n"
            f"name: {criterion}\n"
            "## Scale\n"
            f"{scale}\n"
        )

    def test_a_judge_prompt_is_answered_in_the_reply_format(self) -> None:
        body = json.loads(Responder().answer(self._prompt()))
        assert set(body) == {"score", "rationale"}
        assert 0.0 <= body["score"] <= 1.0

    def test_the_grade_is_deterministic_for_a_criterion(self) -> None:
        """Otherwise the suite could not tell a judge regression from mock noise."""
        first = Responder().answer(self._prompt())
        second = Responder().answer(self._prompt())
        assert first == second

    def test_different_criteria_can_get_different_grades(self) -> None:
        """A mock that returned one constant would let a broken per-criterion
        loop pass every aggregation test."""
        grades = {
            json.loads(Responder().answer(self._prompt(criterion=name)))["score"]
            for name in ("specificity", "restraint", "tone", "actionability", "evidence")
        }
        assert len(grades) > 1

    def test_the_score_lands_on_an_anchor_of_the_declared_scale(self) -> None:
        body = json.loads(Responder().answer(self._prompt(scale="scale: 0.0 to 4.0")))
        assert body["score"] in {0.0, 2.0, 4.0}

    def test_it_honours_a_negative_lower_bound(self) -> None:
        body = json.loads(Responder().answer(self._prompt(scale="scale: -1.0 to 1.0")))
        assert -1.0 <= body["score"] <= 1.0

    def test_malformed_mode_returns_prose_with_a_number_in_it(self) -> None:
        """The precise shape a number-scraping parser would misread."""
        answer = Responder(judge_mode="malformed").answer(self._prompt())
        with pytest.raises(ValueError):
            json.loads(answer)
        assert any(ch.isdigit() for ch in answer)

    def test_out_of_range_mode_parses_but_exceeds_the_scale(self) -> None:
        """A different failure from `malformed`: only the range check catches it."""
        body = json.loads(Responder(judge_mode="out_of_range").answer(self._prompt()))
        assert body["score"] > 1.0

    def test_a_non_judge_prompt_is_unaffected(self) -> None:
        assert Responder().answer("What is 2 + 2?") == "4"

    def test_the_script_still_wins_over_the_judge_path(self) -> None:
        prompt = self._prompt()
        responder = Responder(script={prompt.strip(): '{"score": 0.123}'})
        assert json.loads(responder.answer(prompt))["score"] == 0.123
