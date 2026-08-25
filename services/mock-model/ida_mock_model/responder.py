"""The canned-answer logic.  Deterministic, dependency-free, unit-testable.

Answering rules, tried in order:

1. **Scripted override** -- an exact prompt match in :attr:`Responder.script`.
   How a test pins a specific answer (including a deliberately *wrong* one).
2. **Judge protocol** -- if the prompt is an LLM-as-judge criterion prompt
   (:data:`JUDGE_MARKER`), answer it in the judge's reply format.  See below.
3. **Arithmetic** -- if the prompt contains a simple ``a <op> b`` expression,
   evaluate it and answer with the number.  This is what makes the demo
   verifiable task genuinely pass rather than pass by coincidence.
4. **Echo fallback** -- a stable, prompt-derived sentence.

Rule 3 is a tiny hand-rolled evaluator, **not** ``eval()``: the prompt is
untrusted input and ``eval`` on untrusted input is a remote code execution hole,
even in a mock.

Rule 2, and why the mock knows about judging
--------------------------------------------
Without it, an end-to-end subjective run reaches the judge, the judge asks this
service to grade a criterion, and this service replies ``mock response 8f3a2b1c``
-- which the harness correctly refuses as unparseable.  The whole subjective
path would then be untestable end to end except by asserting that it fails.

So the mock answers the protocol for real: it reads the criterion name and the
declared scale out of the prompt and returns a well-formed judgment, chosen
deterministically from the criterion name so the same rubric always produces the
same grade.  :attr:`Responder.judge_mode` deliberately breaks it -- ``malformed``
and ``out_of_range`` are how the failure drills get a *service* that misbehaves
rather than a stub that pretends to.

It reads only what the protocol puts in the prompt on purpose.  If the judge
prompt changes shape, this stops matching and the end-to-end test fails loudly,
rather than a hand-written fixture continuing to answer a question nobody asks
any more.
"""

from __future__ import annotations

import hashlib
import json
import operator
import re
from dataclasses import dataclass, field

# The U+00D7 MULTIPLICATION SIGN is deliberate, not a typo for "x": it is what
# a quiz item authored in a word processor actually contains, and the mock has
# to understand the prompts real tasks will carry.
_ARITHMETIC = re.compile(
    r"(?<![\d.])(-?\d+(?:\.\d+)?)\s*([+\-*/x\u00d7])\s*(-?\d+(?:\.\d+)?)(?![\d.])"
)

JUDGE_MARKER = "<judge-protocol version="
"""Marks a prompt built by :func:`ida_harness.judge.build_criterion_messages`."""

_JUDGE_CRITERION = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
_JUDGE_SCALE = re.compile(r"^scale:\s*(-?[\d.]+)\s+to\s+(-?[\d.]+)\s*$", re.MULTILINE)

JUDGE_ANCHORS = (0.0, 0.5, 1.0)
"""The anchor fractions the mock picks between.

Matches how this repo's exemplar rubrics are authored -- three behavioural
levels -- so a mock grade lands on an anchor a human wrote rather than on some
arbitrary interior value.
"""

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


def judge_reply(user_message: str, *, mode: str = "json") -> str:
    """Answer one judge-criterion prompt, deterministically.

    ``mode``:

    ``json``           a well-formed judgment on the prompt's own scale.
    ``malformed``      prose with a number in it -- the exact shape a real judge
                       produces when it ignores the reply format, and the one a
                       number-scraping parser would happily misread.
    ``out_of_range``   well-formed JSON scoring above ``scale_max``.  Separated
                       from ``malformed`` because it is a different failure: the
                       reply parses, and only the range check catches it.
    """
    criterion_match = _JUDGE_CRITERION.search(user_message)
    criterion = criterion_match.group(1).strip() if criterion_match else "unknown"

    scale_match = _JUDGE_SCALE.search(user_message)
    scale_min = float(scale_match.group(1)) if scale_match else 0.0
    scale_max = float(scale_match.group(2)) if scale_match else 1.0

    digest = hashlib.sha256(criterion.encode()).digest()
    fraction = JUDGE_ANCHORS[digest[0] % len(JUDGE_ANCHORS)]
    score = scale_min + fraction * (scale_max - scale_min)

    if mode == "malformed":
        return (
            f"I'd say this response is around {format_number(score)} out of "
            f"{format_number(scale_max)} on {criterion}, though you could argue for less."
        )
    if mode == "out_of_range":
        score = scale_max + 1.0

    rationale = (
        f"mock judgment for {criterion}: chosen from the criterion name, so this "
        "grade is deterministic and means nothing about the response."
    )
    return json.dumps({"score": score, "rationale": rationale})


@dataclass
class Responder:
    """Turns a prompt into a deterministic answer.

    ``script`` maps an exact user-message string to the exact reply to give.
    It is how tests force a wrong answer to prove a scorer actually fails.
    """

    script: dict[str, str] = field(default_factory=dict)
    judge_mode: str = "json"
    """How to answer a judge prompt: ``json``, ``malformed`` or ``out_of_range``."""

    def answer(self, user_message: str) -> str:
        scripted = self.script.get(user_message.strip())
        if scripted is not None:
            return scripted

        if JUDGE_MARKER in user_message:
            return judge_reply(user_message, mode=self.judge_mode)

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
