"""Solvers: how a sample's input becomes messages, and messages become an answer.

The **solver** seam (a concept borrowed from Inspect AI, D-4) is what will let
us compare prompting strategies -- zero-shot vs few-shot vs self-consistency --
without touching the runner or the scorer.

The skeleton ships exactly one: :class:`SingleTurnSolver`.  It is real, not a
placeholder; it is simply the simplest strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ida_core.contracts import ChatMessage, SamplingParams, TaskSample, TaskSpec
from ida_harness.client import ChatCompletion, ModelClient


@dataclass(frozen=True)
class SolveOutcome:
    """What a solver produced for one sample."""

    messages: list[ChatMessage]
    """The full conversation, archived verbatim into the transcript."""

    completion: ChatCompletion


@runtime_checkable
class Solver(Protocol):
    """Turn one sample into one answer, using the client however it likes."""

    def solve(
        self,
        task: TaskSpec,
        sample: TaskSample,
        client: ModelClient,
        sampling: SamplingParams,
    ) -> SolveOutcome:
        """Produce an answer.  May call the client more than once."""


class SingleTurnSolver:
    """One system message (if the task has one) + one user message.

    Deliberately does *not* append "answer with only the number" style coaching:
    any instruction that shapes the answer belongs in the task's
    ``system_prompt``, where it is visible, versioned and part of the git SHA
    recorded on the result (D-1).
    """

    def solve(
        self,
        task: TaskSpec,
        sample: TaskSample,
        client: ModelClient,
        sampling: SamplingParams,
    ) -> SolveOutcome:
        messages: list[ChatMessage] = []
        if task.system_prompt:
            messages.append(ChatMessage(role="system", content=task.system_prompt))
        messages.append(ChatMessage(role="user", content=sample.input))
        completion = client.complete(messages, sampling)
        return SolveOutcome(messages=messages, completion=completion)
