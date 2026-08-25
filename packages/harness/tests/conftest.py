"""Fixtures for harness tests.

The client tests drive real ``httpx`` machinery through a ``MockTransport`` --
that exercises our request building, status handling and parsing for real,
while staying hermetic.
"""

from __future__ import annotations

import pytest

from ida_core.contracts import (
    CostRates,
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
    """The model under test.

    **Priced, and priced differently from the judge.**  It used to inherit
    ``CostRates(0.0, 0.0)``, which made every ``cost_usd == 0`` assertion in the
    suite trivially true: a regression that billed the candidate's tokens at the
    JUDGE's rates, or folded judge spend into ``cost_usd``, would have left every
    one of them passing.  Rates that are non-zero, and not multiples of the
    judge's, make each of those numbers identify exactly one arithmetic.
    """
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
        cost=CostRates(input_usd_per_mtok=0.5, output_usd_per_mtok=4.0),
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


ANCHORED_DESCRIPTION = """\
Does the response point at concrete passages rather than offering advice that
would fit any essay?

1.0 -- quotes or names at least one specific passage and says what is wrong with it.
0.5 -- refers to the essay in general terms ("your argument", "the evidence").
0.0 -- gives advice that would apply unchanged to a different essay.\
"""
"""A criterion description carrying ANCHOR LEVELS, as this repo's exemplars do.

The anchors live in ``description`` -- there is no separate ``levels`` field --
so "the judge prompt carries the anchors verbatim" is a claim about this exact
string surviving into the prompt uncut.
"""


@pytest.fixture
def anchored_task() -> TaskSpec:
    """A subjective task whose rubric has anchors, weights and more than one criterion.

    Weights are deliberately unequal (3/1) so a weighted mean is distinguishable
    from a plain one: with values 1.0 and 0.0 the weighted answer is 0.75 and the
    unweighted answer is 0.5.
    """
    return TaskSpec.model_validate(
        {
            "version": 1,
            "id": "test/anchored",
            "title": "Anchored feedback",
            "description": "Formative feedback on an undergraduate essay excerpt.",
            "kind": TaskKind.SUBJECTIVE,
            "system_prompt": "You are an experienced writing instructor.",
            "scorer": {"kind": "llm_judge", "rubric_id": "anchored-v1"},
            "rubric": {
                "id": "anchored-v1",
                "scale_min": 0.0,
                "scale_max": 1.0,
                "criteria": [
                    {
                        "name": "specificity",
                        "description": ANCHORED_DESCRIPTION,
                        "weight": 3.0,
                    },
                    {
                        "name": "restraint",
                        "description": "Does not rewrite the passage for the student.",
                        "weight": 1.0,
                    },
                ],
            },
            "samples": [
                {"id": "s1", "input": "Give feedback on: 'The war was important.'"},
                {"id": "s2", "input": "Give feedback on: 'Many sources say this.'"},
            ],
        }
    )


@pytest.fixture
def judge_entry() -> ModelEntry:
    """A judge model entry priced DIFFERENTLY from the candidate.

    Both sides are non-zero and neither rate is a multiple of the other's, so
    every spend figure in the suite names exactly one arithmetic: candidate
    tokens at candidate rates, judge tokens at judge rates, and the two mistakes
    worth catching -- billing one at the other's rates, or summing them --
    produce visibly different numbers rather than the same zero.
    """
    return ModelEntry(
        key="mock-judge",
        display_name="Mock judge",
        base_url="http://mock-model:8000/v1",
        api_key_env=None,
        max_retries=1,
        serving=ServingConfig(
            model_id="mock-judge-1",
            serving_stack=ServingStack.MOCK,
            quantization=Quantization.NONE,
            sampling=SamplingParams(temperature=0.0, max_tokens=256, seed=11),
        ),
        cost=CostRates(input_usd_per_mtok=1.0, output_usd_per_mtok=2.0),
    )


@pytest.fixture
def no_sleep():
    """Make backoff instant and deterministic for retry tests."""
    return lambda _seconds: None


@pytest.fixture
def no_jitter():
    """Deterministic 'jitter': always the ceiling."""
    return lambda _low, high: high
