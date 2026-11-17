"""``/admin/runs`` and ``/admin/sweeps`` (design 5.6, 10.1): expansion, caps,
estimates, spend confirmation, provenance, and cancel -- queued and running."""

from __future__ import annotations

import pytest
from _admin_helpers import ACTOR, HEADERS, admin_client, admin_context
from sqlalchemy import select

from ida_core.configdb.tables import AuditLogRow
from ida_core.contracts import RunJobMessage, RunStatus
from ida_core.db import RunRow, session_scope
from ida_core.repositories import count_results_for_run
from ida_harness.client import OpenAICompatibleClient
from ida_mock_model.testing import make_transport
from ida_runner import worker as worker_module
from ida_runner.reaper import Reaper
from ida_runner.worker import Worker, execute_job

DEMO = "demo/arithmetic-quiz-check"


@pytest.fixture
def ctx(tmp_path):
    return admin_context(tmp_path)


@pytest.fixture
def client(ctx):
    return admin_client(ctx)


def _launch(client, **body):
    return client.post("/admin/runs", headers=HEADERS, json={"model_keys": ["mock"], **body})


def _row(ctx, run_id: str) -> RunRow:
    with session_scope(ctx.session_factory) as s:
        return s.get(RunRow, run_id)


def test_family_keys_expand_to_the_familys_live_tasks(client, ctx) -> None:
    r = client.post(
        "/admin/runs/estimate",
        headers=HEADERS,
        json={"model_keys": ["mock"], "family_keys": ["demo"]},
    )
    assert r.status_code == 200, r.text
    tasks = {p["task_id"] for p in r.json()["pairs"]}
    assert tasks == {t.id for t in ctx.catalog.all() if t.id.startswith("demo/")}
    assert r.json()["runs"] == len(tasks)


def test_unknown_and_disabled_are_refused_with_nothing_enqueued(client, ctx) -> None:
    assert _launch(client, task_ids=["nope/x"]).status_code == 404
    assert (
        client.post(
            "/admin/runs", headers=HEADERS, json={"model_keys": ["nope"], "task_ids": [DEMO]}
        ).status_code
        == 404
    )
    assert _launch(client, family_keys=["no-such-family"]).status_code == 404
    with session_scope(ctx.session_factory) as s:
        assert s.scalar(select(RunRow.id)) is None


def test_caps_are_hard(tmp_path) -> None:
    client = admin_client(admin_context(tmp_path, sweep_max_runs=1))
    r = client.post(
        "/admin/runs",
        headers=HEADERS,
        json={"model_keys": ["mock"], "family_keys": ["demo"], "confirm_spend_usd": 1e9},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "cap_exceeded"


def test_estimate_basis_is_ceiling_then_history(client, ctx) -> None:
    body = {"model_keys": ["luna"], "task_ids": [DEMO]}
    first = client.post("/admin/runs/estimate", headers=HEADERS, json=body).json()
    assert first["pairs"][0]["basis"] == "ceiling" and first["est_usd_high"] > 0
    with session_scope(ctx.session_factory) as s:
        from ida_core.contracts import RunRecord
        from ida_core.repositories import create_run

        create_run(
            s,
            RunRecord(
                id="run_hist",
                status=RunStatus.SUCCEEDED,
                task_id=DEMO,
                model_key="luna",
                harness_version="t",
                sample_count=4,
            ),
        )
        s.flush()
        row = s.get(RunRow, "run_hist")
        row.prompt_tokens, row.completion_tokens = 400, 40
    second = client.post("/admin/runs/estimate", headers=HEADERS, json=body).json()
    assert second["pairs"][0]["basis"] == "history"
    assert second["est_usd_high"] < first["est_usd_high"]


def test_testing_only_models_need_typed_confirmation(client) -> None:
    r = client.post(
        "/admin/runs", headers=HEADERS, json={"model_keys": ["luna"], "task_ids": [DEMO]}
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "spend_confirmation_required"
    figure = detail["current"]["est_usd_high"]
    ok = client.post(
        "/admin/runs",
        headers=HEADERS,
        json={"model_keys": ["luna"], "task_ids": [DEMO], "confirm_spend_usd": figure},
    )
    assert ok.status_code == 202, ok.text


def test_over_the_ceiling_needs_confirmation(tmp_path) -> None:
    client = admin_client(
        admin_context(tmp_path, admin_run_max_estimated_usd=0.0, sweep_exclude_tags="")
    )
    body = {"model_keys": ["claude-opus-5-5"], "task_ids": [DEMO]}
    estimate = client.post("/admin/runs/estimate", headers=HEADERS, json=body).json()
    assert estimate["needs_confirmation"] is True
    short = client.post(
        "/admin/runs",
        headers=HEADERS,
        json={**body, "confirm_spend_usd": estimate["est_usd_high"] / 2},
    )
    assert short.status_code == 409


def test_mock_needs_no_confirmation_and_records_provenance(client, ctx) -> None:
    r = _launch(client, task_ids=[DEMO], label="smoke")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["queued"] == 1 and body["estimate"]["needs_confirmation"] is False
    row = _row(ctx, body["runs"][0]["id"])
    assert row.launched_by == ACTOR and row.config_revision == 1
    with session_scope(ctx.session_factory) as s:
        audit = s.scalar(select(AuditLogRow).where(AuditLogRow.action == "run.launch"))
        assert audit.entity_id == body["sweep_id"] and audit.config_revision is None
    listed = client.get(f"/admin/runs?launched_by={ACTOR}", headers=HEADERS).json()
    assert [run["id"] for run in listed["runs"]] == [row.id]
    assert listed["runs"][0]["launched_by"] == ACTOR


def test_pagination_cursor(client) -> None:
    for _ in range(3):
        _launch(client, task_ids=[DEMO])
    first = client.get("/admin/runs?limit=2", headers=HEADERS).json()
    assert len(first["runs"]) == 2 and first["next_cursor"]
    second = client.get(
        f"/admin/runs?limit=2&cursor={first['next_cursor']}", headers=HEADERS
    ).json()
    assert len(second["runs"]) == 1 and second["next_cursor"] is None
    ids = [r["id"] for r in first["runs"] + second["runs"]]
    assert len(set(ids)) == 3


def _mock_client_factory(ctx):
    transport = make_transport()
    return lambda: OpenAICompatibleClient(ctx.registry.get("mock"), transport=transport)


def test_cancel_queued_the_worker_acks_and_writes_nothing(client, ctx) -> None:
    run_id = _launch(client, task_ids=[DEMO]).json()["runs"][0]["id"]
    r = client.post(f"/admin/runs/{run_id}/cancel", headers=HEADERS)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    again = client.post(f"/admin/runs/{run_id}/cancel", headers=HEADERS)
    assert again.status_code == 200 and again.json()["status"] == "cancelled"

    worker = Worker(
        queue=ctx.queue,
        session_factory=ctx.session_factory,
        registry=ctx.registry,
        catalog=ctx.catalog,
        artifact_store=ctx.artifact_store,
        client_factory=_mock_client_factory(ctx),
    )
    assert worker.run_forever(max_jobs=1) == 1
    row = _row(ctx, run_id)
    assert row.status == "cancelled" and f"cancelled by {ACTOR}" in row.error
    with session_scope(ctx.session_factory) as s:
        assert count_results_for_run(s, run_id) == 0


def test_cancel_running_keeps_partial_results_and_cost(client, ctx, monkeypatch) -> None:
    run_id = _launch(client, task_ids=[DEMO]).json()["runs"][0]["id"]
    monkeypatch.setattr(worker_module, "CANCEL_POLL_S", 0.0)
    base_factory = _mock_client_factory(ctx)
    calls = {"n": 0}

    class CancellingClient:
        """After the FIRST provider call, an admin presses cancel."""

        def __init__(self) -> None:
            self._inner = base_factory()

        def complete(self, messages, sampling):
            out = self._inner.complete(messages, sampling)
            calls["n"] += 1
            if calls["n"] == 1:
                assert (
                    client.post(f"/admin/runs/{run_id}/cancel", headers=HEADERS).status_code == 200
                )
            return out

        def close(self):
            self._inner.close()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    message = RunJobMessage(
        run_id=run_id, task_id=DEMO, model_key="mock", enqueued_at=_row(ctx, run_id).created_at
    )
    record = execute_job(
        message,
        session_factory=ctx.session_factory,
        registry=ctx.registry,
        catalog=ctx.catalog,
        artifact_store=ctx.artifact_store,
        client_factory=CancellingClient,
    )
    assert record.status is RunStatus.CANCELLED
    row = _row(ctx, run_id)
    assert row.status == "cancelled" and row.error.startswith(f"cancelled by {ACTOR}")
    assert row.cancel_requested_at is not None and row.prompt_tokens > 0
    with session_scope(ctx.session_factory) as s:
        assert count_results_for_run(s, run_id) == 1
    assert calls["n"] == 1


def test_the_reaper_never_resurrects_a_cancelled_run(client, ctx) -> None:
    run_id = _launch(client, task_ids=[DEMO]).json()["runs"][0]["id"]
    client.post(f"/admin/runs/{run_id}/cancel", headers=HEADERS)
    Reaper(queue=ctx.queue, session_factory=ctx.session_factory, stale_run_ttl_s=0).sweep()
    assert _row(ctx, run_id).status == "cancelled"


def test_sweeps_list_detail_and_cancel(client) -> None:
    launched = _launch(client, family_keys=["demo"]).json()
    sweep_id = launched["sweep_id"]
    listed = client.get("/admin/sweeps", headers=HEADERS).json()
    summary = next(s for s in listed["sweeps"] if s["sweep_id"] == sweep_id)
    assert summary["run_count"] == len(launched["runs"]) and summary["launched_by"] == ACTOR
    assert summary["by_status"] == {"queued": len(launched["runs"])}
    detail = client.get(f"/admin/sweeps/{sweep_id}", headers=HEADERS).json()
    assert len(detail["runs"]) == len(launched["runs"])
    cancelled = client.post(f"/admin/sweeps/{sweep_id}/cancel", headers=HEADERS).json()
    assert cancelled["by_status"] == {"cancelled": len(launched["runs"])}
    assert client.get("/admin/sweeps/nope", headers=HEADERS).status_code == 404


def test_admin_run_detail_is_unredacted_and_cancelled_is_not_leaderboard_evidence(
    client, ctx
) -> None:
    run_id = _launch(client, task_ids=[DEMO]).json()["runs"][0]["id"]
    client.post(f"/admin/runs/{run_id}/cancel", headers=HEADERS)
    detail = client.get(f"/admin/runs/{run_id}", headers=HEADERS).json()
    assert detail["run"]["status"] == "cancelled" and detail["results_total"] == 0
    board = client.get(f"/leaderboard?task_id={DEMO}").json()
    assert all(r["run_id"] != run_id for t in board["tasks"] for r in t["results"])
