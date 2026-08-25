"""Task loading and the catalog. Bad task files must fail loudly at load time."""

from __future__ import annotations

import pytest

from ida_core.config import repo_root
from ida_harness.errors import TaskLoadError
from ida_harness.tasks import TaskCatalog, load_task_file

VALID = """
version: 1
id: t/one
title: One
kind: verifiable
scorer: {kind: exact_match}
samples:
  - {id: s1, input: q, target: a}
"""


class TestLoadTaskFile:
    def test_loads_a_valid_file(self, tmp_path) -> None:
        path = tmp_path / "t.yaml"
        path.write_text(VALID)
        assert load_task_file(path).id == "t/one"

    def test_missing_file(self, tmp_path) -> None:
        with pytest.raises(TaskLoadError, match="not found"):
            load_task_file(tmp_path / "nope.yaml")

    def test_unparseable_yaml(self, tmp_path) -> None:
        path = tmp_path / "t.yaml"
        path.write_text("key: [unclosed\n")
        with pytest.raises(TaskLoadError, match="could not parse YAML"):
            load_task_file(path)

    def test_non_mapping_top_level(self, tmp_path) -> None:
        path = tmp_path / "t.yaml"
        path.write_text("- just\n- a list\n")
        with pytest.raises(TaskLoadError, match="must be a mapping"):
            load_task_file(path)

    def test_schema_violation(self, tmp_path) -> None:
        path = tmp_path / "t.yaml"
        path.write_text(VALID.replace("kind: verifiable", "kind: telepathic"))
        with pytest.raises(TaskLoadError):
            load_task_file(path)

    def test_semantic_violation_caught_by_pydantic(self, tmp_path) -> None:
        """A rule the schema also enforces -- both layers must reject it."""
        path = tmp_path / "t.yaml"
        path.write_text(VALID.replace(", target: a", ""))
        with pytest.raises(TaskLoadError):
            load_task_file(path)

    def test_yaml_is_loaded_safely(self, tmp_path) -> None:
        """Task files are authored content; they must not construct Python objects."""
        path = tmp_path / "t.yaml"
        path.write_text("!!python/object/apply:os.system ['echo pwned']\n")
        with pytest.raises(TaskLoadError):
            load_task_file(path)


class TestTaskCatalog:
    def test_indexes_the_shipped_tasks(self) -> None:
        catalog = TaskCatalog.from_directory(repo_root() / "tasks")
        assert catalog.ids() == ["demo/arithmetic-quiz-check", "demo/essay-feedback"]
        assert len(catalog) == 2

    def test_membership_and_lookup(self) -> None:
        catalog = TaskCatalog.from_directory(repo_root() / "tasks")
        assert "demo/arithmetic-quiz-check" in catalog
        assert "nope" not in catalog
        assert catalog.get("demo/arithmetic-quiz-check").kind.value == "verifiable"
        with pytest.raises(KeyError, match="no task"):
            catalog.get("nope")

    def test_source_of_reports_the_file(self) -> None:
        catalog = TaskCatalog.from_directory(repo_root() / "tasks")
        assert catalog.source_of("demo/essay-feedback").name == "essay-feedback.yaml"

    def test_duplicate_task_ids_across_files_are_rejected(self, tmp_path) -> None:
        (tmp_path / "a.yaml").write_text(VALID)
        (tmp_path / "b.yaml").write_text(VALID)
        with pytest.raises(TaskLoadError, match="duplicate task id"):
            TaskCatalog.from_directory(tmp_path)

    def test_one_bad_file_fails_the_whole_catalog(self, tmp_path) -> None:
        """Startup failure beats a mystery 500 on someone's first run."""
        (tmp_path / "good.yaml").write_text(VALID)
        (tmp_path / "bad.yaml").write_text("version: 1\nid: broken\n")
        with pytest.raises(TaskLoadError):
            TaskCatalog.from_directory(tmp_path)

    def test_empty_directory_yields_empty_catalog(self, tmp_path) -> None:
        assert len(TaskCatalog.from_directory(tmp_path)) == 0

    def test_demo_tasks_cover_both_kinds(self) -> None:
        catalog = TaskCatalog.from_directory(repo_root() / "tasks")
        assert {t.kind.value for t in catalog.all()} == {"verifiable", "subjective"}
        assert [t.is_scorable for t in catalog.all()] == [True, False]
