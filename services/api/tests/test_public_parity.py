"""**The public site is identical after seeding** (design 4.3, 10.1).

Two apps over the SAME database rows (runs and results) and the same YAML: one
in ``IDA_CONFIG_SOURCE=yaml`` (today), one in ``db`` after ``ensure_seeded``.
Every public read must return byte-identical JSON. If the database path lost a
field, reordered models, re-hashed a task or mis-rebuilt a class, the response
bytes differ and this fails -- which is the evidence that flipping an
environment to ``db`` changes nothing a visitor can see.

Run for the real config AND the dev set (dev overrides, demo units).
"""

from __future__ import annotations

import shutil

import pytest
from _dashboard_helpers import (
    COMPLETE_TEACHING_ANSWERS,
    GRADING_TASK,
    QUIZ_TASK,
    VERIFIABLE_TASK,
    seed_run,
)
from fastapi.testclient import TestClient

from ida_api.app import create_app
from ida_api.deps import AppContext
from ida_api.slo import load_curriculum_view
from ida_core.artifacts import LocalArtifactStore
from ida_core.config import Settings, repo_root
from ida_core.configdb.tables import ModelRow, TaskRow
from ida_core.db import create_all, make_engine, make_session_factory, session_scope
from ida_core.queue import InMemoryQueue
from ida_harness.config_provider import build_provider

REPO = repo_root()

PUBLIC_GETS = [
    "/models",
    "/models?include_disabled=true",
    "/tasks",
    f"/tasks/{VERIFIABLE_TASK}",
    f"/tasks/{QUIZ_TASK}",
    "/leaderboard",
    "/leaderboard?benchmark=true",
    "/curriculum",
]


def _dev_overrides(tmp_path) -> dict:
    tasks_all = tmp_path / "tasks-all"
    shutil.copytree(REPO / "tasks", tasks_all)
    shutil.copytree(REPO / "tasks-dev", tasks_all, dirs_exist_ok=True)
    return {
        "models_file": str(REPO / "models.dev.yaml"),
        "tasks_dir": str(tasks_all),
        "majors_file": str(REPO / "curriculum" / "majors.dev.yaml"),
        "curriculum_file": str(REPO / "curriculum" / "slo.dev.yaml"),
        "units_file": str(REPO / "curriculum" / "units.dev.yaml"),
    }


def _pair(tmp_path, *, dev: bool) -> tuple[TestClient, TestClient, AppContext]:
    base = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'parity.db'}",
        artifact_backend="local",
        artifact_local_root=str(tmp_path / "artifacts"),
        **(_dev_overrides(tmp_path) if dev else {}),
    )
    engine = make_engine(base.database_url)
    create_all(engine)
    factory = make_session_factory(engine)
    store = LocalArtifactStore(base.artifact_local_root, bucket=base.s3_bucket)
    store.ensure_bucket()

    yaml_settings = base.model_copy(update={"config_source": "yaml"})
    yaml_ctx = AppContext(
        settings=yaml_settings,
        session_factory=factory,
        queue=InMemoryQueue(),
        artifact_store=store,
        config=build_provider(yaml_settings, factory),
        curriculum=load_curriculum_view(
            REPO,
            curriculum_path=yaml_settings.resolved_curriculum_file(),
            majors_path=yaml_settings.resolved_majors_file(),
            units_path=yaml_settings.resolved_units_file(),
        ),
    )
    db_settings = base.model_copy(update={"config_source": "db"})
    db_ctx = AppContext(
        settings=db_settings,
        session_factory=factory,
        queue=InMemoryQueue(),
        artifact_store=store,
        config=build_provider(db_settings, factory),
    )
    # Real evidence on the board, so the leaderboard and the recommender have
    # something to aggregate and rank.
    for offset, (task, model) in enumerate(
        [(VERIFIABLE_TASK, "mock"), (QUIZ_TASK, "mock"), (GRADING_TASK, "luna")]
    ):
        seed_run(yaml_ctx, task_id=task, model_key=model, created_offset_minutes=offset)
    return TestClient(create_app(yaml_ctx)), TestClient(create_app(db_ctx)), db_ctx


@pytest.mark.parametrize("dev", [False, True], ids=["real", "dev"])
def test_every_public_read_is_byte_identical(tmp_path, dev: bool) -> None:
    yaml_client, db_client, _ = _pair(tmp_path, dev=dev)
    for path in PUBLIC_GETS:
        a, b = yaml_client.get(path), db_client.get(path)
        assert a.status_code == b.status_code == 200, path
        assert a.content == b.content, path
    for body in ({"answers": COMPLETE_TEACHING_ANSWERS}, {"answers": {}}):
        a, b = yaml_client.post("/recommend", json=body), db_client.post("/recommend", json=body)
        assert a.status_code == b.status_code
        assert a.content == b.content


def test_the_curriculum_carries_units_in_both_modes(tmp_path) -> None:
    yaml_client, db_client, _ = _pair(tmp_path, dev=False)
    units = db_client.get("/curriculum").json()["units"]
    assert [u["n"] for u in units["MIS 200"]] == [1, 2, 3, 4, 5]
    assert "OM 300" in units
    assert yaml_client.get("/curriculum").json()["units"] == units


def test_targets_stay_redacted_after_an_admin_edit(tmp_path) -> None:
    """An edited task served from the database is still redacted publicly."""
    _, db_client, db_ctx = _pair(tmp_path, dev=False)
    with session_scope(db_ctx.session_factory) as session:
        row = session.get(TaskRow, VERIFIABLE_TASK)
        row.document = {**row.document, "title": "Edited title"}
        from ida_core.configdb.tables import ConfigRevisionRow

        session.add(ConfigRevisionRow(actor="octo", source="admin", summary="edit"))
    db_ctx.config._checked_at = float("-inf")  # skip the 5 s refresh wait
    body = db_client.get(f"/tasks/{VERIFIABLE_TASK}").json()
    assert body["title"] == "Edited title"
    assert body["targets_redacted"] is True
    assert all(s.get("target") is None for s in body["samples"])


def test_a_hidden_model_leaves_the_public_reads(tmp_path) -> None:
    _, db_client, db_ctx = _pair(tmp_path, dev=False)
    assert "mock" in {m["key"] for m in db_client.get("/models").json()}
    with session_scope(db_ctx.session_factory) as session:
        session.get(ModelRow, "mock").hidden = True
        from ida_core.configdb.tables import ConfigRevisionRow

        session.add(ConfigRevisionRow(actor="octo", source="admin", summary="hide"))
    db_ctx.config._checked_at = float("-inf")
    assert "mock" not in {m["key"] for m in db_client.get("/models").json()}
    keys_before = {"mock"}  # seeded evidence above includes mock runs
    board = db_client.get("/leaderboard").json()
    served = {r["model_key"] for t in board["tasks"] for r in t["results"]}
    assert served, "the board should still show the other seeded run"
    assert keys_before.isdisjoint(served)
