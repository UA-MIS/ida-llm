"""The tracer bullet, in process. Runs everywhere, needs nothing but Python.

This is the gate on every commit. It assembles the REAL api app, the REAL runner
worker, the REAL harness and the REAL mock-model service, and wires them with
in-process implementations of the queue and artifact-store protocols. Nothing is
mocked; the substitutions are alternative implementations of the same contracts.
"""

from __future__ import annotations

import json
import threading

import httpx
import pytest
from _tracer_assertions import (
    SUBJECTIVE_TASK,
    TERMINAL_STATUSES,
    VERIFIABLE_TASK,
    assert_all_errored_run_is_marked_failed,
    assert_partial_run_is_marked_partial,
    assert_subjective_run_is_unscored_not_zeroed,
    assert_tracer_run_is_complete,
    assert_transcript_is_faithful,
    wait_until,
)
from fastapi.testclient import TestClient

from ida_api.app import create_app
from ida_api.deps import AppContext
from ida_api.slo import load_curriculum_view
from ida_core.artifacts import LocalArtifactStore, eval_log_key, parse_uri
from ida_core.config import Settings, repo_root
from ida_core.db import create_all, make_engine, make_session_factory
from ida_core.queue import InMemoryQueue
from ida_core.registry import load_registry
from ida_harness.client import OpenAICompatibleClient
from ida_harness.tasks import TaskCatalog
from ida_mock_model.responder import Responder
from ida_mock_model.testing import make_transport
from ida_runner.worker import Worker


@pytest.fixture
def stack(tmp_path):
    """The whole platform, assembled in one process."""
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'tracer.db'}",
        artifact_backend="local",
        artifact_local_root=str(tmp_path / "artifacts"),
    )
    engine = make_engine(settings.database_url)
    create_all(engine)

    store = LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    store.ensure_bucket()

    registry = load_registry(repo_root() / "models.yaml")
    catalog = TaskCatalog.from_directory(repo_root() / "tasks")
    queue = InMemoryQueue()
    session_factory = make_session_factory(engine)

    context = AppContext(
        settings=settings,
        session_factory=session_factory,
        queue=queue,
        artifact_store=store,
        registry=registry,
        catalog=catalog,
        git_sha="f" * 40,
        # The real loader against the real repo: `available: false` when this
        # checkout has no curriculum/slo.yaml, which is a state the API serves.
        curriculum=load_curriculum_view(repo_root()),
    )

    transport = make_transport()

    def client_factory() -> OpenAICompatibleClient:
        return OpenAICompatibleClient(registry.get("mock"), transport=transport)

    worker = Worker(
        queue=queue,
        session_factory=session_factory,
        registry=registry,
        catalog=catalog,
        artifact_store=store,
        git_sha="f" * 40,
        poll_timeout_s=1,
        client_factory=client_factory,
    )
    thread = threading.Thread(target=worker.run_forever, daemon=True)
    thread.start()

    api = TestClient(create_app(context))
    try:
        yield api, store
    finally:
        worker.stop()
        thread.join(timeout=10)


def _enqueue(api: TestClient, task_id: str) -> str:
    response = api.post(
        "/runs", json={"task_ids": [task_id], "model_keys": ["mock"], "label": "tracer"}
    )
    assert response.status_code == 202, response.text
    return response.json()["runs"][0]["id"]


def _await_terminal(api: TestClient, run_id: str) -> dict:
    def check() -> dict | None:
        detail = api.get(f"/runs/{run_id}").json()
        return detail if detail["run"]["status"] in TERMINAL_STATUSES else None

    return wait_until(check, timeout_s=30)


class TestTracerBullet:
    """POST /runs -> queue -> runner -> harness -> mock-model -> DB + MinIO -> GET /runs/{id}."""

    def test_end_to_end(self, stack) -> None:
        api, _store = stack
        run_id = _enqueue(api, VERIFIABLE_TASK)

        queued = api.get(f"/runs/{run_id}").json()["run"]
        assert queued["status"] in {"queued", "running", "succeeded"}
        assert queued["task_git_sha"] == "f" * 40, "D-1 provenance is set at enqueue"

        detail = _await_terminal(api, run_id)
        assert_tracer_run_is_complete(detail)

    def test_transcripts_are_served_back_out_of_object_storage(self, stack) -> None:
        api, _store = stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        detail = _await_terminal(api, run_id)

        for result in detail["results"]:
            sample_id = result["sample_id"]
            response = api.get(f"/runs/{run_id}/results/{sample_id}/transcript")
            assert response.status_code == 200
            assert_transcript_is_faithful(response.json(), run_id, sample_id)

    def test_the_full_eval_log_is_archived(self, stack) -> None:
        """A run must be replayable from artifacts alone, not just from Postgres."""
        api, store = stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        _await_terminal(api, run_id)

        eval_log = store.get_json(eval_log_key(run_id))
        assert eval_log["run_id"] == run_id
        assert eval_log["status"] == "succeeded"
        assert len(eval_log["results"]) == 4
        assert len(eval_log["transcripts"]) == 4
        assert eval_log["serving_config"]["model_id"] == "mock-echo-1"
        assert eval_log["task_git_sha"] == "f" * 40

    def test_the_run_appears_in_the_list_the_frontend_renders(self, stack) -> None:
        api, _store = stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        _await_terminal(api, run_id)

        listing = api.get("/runs").json()
        assert listing["runs"][0]["id"] == run_id
        assert listing["runs"][0]["mean_score"] == 1.0
        assert listing["runs"][0]["label"] == "tracer"

    def test_artifact_pointer_resolves_to_a_real_object(self, stack) -> None:
        api, store = stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        detail = _await_terminal(api, run_id)

        for result in detail["results"]:
            bucket, key = parse_uri(result["transcript_uri"])
            assert bucket == store.bucket
            assert store.exists(key), f"dangling artifact pointer: {result['transcript_uri']}"


class TestSubjectiveTracer:
    def test_subjective_run_completes_without_scores(self, stack) -> None:
        api, _store = stack
        run_id = _enqueue(api, SUBJECTIVE_TASK)
        detail = _await_terminal(api, run_id)
        assert_subjective_run_is_unscored_not_zeroed(detail)

    def test_api_explains_why_it_is_unscorable(self, stack) -> None:
        api, _store = stack
        task = next(t for t in api.get("/tasks").json() if t["id"] == SUBJECTIVE_TASK)
        assert task["scorable"] is False
        assert "judge" in task["unscorable_reason"]


class TestMultipleRuns:
    def test_a_sweep_produces_one_independent_run_per_pair(self, stack) -> None:
        api, _store = stack
        response = api.post(
            "/runs",
            json={
                "task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK],
                "model_keys": ["mock"],
                "label": "sweep",
            },
        )
        assert response.status_code == 202
        run_ids = [r["id"] for r in response.json()["runs"]]
        assert len(run_ids) == 2

        details = [_await_terminal(api, run_id) for run_id in run_ids]
        assert all(d["run"]["status"] == "succeeded" for d in details)
        assert details[0]["run"]["mean_score"] == 1.0
        assert details[1]["run"]["mean_score"] is None


@pytest.fixture
def broken_stack(tmp_path):
    """The same stack, with the model endpoint unreachable.

    Everything else is real -- real API, real runner, real persistence. Only the
    transport refuses connections, which is what a dead vLLM box, an expired key
    or a network partition looks like from in here.
    """
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'broken.db'}",
        artifact_backend="local",
        artifact_local_root=str(tmp_path / "artifacts"),
    )
    engine = make_engine(settings.database_url)
    create_all(engine)
    store = LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    store.ensure_bucket()

    registry = load_registry(repo_root() / "models.yaml")
    registry.get("mock").max_retries = 0
    catalog = TaskCatalog.from_directory(repo_root() / "tasks")
    queue = InMemoryQueue()
    session_factory = make_session_factory(engine)

    context = AppContext(
        settings=settings,
        session_factory=session_factory,
        queue=queue,
        artifact_store=store,
        registry=registry,
        catalog=catalog,
        git_sha="f" * 40,
        # The real loader against the real repo: `available: false` when this
        # checkout has no curriculum/slo.yaml, which is a state the API serves.
        curriculum=load_curriculum_view(repo_root()),
    )

    def dead_client_factory() -> OpenAICompatibleClient:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        return OpenAICompatibleClient(
            registry.get("mock"),
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
            jitter=lambda _lo, hi: hi,
        )

    worker = Worker(
        queue=queue,
        session_factory=session_factory,
        registry=registry,
        catalog=catalog,
        artifact_store=store,
        git_sha="f" * 40,
        poll_timeout_s=1,
        client_factory=dead_client_factory,
    )
    thread = threading.Thread(target=worker.run_forever, daemon=True)
    thread.start()
    api = TestClient(create_app(context))
    try:
        yield api
    finally:
        worker.stop()
        thread.join(timeout=10)


class TestBrokenRunIsReportedHonestly:
    """B1/B5 end-to-end: the failure the review reproduced against compose.

    This is the inverse of TestSubjectiveTracer, and the two must never be
    confusable: both produce `mean_score: null`, and exactly one of them means
    "the model was not measured".
    """

    def test_an_unreachable_model_produces_a_failed_run(self, broken_stack) -> None:
        api = broken_stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        detail = _await_terminal(api, run_id)
        assert_all_errored_run_is_marked_failed(detail)

    def test_it_is_not_reported_as_succeeded(self, broken_stack) -> None:
        """The specific regression: `status: succeeded` on a run of failed calls."""
        api = broken_stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        assert _await_terminal(api, run_id)["run"]["status"] != "succeeded"

    def test_the_run_list_shows_the_failure_too(self, broken_stack) -> None:
        """The landing page reads this endpoint; it must not show a green badge."""
        api = broken_stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        _await_terminal(api, run_id)
        row = next(r for r in api.get("/runs").json()["runs"] if r["id"] == run_id)
        assert row["status"] == "failed"
        assert row["error_count"] == 4
        assert row["mean_score"] is None

    def test_the_ui_classifier_would_not_call_it_subjective(self, broken_stack) -> None:
        """Mirrors frontend/src/lib/outcome.ts `classifyRun` in Python.

        The frontend logic is TypeScript and not exercised here, but its INPUTS
        are: this asserts the API reports the fields that classifier needs, with
        the values that make it choose 'all-errored' rather than
        'not-yet-scorable'. If this fails, the UI has lost the signal.
        """
        api = broken_stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        detail = _await_terminal(api, run_id)
        run, results = detail["run"], detail["results"]

        every_sample_unscorable = all(not r["scorable"] for r in results)
        assert not every_sample_unscorable, "would wrongly render 'subjective task'"
        assert run["status"] == "failed" or run["error_count"] > 0


class TestSweepEndToEnd:
    """B9 — the comparison view's query must work against real stored rows."""

    def test_one_request_yields_one_addressable_sweep(self, stack) -> None:
        api, _store = stack
        response = api.post(
            "/runs",
            json={
                "task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK],
                "model_keys": ["mock"],
                "label": "sweep",
            },
        )
        sweep_id = response.json()["sweep_id"]
        for run in response.json()["runs"]:
            _await_terminal(api, run["id"])

        listing = api.get(f"/runs?sweep_id={sweep_id}").json()
        assert listing["total"] == 2
        assert {r["task_id"] for r in listing["runs"]} == {VERIFIABLE_TASK, SUBJECTIVE_TASK}
        assert all(r["status"] == "succeeded" for r in listing["runs"])


@pytest.fixture
def flaky_stack(tmp_path):
    """The full stack against a model that fails the first call and then works.

    The middle case between "everything worked" and "nothing worked", and the
    one a real sweep against a rate-limited API hits constantly.
    """
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'flaky.db'}",
        artifact_backend="local",
        artifact_local_root=str(tmp_path / "artifacts"),
    )
    engine = make_engine(settings.database_url)
    create_all(engine)
    store = LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    store.ensure_bucket()

    registry = load_registry(repo_root() / "models.yaml")
    registry.get("mock").max_retries = 0
    catalog = TaskCatalog.from_directory(repo_root() / "tasks")
    queue = InMemoryQueue()
    session_factory = make_session_factory(engine)

    context = AppContext(
        settings=settings,
        session_factory=session_factory,
        queue=queue,
        artifact_store=store,
        registry=registry,
        catalog=catalog,
        git_sha="f" * 40,
        # The real loader against the real repo: `available: false` when this
        # checkout has no curriculum/slo.yaml, which is a state the API serves.
        curriculum=load_curriculum_view(repo_root()),
    )

    # The mock model's OWN answering logic, called directly rather than over
    # HTTP. Driving the ASGI app through a nested TestClient from inside a
    # MockTransport handler deadlocks (two event-loop portals on one thread),
    # and the fidelity that matters here is the ANSWER, not the transport --
    # which the other tracer tests already cover end to end.
    responder = Responder()
    calls = {"n": 0}

    def flaky_factory() -> OpenAICompatibleClient:
        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="rate limited")
            body = json.loads(request.read())
            answer = responder.answer(body["messages"][-1]["content"])
            return httpx.Response(
                200,
                json={
                    "id": f"chatcmpl-flaky-{calls['n']}",
                    "model": "mock-echo-1",
                    "choices": [{"message": {"role": "assistant", "content": answer}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                },
            )

        return OpenAICompatibleClient(
            registry.get("mock"),
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
            jitter=lambda _lo, hi: hi,
        )

    worker = Worker(
        queue=queue,
        session_factory=session_factory,
        registry=registry,
        catalog=catalog,
        artifact_store=store,
        git_sha="f" * 40,
        poll_timeout_s=1,
        client_factory=flaky_factory,
    )
    thread = threading.Thread(target=worker.run_forever, daemon=True)
    thread.start()
    api = TestClient(create_app(context))
    try:
        yield api
    finally:
        worker.stop()
        thread.join(timeout=10)


class TestPartialRunIsReportedHonestly:
    """B5's middle case: one sample down, three fine. Neither success nor failure."""

    def test_a_flaky_endpoint_produces_a_partial_run(self, flaky_stack) -> None:
        api = flaky_stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        assert_partial_run_is_marked_partial(_await_terminal(api, run_id))

    def test_the_mean_covers_only_the_surviving_samples(self, flaky_stack) -> None:
        """An errored sample is excluded, not scored 0 -- our outage is not the
        model's wrong answer, and scoring it 0 would defame the model."""
        api = flaky_stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        detail = _await_terminal(api, run_id)
        run = detail["run"]
        assert run["mean_score"] == 1.0, "the 3 that ran were all correct"
        assert run["scored_count"] == 3
        assert run["error_count"] == 1

    def test_the_surviving_samples_keep_their_evidence(self, flaky_stack) -> None:
        api = flaky_stack
        run_id = _enqueue(api, VERIFIABLE_TASK)
        results = _await_terminal(api, run_id)["results"]
        survived = [r for r in results if r["error"] is None]
        failed = [r for r in results if r["error"] is not None]
        assert len(survived) == 3 and len(failed) == 1
        assert all(r["transcript_uri"] is not None for r in survived)
        assert all(r["transcript_uri"] is None for r in failed)
