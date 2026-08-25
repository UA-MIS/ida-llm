"""Authoring-time entry checks (review B1).

The case that motivates all of this: ``SamplingParams`` defaults ``temperature``
to 0.0 (the benchmark default), and current Claude models reject a non-default
``temperature`` with a 400.  So an ``anthropic_compat`` entry that simply *omits*
its ``sampling:`` block is broken on every call, and broken invisibly -- the
mistake is a line nobody wrote.

Both directions are tested: the checks fire on the shapes that fail on the wire,
and stay silent on the shapes that do not.  A validator with no negative tests is
a validator nobody can safely tighten later.
"""

from __future__ import annotations

import pytest

from ida_core.contracts import (
    ModelEntry,
    ModelRegistry,
    SamplingParams,
    ServingConfig,
    ServingStack,
)
from ida_harness.preflight import check_entry, check_registry, errors


def _entry(
    stack: ServingStack, sampling: SamplingParams | None = None, key: str = "m"
) -> ModelEntry:
    serving = ServingConfig(model_id="model-1", serving_stack=stack)
    if sampling is not None:
        serving = serving.model_copy(update={"sampling": sampling})
    return ModelEntry(
        key=key,
        display_name="M",
        base_url="https://example.test/v1",
        serving=serving,
    )


def _fields(problems) -> set[str]:
    return {p.field for p in problems}


class TestTheMotivatingCase:
    def test_an_anthropic_entry_with_no_sampling_block_is_flagged(self) -> None:
        """The whole point of B1. Nothing was written, so nothing looks wrong --
        but the inherited temperature 0.0 400s on every current model."""
        problems = check_entry(_entry(ServingStack.ANTHROPIC_COMPAT))
        assert "serving.sampling.temperature" in _fields(problems)
        assert any("no `sampling:` block" in p.message for p in problems)

    def test_the_message_names_the_fix_and_the_models_that_still_accept_it(self) -> None:
        (problem,) = check_entry(_entry(ServingStack.ANTHROPIC_COMPAT))
        assert "1.0" in problem.message
        assert "Sonnet 4.6" in problem.message
        assert problem.entry_key == "m"


class TestSeverities:
    def test_a_seed_is_an_error_not_a_warning(self) -> None:
        """No Anthropic model has ever had a seed parameter, so this can never
        be a deliberate choice."""
        problems = check_entry(
            _entry(ServingStack.ANTHROPIC_COMPAT, SamplingParams(temperature=1.0, seed=7))
        )
        assert [p.severity for p in problems] == ["error"]
        assert "seed" in problems[0].field

    def test_both_sampling_params_non_default_is_an_error(self) -> None:
        """Claude 4.x rejects the pair; newer models reject either. There is no
        model for which this is correct, so it is not a judgement call."""
        problems = check_entry(
            _entry(ServingStack.ANTHROPIC_COMPAT, SamplingParams(temperature=0.2, top_p=0.9))
        )
        assert errors(problems)
        assert "No Claude model accepts both" in problems[0].message

    def test_one_non_default_param_is_only_a_warning(self) -> None:
        """Deliberate and correct against Sonnet 4.6 / Haiku 4.5, so warning --
        a hard failure here would be wrong the day a model accepts it again."""
        problems = check_entry(
            _entry(ServingStack.ANTHROPIC_COMPAT, SamplingParams(temperature=0.0, top_p=1.0))
        )
        assert [p.severity for p in problems] == ["warning"]
        assert errors(problems) == []


class TestNoFalsePositives:
    def test_api_defaults_are_silent(self) -> None:
        sampling = SamplingParams(temperature=1.0, top_p=1.0, seed=None)
        assert check_entry(_entry(ServingStack.ANTHROPIC_COMPAT, sampling)) == []

    @pytest.mark.parametrize(
        "stack",
        [
            ServingStack.OPENAI_API,
            ServingStack.VLLM,
            ServingStack.OLLAMA,
            ServingStack.LLAMA_CPP,
            ServingStack.MOCK,
        ],
    )
    def test_other_stacks_are_never_flagged(self, stack: ServingStack) -> None:
        """vLLM honours seed and sampling; saying otherwise would train authors
        to ignore this validator."""
        sampling = SamplingParams(temperature=0.0, top_p=1.0, seed=20260101)
        assert check_entry(_entry(stack, sampling)) == []


class TestRegistrySweep:
    def test_disabled_entries_are_checked_too(self) -> None:
        """A disabled entry is one `enabled: true` away from spending money, and
        is exactly the entry nobody has ever run."""
        entry = _entry(ServingStack.ANTHROPIC_COMPAT, SamplingParams(temperature=0.0))
        entry.enabled = False
        problems = check_registry(ModelRegistry(version=1, models=[entry]))
        assert problems, "a disabled entry still has to be right before it is enabled"

    def test_every_entry_is_reported_under_its_own_key(self) -> None:
        registry = ModelRegistry(
            version=1,
            models=[
                _entry(ServingStack.ANTHROPIC_COMPAT, SamplingParams(temperature=0.0), key="a"),
                _entry(ServingStack.ANTHROPIC_COMPAT, SamplingParams(seed=1), key="b"),
            ],
        )
        assert {p.entry_key for p in check_registry(registry)} == {"a", "b"}
