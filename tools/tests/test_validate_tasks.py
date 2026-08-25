"""Tests for the schema gate itself.

A gate nobody tests is a gate that reports green. These drive
``tools/validate_tasks.py`` exactly the way CI does -- as a script, from the repo
root -- and assert BOTH directions: the shipped content passes, and a malformed
file is actually rejected with a non-zero exit code.

The RULES themselves (all eight, both validation layers) are covered in depth by
``packages/core/tests/test_validation.py``. What is asserted here is the seam CI
depends on: that this path exists, runs, and fails loudly.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "tools" / "validate_tasks.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(VALIDATOR), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_validator_exists_where_ci_invokes_it() -> None:
    # ci.yml and build-and-push.yaml both run `python tools/validate_tasks.py`.
    # If this path ever moves, those two workflows must move with it.
    assert VALIDATOR.is_file()


def test_shipped_content_is_valid() -> None:
    result = _run(REPO_ROOT)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "All authored content is valid." in result.stdout


@pytest.fixture
def content_tree(tmp_path: Path) -> Path:
    """A throwaway copy of the real models.yaml + tasks/ that a test may corrupt."""
    shutil.copy(REPO_ROOT / "models.yaml", tmp_path / "models.yaml")
    shutil.copytree(REPO_ROOT / "tasks", tmp_path / "tasks")
    return tmp_path


def test_a_malformed_task_fails_the_gate(content_tree: Path) -> None:
    victim = next((content_tree / "tasks").rglob("*.yaml"))
    victim.write_text("kind: Task\nthis_is_not: a valid task\n")

    result = _run(content_tree)
    assert result.returncode == 1
    assert "problem(s)" in result.stderr


def test_a_malformed_registry_fails_the_gate(content_tree: Path) -> None:
    (content_tree / "models.yaml").write_text("models: not-a-list\n")

    result = _run(content_tree)
    assert result.returncode == 1
    assert "problem(s)" in result.stderr


def test_an_empty_task_tree_fails_rather_than_passing_vacuously(content_tree: Path) -> None:
    # The failure mode this catches is the nastiest one: a gate that reports
    # green because it found nothing to check.
    shutil.rmtree(content_tree / "tasks")
    (content_tree / "tasks").mkdir()

    result = _run(content_tree)
    assert result.returncode == 1
    assert "no task files found" in result.stderr
