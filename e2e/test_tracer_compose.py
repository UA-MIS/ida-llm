"""The tracer bullet against the real docker-compose stack.

Run with ``make tracer`` (which brings the stack up first). Skipped
automatically when the API is not reachable, so ``make test`` and CI stay green
on a machine without Docker -- the in-process mode
(``test_tracer_inprocess.py``) is the commit gate.

The assertions are IMPORTED from conftest and are byte-identical to the
in-process ones. What this mode adds is proof that the containers, the compose
network, the real Redis, the real Postgres and the real MinIO are wired right.
"""

from __future__ import annotations

import os

import httpx
import pytest
from _tracer_assertions import (
    SUBJECTIVE_TASK,
    TERMINAL_STATUSES,
    VERIFIABLE_TASK,
    assert_subjective_run_is_unscored_not_zeroed,
    assert_tracer_run_is_complete,
    assert_transcript_is_faithful,
    wait_until,
)

API_BASE = os.environ.get("IDA_E2E_API_BASE", "http://localhost:8000")
STARTUP_TIMEOUT_S = float(os.environ.get("IDA_E2E_TIMEOUT_S", "120"))


def _api_is_up() -> bool:
    try:
        response = httpx.get(f"{API_BASE}/health", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200 and response.json().get("status") == "ok"


pytestmark = pytest.mark.skipif(
    not _api_is_up(),
    reason=f"no healthy API at {API_BASE}; run `make dev` first (or use `make tracer`)",
)


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
        yield client


def _enqueue(api: httpx.Client, task_id: str) -> str:
    response = api.post(
        "/runs",
        json={"task_ids": [task_id], "model_keys": ["mock"], "label": "tracer-compose"},
    )
    assert response.status_code == 202, response.text
    return response.json()["runs"][0]["id"]


def _await_terminal(api: httpx.Client, run_id: str) -> dict:
    def check() -> dict | None:
        detail = api.get(f"/runs/{run_id}").json()
        return detail if detail["run"]["status"] in TERMINAL_STATUSES else None

    return wait_until(check, timeout_s=STARTUP_TIMEOUT_S)


class TestStackHealth:
    def test_api_reports_every_dependency_healthy(self, api: httpx.Client) -> None:
        body = api.get("/health").json()
        assert body["status"] == "ok"
        # Pinned as a SUPERSET check, not equality: what matters is that each of
        # these three is genuinely reachable across real containers. Adding a
        # fourth dependency later should not fail this test -- reporting one of
        # these as down, or dropping it from the report entirely, should.
        assert {"database", "queue", "artifacts"} <= set(body["checks"])
        assert all(body["checks"].values()), body["checks"]

    def test_the_probe_contract_holds_against_the_real_container(self, api: httpx.Client) -> None:
        """/healthz and /readyz are what the CHART probes.

        The unit suite proves the split in-process; this proves the paths
        actually answer on the port the Deployment exposes. A liveness probe
        pointed at a 404 fails every pod, forever, and does it only in the
        cluster -- which is the most expensive place to find out.
        """
        liveness = api.get("/healthz")
        assert liveness.status_code == 200
        assert liveness.json()["status"] == "ok"
        # Liveness must not report dependencies -- it must not have LOOKED.
        assert liveness.json()["checks"] == {}

        readiness = api.get("/readyz")
        assert readiness.status_code == 200
        assert readiness.json()["checks"], "readiness must actually check something"

    def test_metrics_is_scrapeable_from_outside_the_container(self, api: httpx.Client) -> None:
        """ServiceMonitor `ida-llm-api` scrapes this path on the `http` port."""
        response = api.get("/metrics")
        assert response.status_code == 200
        assert "ida_llm_api_requests_total" in response.text

    def test_registry_and_catalog_loaded_in_the_container(self, api: httpx.Client) -> None:
        assert [m["key"] for m in api.get("/models").json()] == ["mock"]
        # A superset, not an equality: the container ships whatever is in
        # `tasks/`, which grows as families are authored. What this asserts is
        # that the catalog loaded at all and that the two tasks the tracer runs
        # below are in it.
        assert {VERIFIABLE_TASK, SUBJECTIVE_TASK} <= {t["id"] for t in api.get("/tasks").json()}


class TestTracerBullet:
    """The full path across real containers, real Redis, real Postgres, real MinIO."""

    def test_end_to_end(self, api: httpx.Client) -> None:
        run_id = _enqueue(api, VERIFIABLE_TASK)
        detail = _await_terminal(api, run_id)
        assert_tracer_run_is_complete(detail)

    def test_transcripts_come_back_out_of_minio(self, api: httpx.Client) -> None:
        run_id = _enqueue(api, VERIFIABLE_TASK)
        detail = _await_terminal(api, run_id)
        for result in detail["results"]:
            sample_id = result["sample_id"]
            response = api.get(f"/runs/{run_id}/results/{sample_id}/transcript")
            assert response.status_code == 200, response.text
            assert_transcript_is_faithful(response.json(), run_id, sample_id)

    def test_run_shows_up_in_the_list_endpoint(self, api: httpx.Client) -> None:
        run_id = _enqueue(api, VERIFIABLE_TASK)
        _await_terminal(api, run_id)
        listing = api.get("/runs?limit=50").json()
        assert run_id in {r["id"] for r in listing["runs"]}

    def test_git_sha_was_baked_into_the_image(self, api: httpx.Client) -> None:
        """D-1: a container has no .git, so the SHA must come from the build arg."""
        run_id = _enqueue(api, VERIFIABLE_TASK)
        run = _await_terminal(api, run_id)["run"]
        if run["task_git_sha"] is None:
            pytest.skip("image built without GIT_SHA; set it in the build pipeline")
        assert len(run["task_git_sha"]) == 40


class TestSubjectiveTracer:
    def test_completes_without_scores(self, api: httpx.Client) -> None:
        run_id = _enqueue(api, SUBJECTIVE_TASK)
        assert_subjective_run_is_unscored_not_zeroed(_await_terminal(api, run_id))


class TestFrontend:
    """Build-level coverage: the page renders and its API contract holds.

    No browser automation -- proving the skeleton is wired does not need it, and
    a headless browser in CI is a maintenance cost the walking skeleton has not
    earned yet.
    """

    def test_frontend_serves_the_run_list(self) -> None:
        frontend_base = os.environ.get("IDA_E2E_FRONTEND_BASE", "http://localhost:3000")
        try:
            response = httpx.get(frontend_base, timeout=10.0, follow_redirects=True)
        except httpx.HTTPError:
            pytest.skip(f"no frontend at {frontend_base}")
        assert response.status_code == 200
        assert "Capstone-IDA" in response.text
