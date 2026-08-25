"""Tests for task loading, including the two failure modes that silently shrink a
suite (and therefore silently inflate every score)."""

import pytest

from ida_harness.tasks import load_tasks


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


VALID = """\
apiVersion: ida.capstone/v1
kind: Task
id: {id}
version: 1
title: T
category: c
prompt: |
  hello
rubric:
  kind: exact
gold: hi
"""


def test_loads_and_sorts_by_id(tmp_path):
    _write(tmp_path / "b.yaml", VALID.format(id="b"))
    _write(tmp_path / "nested" / "a.yaml", VALID.format(id="a"))
    tasks = load_tasks(tmp_path)
    # Deterministic ordering is load-bearing: an unordered suite makes two runs of
    # the SAME commit produce transcripts that diff for no reason.
    assert [t.id for t in tasks] == ["a", "b"]


def test_empty_suite_raises_rather_than_scoring_vacuously(tmp_path):
    with pytest.raises(ValueError, match="empty suite"):
        load_tasks(tmp_path)


def test_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_tasks(tmp_path / "nope")


def test_non_task_document_raises_rather_than_being_skipped(tmp_path):
    # Silently skipping this is the bug that makes the suite quietly smaller.
    _write(tmp_path / "ok.yaml", VALID.format(id="ok"))
    _write(tmp_path / "notes.yaml", "kind: Notes\nid: x\n")
    with pytest.raises(ValueError, match="not a Task document"):
        load_tasks(tmp_path)
