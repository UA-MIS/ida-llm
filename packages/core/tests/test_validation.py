"""The two validation layers must agree.

A file that passes JSON Schema but fails pydantic (or vice versa) is a bug in
whichever layer is out of step -- see ida_core.validation's module docstring.
"""

from __future__ import annotations

import pytest

from ida_core.config import repo_root
from ida_core.contracts import ModelRegistry, TaskSpec
from ida_core.validation import (
    ValidationError,
    discover_task_files,
    load_yaml,
    validate_models_document,
    validate_task_document,
)


def _verifiable_doc(**overrides) -> dict:
    doc = {
        "version": 1,
        "id": "demo/t",
        "title": "T",
        "kind": "verifiable",
        "scorer": {"kind": "exact_match"},
        "samples": [{"id": "s1", "input": "q", "target": "a"}],
    }
    doc.update(overrides)
    return doc


def _subjective_doc(**overrides) -> dict:
    doc = {
        "version": 1,
        "id": "demo/s",
        "title": "S",
        "kind": "subjective",
        "scorer": {"kind": "llm_judge", "rubric_id": "r1"},
        "rubric": {"id": "r1", "criteria": [{"name": "c", "description": "d"}]},
        "samples": [{"id": "s1", "input": "q"}],
    }
    doc.update(overrides)
    return doc


class TestSchemaAcceptsValidDocuments:
    def test_verifiable(self) -> None:
        validate_task_document(_verifiable_doc())

    def test_subjective(self) -> None:
        validate_task_document(_subjective_doc())


class TestSchemaEnforcesTheTaxonomy:
    """These are the same rules pydantic enforces; both layers must catch them."""

    def test_verifiable_without_target_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_task_document(_verifiable_doc(samples=[{"id": "s", "input": "q"}]))

    def test_verifiable_with_judge_scorer_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_task_document(_verifiable_doc(scorer={"kind": "llm_judge", "rubric_id": "r"}))

    def test_verifiable_with_rubric_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_task_document(
                _verifiable_doc(rubric={"id": "r", "criteria": [{"name": "c", "description": "d"}]})
            )

    def test_subjective_without_rubric_rejected(self) -> None:
        doc = _subjective_doc()
        del doc["rubric"]
        with pytest.raises(ValidationError):
            validate_task_document(doc)

    def test_subjective_with_target_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_task_document(
                _subjective_doc(samples=[{"id": "s", "input": "q", "target": "a"}])
            )


class TestSchemaStructuralRules:
    def test_unknown_top_level_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_task_document(_verifiable_doc(surprise=1))

    def test_wrong_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_task_document(_verifiable_doc(version=2))

    def test_unsafe_sample_id_rejected(self) -> None:
        """Sample ids become object-key leaves; the schema enforces path-safety."""
        with pytest.raises(ValidationError):
            validate_task_document(
                _verifiable_doc(samples=[{"id": "a/b", "input": "q", "target": "a"}])
            )

    def test_empty_samples_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_task_document(_verifiable_doc(samples=[]))

    def test_error_message_names_the_file_and_path(self) -> None:
        with pytest.raises(ValidationError) as exc:
            validate_task_document(_verifiable_doc(kind="nonsense"), "some/file.yaml")
        assert "some/file.yaml" in str(exc.value)
        assert "kind" in str(exc.value)


class TestModelsSchema:
    def _doc(self, **overrides) -> dict:
        entry = {
            "key": "mock",
            "display_name": "Mock",
            "base_url": "http://mock-model:8000/v1",
            "serving": {"model_id": "mock-echo-1", "serving_stack": "mock"},
        }
        entry.update(overrides)
        return {"version": 1, "models": [entry]}

    def test_minimal_document_is_valid(self) -> None:
        validate_models_document(self._doc())

    def test_uppercase_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_models_document(self._doc(key="MOCK"))

    def test_non_http_base_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_models_document(self._doc(base_url="ftp://x/v1"))

    def test_unknown_serving_stack_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_models_document(
                self._doc(serving={"model_id": "m", "serving_stack": "telepathy"})
            )

    def test_negative_cost_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_models_document(self._doc(cost={"input_usd_per_mtok": -1}))

    def test_no_api_key_field_exists(self) -> None:
        """Secrets must be impossible to put in this file, not merely discouraged."""
        with pytest.raises(ValidationError):
            validate_models_document(self._doc(api_key="sk-oops"))


class TestShippedFilesAreValid:
    """The repo's own tasks/ and models.yaml must pass BOTH layers."""

    def test_models_yaml(self) -> None:
        path = repo_root() / "models.yaml"
        document = load_yaml(path)
        validate_models_document(document, path)
        registry = ModelRegistry.model_validate(document)
        assert "mock" in registry.enabled_keys()

    def test_every_task_file(self) -> None:
        files = discover_task_files(repo_root() / "tasks")
        assert files, "expected at least the two demo tasks"
        for path in files:
            document = load_yaml(path)
            validate_task_document(document, path)
            TaskSpec.model_validate(document)

    def test_both_demo_kinds_are_represented(self) -> None:
        kinds = {
            TaskSpec.model_validate(load_yaml(p)).kind.value
            for p in discover_task_files(repo_root() / "tasks")
        }
        assert kinds == {"verifiable", "subjective"}


class TestDiscovery:
    def test_underscore_prefixed_files_are_skipped(self, tmp_path) -> None:
        (tmp_path / "real.yaml").write_text("id: x")
        (tmp_path / "_partial.yaml").write_text("id: y")
        assert [p.name for p in discover_task_files(tmp_path)] == ["real.yaml"]

    def test_missing_directory_yields_nothing(self, tmp_path) -> None:
        assert discover_task_files(tmp_path / "nope") == []

    def test_yml_extension_is_found(self, tmp_path) -> None:
        (tmp_path / "a.yml").write_text("id: x")
        assert len(discover_task_files(tmp_path)) == 1


class TestBothLayersAgreeOnNumericPunctuation:
    """B3 — the JSON Schema and pydantic must reject the same thing.

    `ida_core.validation`'s docstring says a file that passes one layer and
    fails the other is a bug in whichever is out of step. This pins the specific
    rule that was added to pydantic first, so the schema cannot silently lag.
    """

    def _doc(self, kind: str, strip_punctuation: bool) -> dict:
        return {
            "version": 1,
            "id": "demo/t",
            "title": "T",
            "kind": "verifiable",
            "scorer": {
                "kind": kind,
                "normalisation": {"strip_punctuation": strip_punctuation},
            },
            "samples": [{"id": "s1", "input": "q", "target": "42"}],
        }

    def test_schema_rejects_strip_punctuation_for_numeric_match(self) -> None:
        with pytest.raises(ValidationError):
            validate_task_document(self._doc("numeric_match", True))

    def test_pydantic_rejects_it_too(self) -> None:
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="numerically significant"):
            TaskSpec.model_validate(self._doc("numeric_match", True))

    def test_both_accept_it_for_exact_match(self) -> None:
        doc = self._doc("exact_match", True)
        validate_task_document(doc)
        TaskSpec.model_validate(doc)

    def test_both_accept_numeric_match_without_it(self) -> None:
        doc = self._doc("numeric_match", False)
        validate_task_document(doc)
        TaskSpec.model_validate(doc)


class TestContentSha:
    """B8 — the per-task comparability key."""

    def test_a_loaded_task_carries_one(self) -> None:
        from ida_harness.tasks import load_task_file

        for path in discover_task_files(repo_root() / "tasks"):
            assert len(load_task_file(path).content_sha) == 64

    def test_it_ignores_formatting_and_comments(self) -> None:
        """Reindenting a task, or fixing a typo in a comment, must not invalidate
        every stored result's comparability or bust the completion cache."""
        from ida_core.contracts import content_sha_of

        assert content_sha_of({"a": 1, "b": [2, 3]}) == content_sha_of({"b": [2, 3], "a": 1})

    def test_it_changes_when_content_changes(self) -> None:
        from ida_core.contracts import content_sha_of

        assert content_sha_of({"target": "42"}) != content_sha_of({"target": "43"})

    def test_it_cannot_be_authored_in_a_task_file(self) -> None:
        """It is derived; letting a file assert its own hash would be meaningless."""
        doc = {
            "version": 1,
            "id": "demo/t",
            "title": "T",
            "kind": "verifiable",
            "scorer": {"kind": "exact_match"},
            "samples": [{"id": "s1", "input": "q", "target": "a"}],
            "content_sha": "f" * 64,
        }
        with pytest.raises(ValidationError):
            validate_task_document(doc)
