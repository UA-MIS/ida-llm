"""Fixtures for harness tests.

The client tests drive real ``httpx`` machinery through a ``MockTransport`` --
that exercises our request building, status handling and parsing for real,
while staying hermetic.
"""

from __future__ import annotations

import pytest

from ida_core.contracts import (
    ModelEntry,
    Quantization,
    SamplingParams,
    ServingConfig,
    ServingStack,
    TaskKind,
    TaskSpec,
)


@pytest.fixture
def model_entry() -> ModelEntry:
    return ModelEntry(
        key="mock",
        display_name="Mock",
        base_url="http://mock-model:8000/v1",
        api_key_env=None,
        max_retries=2,
        serving=ServingConfig(
            model_id="mock-echo-1",
            serving_stack=ServingStack.MOCK,
            quantization=Quantization.NONE,
            sampling=SamplingParams(temperature=0.0, max_tokens=64, seed=7),
        ),
    )


@pytest.fixture
def verifiable_task() -> TaskSpec:
    return TaskSpec.model_validate(
        {
            "version": 1,
            "id": "test/arith",
            "title": "Arithmetic",
            "kind": TaskKind.VERIFIABLE,
            "system_prompt": "Answer with the number on the last line.",
            "scorer": {"kind": "numeric_match", "normalisation": {"take_last_line": True}},
            "samples": [
                {"id": "a", "input": "What is 2 + 2?", "target": "4"},
                {"id": "b", "input": "What is 10 * 10?", "target": "100"},
            ],
        }
    )


@pytest.fixture
def subjective_task() -> TaskSpec:
    return TaskSpec.model_validate(
        {
            "version": 1,
            "id": "test/subj",
            "title": "Subjective",
            "kind": TaskKind.SUBJECTIVE,
            "scorer": {"kind": "llm_judge", "rubric_id": "r1"},
            "rubric": {"id": "r1", "criteria": [{"name": "c", "description": "d"}]},
            "samples": [{"id": "s1", "input": "Give feedback on this essay."}],
        }
    )


@pytest.fixture
def no_sleep():
    """Make backoff instant and deterministic for retry tests."""
    return lambda _seconds: None


@pytest.fixture
def no_jitter():
    """Deterministic 'jitter': always the ceiling."""
    return lambda _low, high: high
