"""The shared validation suite (design 4.4) fires every rule the CI gate
enforces, as path-addressed issues the admin console can pin to a field."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from ida_core.curriculum import load_curriculum
from ida_core.validation import ValidationError, load_yaml
from ida_core.validation_suite import (
    Issue,
    errors_of,
    issues_from_validation_error,
    validate_curriculum,
    validate_models,
    validate_task,
)

REPO = Path(__file__).resolve().parents[3]
CURRICULUM = load_curriculum(REPO / "curriculum" / "slo.yaml")


def _slo_task() -> dict:
    """A real SLO-tagged task document."""
    for path in sorted((REPO / "tasks").rglob("*.yaml")):
        document = load_yaml(path)
        if any(str(t).startswith("slo:") for t in document.get("tags", [])):
            return document
    raise AssertionError("no SLO-tagged task in the repo")


FAMILIES = {p.name for p in (REPO / "tasks").iterdir() if p.is_dir()}


def test_the_real_task_is_clean_and_returns_its_spec() -> None:
    issues, spec = validate_task(_slo_task(), curriculum=CURRICULUM, families=FAMILIES)
    assert errors_of(issues) == []
    assert spec is not None and len(spec.content_sha) == 64


def test_an_slo_tag_typo_is_an_error_on_tags() -> None:
    document = _slo_task()
    document["tags"] = ["slo:SL02" if str(t).startswith("slo:") else t for t in document["tags"]]
    issues, spec = validate_task(document, curriculum=CURRICULUM, families=FAMILIES)
    assert spec is None
    assert any(i.path == "tags" for i in errors_of(issues))


def test_a_schema_error_carries_its_path() -> None:
    document = _slo_task()
    del document["samples"][0]["input"]
    issues, _ = validate_task(document, curriculum=CURRICULUM, families=FAMILIES)
    assert any(i.path.startswith("samples/0") for i in issues)


def test_a_target_leaking_into_metadata_is_an_error() -> None:
    document = copy.deepcopy(load_yaml(REPO / "tasks" / "demo" / "arithmetic-quiz-check.yaml"))
    sample = document["samples"][0]
    sample.setdefault("metadata", {})["hint"] = f"the answer is {sample['target']}"
    issues, spec = validate_task(document, curriculum=CURRICULUM, families=FAMILIES)
    assert spec is None and errors_of(issues)


def test_an_unknown_family_prefix_is_an_error_on_id() -> None:
    document = _slo_task()
    document["id"] = "no-such-family/" + document["id"].split("/", 1)[1]
    issues, _ = validate_task(document, curriculum=CURRICULUM, families=FAMILIES)
    assert any(i.path == "id" for i in errors_of(issues))


def test_without_a_curriculum_an_slo_task_is_refused_not_passed() -> None:
    issues, spec = validate_task(_slo_task(), curriculum=None, families=None)
    assert spec is None and any("SLO-tagged" in i.message for i in issues)


def test_models_errors_are_issues() -> None:
    assert validate_models(load_yaml(REPO / "models.yaml")) == []
    assert validate_models({"version": 1, "models": "nope"})
    doc = load_yaml(REPO / "models.yaml")
    doc["models"].append(copy.deepcopy(doc["models"][0]))
    assert any("duplicate" in i.message for i in validate_models(doc))


def test_orphaning_mis200_is_an_error_and_title_drift_a_warning() -> None:
    slo = load_yaml(REPO / "curriculum" / "slo.yaml")
    majors = load_yaml(REPO / "curriculum" / "majors.yaml")
    clean = validate_curriculum(slo, majors, FAMILIES)
    assert errors_of(clean) == []
    assert any(i.severity == "warning" for i in clean)  # MIS 200's catalog title

    for major in majors["majors"]:
        major["classes"] = [c for c in major.get("classes") or [] if c["course"] != "MIS 200"]
    issues = validate_curriculum(slo, majors, FAMILIES)
    assert any("MIS 200" in i.message for i in errors_of(issues))


def test_validation_error_strings_split_into_path_and_message() -> None:
    exc = ValidationError("x.yaml", ["samples/3/target: is required", "no colon here"])
    assert issues_from_validation_error(exc) == [
        Issue("samples/3/target", "is required"),
        Issue("", "no colon here"),
    ]


@pytest.mark.parametrize("severity", ["error", "warning"])
def test_issue_as_dict(severity) -> None:
    assert Issue("p", "m", severity).as_dict() == {
        "path": "p",
        "message": "m",
        "severity": severity,
    }
