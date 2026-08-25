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


class TestTargetsDoNotLeakIntoMetadata:
    """The rule that closes the metadata/redaction hole.

    `GET /tasks/{id}` redacts every `target` behind the `author` role but
    serves `sample.metadata` verbatim to anyone. A derivation written into
    metadata therefore publishes the answer key the redaction exists to
    protect. `tasks/SCHEMA.md` told authors not to do it; nothing stopped them.
    """

    @staticmethod
    def _with(metadata: dict, target: str = "42") -> dict:
        return _verifiable_task(
            samples=[{"id": "s1", "input": "q", "target": target, "metadata": metadata}]
        )

    # --- must be rejected ---------------------------------------------------

    @pytest.mark.parametrize(
        ("target", "metadata", "why"),
        [
            ("42", {"note": "the answer is 42"}, "stated in prose"),
            ("42", {"answer": 42}, "an int value"),
            ("7.5", {"working": "63/840*100 = 7.50"}, "same value, different format"),
            ("3", {"note": "result: +3"}, "signed form"),
            ("-11", {"note": "comes to -11"}, "negative"),
            ("1.92", {"check": "1.92"}, "exact string"),
            ("42", {"outer": {"inner": "= 42"}}, "nested dict"),
            ("42", {"steps": ["first", "then 42"]}, "inside a list"),
            ("paris", {"note": "the answer is Paris"}, "non-numeric, case-insensitive"),
        ],
    )
    def test_a_recoverable_target_is_rejected(self, target, metadata, why) -> None:
        with pytest.raises(ValidationError, match="leaks gold answers"):
            TaskSpec.model_validate(self._with(metadata, target))

    # --- must NOT be rejected ----------------------------------------------

    @pytest.mark.parametrize(
        ("target", "metadata", "why"),
        [
            ("4", {"mirrors": "l4-distribution-key"}, "digit inside an identifier"),
            ("2", {"template": "interest-v2"}, "version suffix"),
            ("3", {"tags": "ladder-l3"}, "rung name"),
            ("5", {"skill": "mode", "provenance": "synthetic"}, "no digits at all"),
            ("42", {"note": "421 items"}, "a longer number is not the target"),
            ("1", {"skill": "one-sample-t"}, "the word one is not the digit 1"),
        ],
    )
    def test_an_identifier_containing_a_digit_is_not_a_leak(self, target, metadata, why) -> None:
        """The false-positive guard. Without it the rule is unusable.

        Sample metadata is full of digit-bearing identifiers (`ladder-l3`,
        `mirrors: l4-distribution-key`). A rule that reads the `4` out of
        `l4-distribution-key` and fails a task whose target is `4` gets
        switched off, and then it protects nothing.
        """
        TaskSpec.model_validate(self._with(metadata, target))  # must not raise

    def test_subjective_samples_are_unaffected(self) -> None:
        """No target, nothing to leak -- and metadata is how subjective samples
        carry their probe labels."""
        doc = _subjective_task(
            samples=[{"id": "s1", "input": "q", "metadata": {"probe": "42", "n": 42}}]
        )
        TaskSpec.model_validate(doc)

    def test_the_rule_reports_the_offending_sample(self) -> None:
        doc = _verifiable_task(
            samples=[
                {"id": "clean", "input": "q", "target": "1", "metadata": {"skill": "x"}},
                {"id": "dirty", "input": "q", "target": "42", "metadata": {"note": "it is 42"}},
            ]
        )
        with pytest.raises(ValidationError, match="dirty"):
            TaskSpec.model_validate(doc)

    def test_a_derivation_without_the_answer_is_not_caught(self) -> None:
        """The documented blind spot, asserted so it stays documented.

        `sum=70, n=5` hands a reader the answer 14 without containing it. This
        rule is a tripwire for the mechanical mistake, NOT proof that a task
        keeps its key secret -- and a test that pretends otherwise would be
        worse than no test.
        """
        TaskSpec.model_validate(self._with({"working": "sum=70, n=5"}, "14"))

    def test_the_shipped_tasks_all_pass(self) -> None:
        """The corpus students copy must itself be clean."""
        from ida_core.config import repo_root
        from ida_core.validation import discover_task_files, load_yaml

        files = discover_task_files(repo_root() / "tasks")
        assert files, "no task files found -- this test would pass vacuously"
        for path in files:
            TaskSpec.model_validate(load_yaml(path))
