"""The canned-answer logic.  Deterministic, dependency-free, unit-testable.

Answering rules, tried in order:

1. **Scripted override** -- an exact prompt match in :attr:`Responder.script`.
   How a test pins a specific answer (including a deliberately *wrong* one).
2. **Arithmetic** -- if the prompt contains a simple ``a <op> b`` expression,
   evaluate it and answer with the number.  This is what makes the demo
   verifiable task genuinely pass rather than pass by coincidence.
3. **Echo fallback** -- a stable, prompt-derived sentence.

Rule 2 is a tiny hand-rolled evaluator, **not** ``eval()``: the prompt is
untrusted input and ``eval`` on untrusted input is a remote code execution hole,
even in a mock.
"""

from __future__ import annotations

import hashlib
import operator
import re
from dataclasses import dataclass, field

# The U+00D7 MULTIPLICATION SIGN is deliberate, not a typo for "x": it is what
# a quiz item authored in a word processor actually contains, and the mock has
# to understand the prompts real tasks will carry.
_ARITHMETIC = re.compile(
    r"(?<![\d.])(-?\d+(?:\.\d+)?)\s*([+\-*/x\u00d7])\s*(-?\d+(?:\.\d+)?)(?![\d.])"
)

_OPERATORS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "x": operator.mul,
    "\u00d7": operator.mul,  # U+00D7 MULTIPLICATION SIGN -- see _ARITHMETIC above
    "/": operator.truediv,
}


def evaluate_arithmetic(text: str) -> float | None:
    """Evaluate the first ``a <op> b`` expression in ``text``.

    Returns ``None`` when there is no expression, or when it is undefined
    (division by zero).  Never executes the input.
    """
    match = _ARITHMETIC.search(text)
    if match is None:
        return None
    left, symbol, right = match.groups()
    func = _OPERATORS[symbol]
    try:
        return float(func(float(left), float(right)))
    except ZeroDivisionError:
        return None


def format_number(value: float) -> str:
    """Render a number the way a careful student would: ``12`` not ``12.0``."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:g}"


@dataclass
class Responder:
    """Turns a prompt into a deterministic answer.

    ``script`` maps an exact user-message string to the exact reply to give.
    It is how tests force a wrong answer to prove a scorer actually fails.
    """

    script: dict[str, str] = field(default_factory=dict)

    def answer(self, user_message: str) -> str:
        scripted = self.script.get(user_message.strip())
        if scripted is not None:
            return scripted

        computed = evaluate_arithmetic(user_message)
        if computed is not None:
            return format_number(computed)

        digest = hashlib.sha256(user_message.encode()).hexdigest()[:8]
        return f"mock response {digest}"


def estimate_tokens(text: str) -> int:
    """A crude but *stable* token estimate: ~4 characters per token, min 1.

    Stable matters more than accurate here -- the tracer bullet asserts that
    token accounting flows end to end, and a wobbling estimate would make that
    assertion useless.
    """
    return max(1, len(text) // 4)
