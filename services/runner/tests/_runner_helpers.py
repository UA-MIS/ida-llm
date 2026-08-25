"""Seeding helpers shared by the runner's test modules.

⚠ UNIQUELY NAMED ON PURPOSE. CI runs ONE `pytest` from the repo root across five
distributions that each own a `tests/` directory, so a module called `helpers`
here and a module called `helpers` under services/api would be the same import
name. The `_runner_` prefix is what keeps that from ever happening.

`conftest.py` puts this directory on sys.path, which is what makes
`from _runner_helpers import ...` resolve whether pytest was invoked from the
repo root (CI) or from services/runner (a focused local run).
"""

from __future__ import annotations

from ida_core.contracts import RunJobMessage, RunRecord, RunStatus
from ida_core.db import session_scope, utcnow
from ida_core.ids import new_run_id
from ida_core.repositories import create_run

VERIFIABLE_TASK = "demo/arithmetic-quiz-check"
SUBJECTIVE_TASK = "demo/essay-feedback"


def seed_run(session_factory, task_id: str = VERIFIABLE_TASK, **overrides) -> str:
    run_id = new_run_id()
    base = {
        "id": run_id,
        "status": RunStatus.QUEUED,
        "task_id": task_id,
        "model_key": "mock",
        "harness_version": "0.1.0",
        "task_git_sha": "e" * 40,
    }
    base.update(overrides)
    with session_scope(session_factory) as session:
        create_run(session, RunRecord(**base))
    return run_id


def job_message(run_id: str, task_id: str = VERIFIABLE_TASK, **overrides) -> RunJobMessage:
    base = {
        "run_id": run_id,
        "task_id": task_id,
        "model_key": "mock",
        "enqueued_at": utcnow(),
    }
    base.update(overrides)
    return RunJobMessage(**base)
