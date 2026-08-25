"""Authoring-time checks on a ``models.yaml`` entry.  Nothing here runs per request.

Why this exists, and why it is not a runtime guard
--------------------------------------------------
:class:`~ida_core.contracts.SamplingParams` defaults ``temperature`` to **0.0**,
because that is the *benchmark* default -- we want near-deterministic output.
Current Claude models reject a **non-default** ``temperature``/``top_p`` with a
400.  Those two facts collide in the worst possible way: an author who adds an
``anthropic_compat`` entry and simply omits the ``sampling:`` block inherits
``temperature: 0.0``, which reaches the wire and fails every call.  The mistake
is invisible in the YAML precisely because nothing was written.

A hard local raise -- the treatment ``seed`` gets in
:class:`~ida_harness.anthropic_client.AnthropicMessagesClient` -- would be the
wrong instrument here, and the difference is worth stating:

``seed``          the Messages API has no such parameter, and never will while
                  it is the Messages API.  Refusing it is a statement about the
                  *protocol*, so it belongs in the client and holds forever.
``temperature``   exists and is merely *restricted on current models*.  A model
                  released next month may accept it again.  A hard raise would
                  be wrong the day that happens, and a benchmark harness that
                  refuses a parameter the endpoint accepts is its own bug.

So this is a check on **authored configuration**, run by the test suite over
every entry in ``models.yaml`` (see ``tests/test_registry_examples.py``).  It
fails at PR time, costs nothing at runtime, and ages gracefully: when a model
starts accepting sampling again, a warning here becomes wrong -- not a
production outage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ida_core.contracts import ModelEntry, ModelRegistry, ServingStack
from ida_harness.anthropic_client import (
    ANTHROPIC_DEFAULT_TEMPERATURE,
    ANTHROPIC_DEFAULT_TOP_P,
)

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class EntryProblem:
    """One complaint about one authored entry."""

    entry_key: str
    field: str
    """Dotted path to the offending field, as an author would find it in YAML."""

    severity: Severity
    """``error`` -- no model accepts this, it cannot be right.
    ``warning`` -- rejected by current models; deliberate only if you know the
    target accepts it."""

    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.entry_key}.{self.field}: {self.message}"


def check_entry(entry: ModelEntry) -> list[EntryProblem]:
    """Everything wrong with ``entry`` that is knowable without a network call."""
    if entry.serving.serving_stack is not ServingStack.ANTHROPIC_COMPAT:
        # The OpenAI-compatible surface accepts temperature, top_p and seed from
        # every server we target, so there is nothing to say about it here.
        return []
    return _check_anthropic_sampling(entry)


def check_registry(registry: ModelRegistry) -> list[EntryProblem]:
    """:func:`check_entry` over every entry, enabled or not.

    Disabled entries are checked too, on purpose: a disabled entry is one
    ``enabled: true`` away from spending money, and it is exactly the entry
    nobody has ever run.
    """
    return [problem for entry in registry.models for problem in check_entry(entry)]


def errors(problems: list[EntryProblem]) -> list[EntryProblem]:
    """Just the ``error``-severity ones."""
    return [p for p in problems if p.severity == "error"]


def _check_anthropic_sampling(entry: ModelEntry) -> list[EntryProblem]:
    sampling = entry.serving.sampling
    problems: list[EntryProblem] = []

    if sampling.seed is not None:
        problems.append(
            EntryProblem(
                entry.key,
                "serving.sampling.seed",
                "error",
                f"the Anthropic Messages API has no seed parameter, but this entry sets "
                f"{sampling.seed}. The client refuses to run rather than record a seeded "
                "run that was never seeded -- write `seed: null`.",
            )
        )

    off_temperature = sampling.temperature != ANTHROPIC_DEFAULT_TEMPERATURE
    off_top_p = sampling.top_p != ANTHROPIC_DEFAULT_TOP_P

    if off_temperature and off_top_p:
        problems.append(
            EntryProblem(
                entry.key,
                "serving.sampling",
                "error",
                f"temperature={sampling.temperature} and top_p={sampling.top_p} are both "
                f"non-default. No Claude model accepts both at once -- Claude 4.x rejects "
                "the pair, and newer models reject either. Set one of them back to 1.0.",
            )
        )
    else:
        if off_temperature:
            problems.append(_restricted(entry, "temperature", sampling.temperature))
        if off_top_p:
            problems.append(_restricted(entry, "top_p", sampling.top_p))

    return problems


def _restricted(entry: ModelEntry, field: str, value: float) -> EntryProblem:
    return EntryProblem(
        entry.key,
        f"serving.sampling.{field}",
        "warning",
        f"{field}={value} is not Anthropic's default (1.0), and current Claude models "
        f"(Opus 5, Sonnet 5, Opus 4.8/4.7) reject a non-default {field} with a 400. "
        "Correct only if this entry's model_id is one that still accepts sampling "
        "(Sonnet 4.6, Haiku 4.5). Otherwise write 1.0 -- the client omits a parameter "
        "already at the default, so the recorded ServingConfig stays true either way. "
        "NOTE: an entry with no `sampling:` block inherits temperature 0.0 and hits this.",
    )
