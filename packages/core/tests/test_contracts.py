"""The taxonomy rules and reproducibility invariants are the point of this file.

If a test here fails, a contract changed. That is either deliberate (bump the
schema version, update the docs) or a bug.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ida_core.contracts import (
    CostRates,
    ModelEntry,
    ModelRegistry,
    Rubric,
    RubricCriterion,
    SamplingParams,
    ScorerKind,
    ScorerSpec,
    ServingConfig,
    ServingStack,
    TaskKind,
    TaskSample,
    TaskSpec,
    TokenUsage,
)


def _verifiable_task(**overrides) -> dict:
    base = {
        "id": "demo/t",
        "title": "T",
        "kind": TaskKind.VERIFIABLE,
        "scorer": {"kind": ScorerKind.EXACT_MATCH},
        "samples": [{"id": "s1", "input": "q", "target": "a"}],
    }
    base.update(overrides)
    return base


def _subjective_task(**overrides) -> dict:
    base = {
        "id": "demo/s",
        "title": "S",
        "kind": TaskKind.SUBJECTIVE,
        "scorer": {"kind": ScorerKind.LLM_JUDGE, "rubric_id": "r1"},
        "rubric": {"id": "r1", "criteria": [{"name": "c", "description": "d"}]},
        "samples": [{"id": "s1", "input": "q"}],
    }
    base.update(overrides)
    return base


class TestTaskTaxonomy:
    def test_verifiable_task_is_scorable(self) -> None:
        spec = TaskSpec.model_validate(_verifiable_task())
        assert spec.is_scorable is True

    def test_subjective_task_is_not_scorable_in_skeleton(self) -> None:
        spec = TaskSpec.model_validate(_subjective_task())
        assert spec.is_scorable is False

    def test_verifiable_sample_without_target_is_rejected(self) -> None:
        doc = _verifiable_task(samples=[{"id": "s1", "input": "q"}])
        with pytest.raises(ValidationError, match="without a target"):
            TaskSpec.model_validate(doc)

    def test_verifiable_task_with_judge_scorer_is_rejected(self) -> None:
        doc = _verifiable_task(scorer={"kind": ScorerKind.LLM_JUDGE, "rubric_id": "r"})
        with pytest.raises(ValidationError, match="programmatic scorer"):
            TaskSpec.model_validate(doc)

    def test_verifiable_task_with_rubric_is_rejected(self) -> None:
        doc = _verifiable_task(rubric={"id": "r1", "criteria": [{"name": "c", "description": "d"}]})
        with pytest.raises(ValidationError, match="must not carry a rubric"):
            TaskSpec.model_validate(doc)

    def test_subjective_task_without_rubric_is_rejected(self) -> None:
        doc = _subjective_task()
        del doc["rubric"]
        with pytest.raises(ValidationError, match="must carry a rubric"):
            TaskSpec.model_validate(doc)

    def test_subjective_task_with_targets_is_rejected(self) -> None:
        doc = _subjective_task(samples=[{"id": "s1", "input": "q", "target": "a"}])
        with pytest.raises(ValidationError, match="must not carry targets"):
            TaskSpec.model_validate(doc)

    def test_subjective_task_with_mismatched_rubric_id_is_rejected(self) -> None:
        doc = _subjective_task(scorer={"kind": ScorerKind.LLM_JUDGE, "rubric_id": "other"})
        with pytest.raises(ValidationError, match=r"does not match rubric\.id"):
            TaskSpec.model_validate(doc)

    def test_duplicate_sample_ids_are_rejected(self) -> None:
        doc = _verifiable_task(
            samples=[
                {"id": "s1", "input": "q", "target": "a"},
                {"id": "s1", "input": "q2", "target": "b"},
            ]
        )
        with pytest.raises(ValidationError, match="duplicate sample ids"):
            TaskSpec.model_validate(doc)

    def test_task_needs_at_least_one_sample(self) -> None:
        with pytest.raises(ValidationError):
            TaskSpec.model_validate(_verifiable_task(samples=[]))

    def test_unknown_field_is_rejected(self) -> None:
        """extra=forbid across the contracts: a typo must not be silently ignored."""
        with pytest.raises(ValidationError):
            TaskSpec.model_validate(_verifiable_task(kimd="verifiable"))


class TestModelRegistry:
    def test_registry_key_is_derived_from_entry_key(self) -> None:
        entry = ModelEntry(
            key="mock",
            display_name="M",
            base_url="http://x/v1",
            serving=ServingConfig(model_id="m", serving_stack=ServingStack.MOCK),
        )
        assert entry.serving.registry_key == "mock"

    def test_mistyped_registry_key_is_normalised_not_rejected(self) -> None:
        entry = ModelEntry(
            key="mock",
            display_name="M",
            base_url="http://x/v1",
            serving=ServingConfig(
                model_id="m", registry_key="typo", serving_stack=ServingStack.MOCK
            ),
        )
        assert entry.serving.registry_key == "mock"

    def test_duplicate_keys_rejected(self, model_entry: ModelEntry) -> None:
        with pytest.raises(ValidationError, match="duplicate model keys"):
            ModelRegistry(models=[model_entry, model_entry.model_copy(deep=True)])

    def test_get_and_enabled_keys(self, model_entry: ModelEntry) -> None:
        disabled = model_entry.model_copy(deep=True, update={"key": "off", "enabled": False})
        disabled.serving.registry_key = "off"
        registry = ModelRegistry(models=[model_entry, disabled])
        assert registry.get("mock").key == "mock"
        assert registry.enabled_keys() == ["mock"]
        with pytest.raises(KeyError):
            registry.get("nope")


class TestTokenAccounting:
    def test_addition_and_total(self) -> None:
        a = TokenUsage(prompt_tokens=10, completion_tokens=5)
        b = TokenUsage(prompt_tokens=1, completion_tokens=2)
        total = a + b
        assert (total.prompt_tokens, total.completion_tokens) == (11, 7)
        assert total.total_tokens == 18

    def test_cost_is_per_million_tokens(self) -> None:
        usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000)
        rates = CostRates(input_usd_per_mtok=3.0, output_usd_per_mtok=15.0)
        assert usage.cost_usd(rates) == pytest.approx(3.0 + 7.5)

    def test_self_hosted_costs_nothing(self) -> None:
        usage = TokenUsage(prompt_tokens=10_000, completion_tokens=10_000)
        assert usage.cost_usd(CostRates()) == 0.0


class TestSamplingParams:
    def test_defaults_are_deterministic(self) -> None:
        """Benchmark defaults must be greedy, or re-runs are not reproducible."""
        params = SamplingParams()
        assert params.temperature == 0.0
        assert params.top_p == 1.0

    def test_temperature_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SamplingParams(temperature=3.0)


class TestRubric:
    def test_criterion_weight_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Rubric(id="r", criteria=[RubricCriterion(name="c", description="d", weight=0)])


class TestScorerSpec:
    def test_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScorerSpec(kind=ScorerKind.NUMERIC_MATCH, tolerance=-1)


class TestTaskSampleRoundTrip:
    def test_sample_metadata_is_preserved(self) -> None:
        sample = TaskSample(id="s", input="i", target="t", metadata={"difficulty": "easy"})
        assert TaskSample.model_validate(sample.model_dump()).metadata == {"difficulty": "easy"}
