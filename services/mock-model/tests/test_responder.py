"""Responder rules. Determinism is the property that makes the tracer bullet meaningful."""

from __future__ import annotations

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
