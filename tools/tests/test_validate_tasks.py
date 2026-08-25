"""Tests for the schema gate itself.

A gate nobody tests is a gate that reports green. These assert BOTH directions:
the shipped example suite passes, and each rule actually rejects what it claims.
"""

import shutil
from pathlib import Path

import pytest

from validate_tasks import main

REPO_ROOT = Path(__file__).resolve().parents[2]

VALID_TASK = """\
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

VALID_MODELS = """\
apiVersion: ida.capstone/v1
models:
  - id: mock-echo
    provider: mock
    model: mock-echo-v1
    base_url_env: MOCK_MODEL_BASE_URL
    api_key_env: MOCK_MODEL_API_KEY
    max_tokens: 128
    temperature: 0.0
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "tasks").mkdir()
    (tmp_path / "models.yaml").write_text(VALID_MODELS)
    (tmp_path / "tasks" / "ok.yaml").write_text(VALID_TASK.format(id="ok"))
    return tmp_path


def run(root) -> int:
    return main(["--root", str(root)])


def test_the_shipped_suite_is_valid():
    # Guards against the example tasks rotting out of sync with the schema.
    assert run(REPO_ROOT) == 0


def test_valid_fixture_passes(repo):
    assert run(repo) == 0


def test_empty_task_dir_fails(repo):
    (repo / "tasks" / "ok.yaml").unlink()
    assert run(repo) == 1


def test_id_must_match_filename_stem(repo):
    (repo / "tasks" / "ok.yaml").write_text(VALID_TASK.format(id="different"))
    assert run(repo) == 1


def test_duplicate_ids_fail(repo):
    shutil.copy(repo / "tasks" / "ok.yaml", repo / "tasks" / "copy.yaml")
    (repo / "tasks" / "copy.yaml").write_text(VALID_TASK.format(id="ok"))
    assert run(repo) == 1


def test_judge_model_must_exist_in_models_yaml(repo):
    (repo / "tasks" / "j.yaml").write_text(
        "apiVersion: ida.capstone/v1\nkind: Task\nid: j\nversion: 1\ntitle: T\n"
        "category: c\nprompt: |\n  q\nrubric:\n  kind: judge\n"
        "  judge_model: ghost-model\n  criteria: [a]\n"
    )
    assert run(repo) == 1


def test_judge_model_that_exists_passes(repo):
    (repo / "tasks" / "j.yaml").write_text(
        "apiVersion: ida.capstone/v1\nkind: Task\nid: j\nversion: 1\ntitle: T\n"
        "category: c\nprompt: |\n  q\nrubric:\n  kind: judge\n"
        "  judge_model: mock-echo\n  criteria: [a]\n"
    )
    assert run(repo) == 0


def test_pasted_api_key_is_rejected(repo):
    # RULE 8. `api_key_env` names a variable; a literal key is not [A-Z0-9_].
    (repo / "models.yaml").write_text(
        VALID_MODELS.replace("api_key_env: MOCK_MODEL_API_KEY", "api_key_env: sk-live-abc123")
    )
    assert run(repo) == 1


def test_gold_required_for_non_judge(repo):
    (repo / "tasks" / "ok.yaml").write_text(VALID_TASK.format(id="ok").replace("gold: hi\n", ""))
    assert run(repo) == 1
