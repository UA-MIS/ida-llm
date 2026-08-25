"""API contract tests: every documented route, plus the enqueue invariants."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ida_api.deps import AppContext
from ida_core.contracts import (
    ResultRecord,
    RunRecord,
    RunStatus,
    Score,
    ScorerKind,
    ServingConfig,
    ServingStack,
    TokenUsage,
)
from ida_core.db import session_scope
from ida_core.ids import new_result_id, new_run_id
from ida_core.repositories import create_run, insert_results

VERIFIABLE_TASK = "demo/arithmetic-quiz-check"
SUBJECTIVE_TASK = "demo/essay-feedback"


class DeadQueue:
    """A queue whose every liveness answer is an outage."""

    def enqueue(self, message): ...
    def dequeue(self, timeout_s=5):
        return None

    def depth(self):
        return 0

    def ping(self):
        raise ConnectionError("redis is gone")


class TestHealth:
    """The /healthz + /readyz split is a DEPLOYMENT CONTRACT.

    The chart probes /healthz for liveness (20s/20s) and /readyz for readiness
    (5s/10s). If liveness ever starts checking a dependency, a brief database
    blip restarts every replica instead of merely removing them from the
    Service -- a small outage becomes a large one. These tests are what stops
    that from being a one-line change nobody notices.
    """

    def test_readyz_reports_each_dependency(self, client: TestClient) -> None:
        response = client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["checks"] == {"database": True, "queue": True, "artifacts": True}

    def test_health_is_readyz_body_at_200(self, client: TestClient) -> None:
        assert client.get("/health").json() == client.get("/readyz").json()

    def test_healthz_is_ok_and_checks_nothing(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["checks"] == {}

    def test_healthz_never_touches_a_dependency(self, context: AppContext) -> None:
        """THE guard the README advertises.

        Every dependency is replaced with one that raises on contact, and
        liveness must still answer 200. If someone adds a `SELECT 1` to
        /healthz, this is the test that fails.
        """
        from ida_api.app import create_app

        class Exploding:
            def __getattr__(self, name):
                def _boom(*args, **kwargs):
                    raise AssertionError(
                        f"/healthz touched a dependency ({name}); liveness must not"
                    )

                return _boom

        context.queue = Exploding()
        context.artifact_store = Exploding()
        context.session_factory = Exploding()

        response = TestClient(create_app(context)).get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readyz_returns_503_when_a_dependency_is_down(self, context: AppContext) -> None:
        """503, not 200-with-a-sad-body.

        The chart's readinessProbe reads the STATUS CODE. Returning 200 while
        degraded would leave a pod with a dead database in the Service, serving
        500s to real traffic.
        """
        from ida_api.app import create_app

        context.queue = DeadQueue()
        response = TestClient(create_app(context)).get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["queue"] is False
        assert body["checks"]["database"] is True

    def test_every_check_runs_even_when_an_earlier_one_fails(self, context: AppContext) -> None:
        """A report that stops at the first failure hides the second.

        "The queue is down" and "the queue AND the object store are down" are
        different incidents, and the probe body is often the only evidence
        anyone has at 2am.
        """
        from ida_api.app import create_app

        class DeadStore:
            def ensure_bucket(self):
                raise OSError("minio is gone")

        context.queue = DeadQueue()
        context.artifact_store = DeadStore()
        body = TestClient(create_app(context)).get("/readyz").json()
        assert body["checks"] == {"database": True, "queue": False, "artifacts": False}

    def test_metrics_is_exposed_for_the_servicemonitor(self, client: TestClient) -> None:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]

    def test_requests_are_counted_by_route_template_not_raw_path(self, client: TestClient) -> None:
        """Unbounded label cardinality takes Prometheus down, not the app.

        A benchmark platform mints run ids without limit, so labelling by raw
        path would mint a time series per run.
        """
        client.get("/runs/run_does_not_exist")
        body = client.get("/metrics").text
        assert 'route="/runs/{run_id}"' in body
        assert "run_does_not_exist" not in body


class TestModelsEndpoint:
    def test_lists_enabled_models(self, client: TestClient) -> None:
        models = client.get("/models").json()
        assert [m["key"] for m in models] == ["mock"]

    def test_exposes_only_the_whitelisted_fields(self, client: TestClient) -> None:
        """Pinned literally: adding a field to ModelEntry must not leak it by default."""
        model = client.get("/models").json()[0]
        assert set(model) == {
            "key",
            "display_name",
            "base_url",
            "enabled",
            "requires_api_key",
            "serving_stack",
            "model_id",
            "quantization",
            "tags",
        }
        assert model["requires_api_key"] is False

    def test_never_exposes_a_secret_or_the_env_var_name(
        self, client: TestClient, context: AppContext, monkeypatch
    ) -> None:
        """The registry knows an env var NAME; neither it nor its value may escape."""
        monkeypatch.setenv("SECRET_MODEL_KEY", "sk-live-do-not-leak")
        context.registry.get("mock").api_key_env = "SECRET_MODEL_KEY"
        body = client.get("/models").text
        assert "sk-live-do-not-leak" not in body
        assert "SECRET_MODEL_KEY" not in body
        assert client.get("/models").json()[0]["requires_api_key"] is True

    def test_exposes_serving_metadata(self, client: TestClient) -> None:
        model = client.get("/models").json()[0]
        assert model["serving_stack"] == "mock"
        assert model["model_id"] == "mock-echo-1"
        assert model["quantization"] == "none"


class TestTasksEndpoint:
    def test_lists_both_demo_tasks(self, client: TestClient) -> None:
        tasks = client.get("/tasks").json()
        assert [t["id"] for t in tasks] == [VERIFIABLE_TASK, SUBJECTIVE_TASK]

    def test_verifiable_task_is_scorable(self, client: TestClient) -> None:
        task = next(t for t in client.get("/tasks").json() if t["id"] == VERIFIABLE_TASK)
        assert task["scorable"] is True
        assert task["unscorable_reason"] is None
        assert task["scorer"] == "numeric_match"
        assert task["sample_count"] == 4

    def test_subjective_task_explains_why_it_is_not_scorable(self, client: TestClient) -> None:
        """The UI must be able to say 'not yet scorable', not show a misleading zero."""
        task = next(t for t in client.get("/tasks").json() if t["id"] == SUBJECTIVE_TASK)
        assert task["scorable"] is False
        assert "judge" in task["unscorable_reason"]

    def test_get_one_task_returns_the_spec_with_targets_redacted(self, client: TestClient) -> None:
        """A10: the answer key must not be published on an unauthenticated read."""
        body = client.get(f"/tasks/{VERIFIABLE_TASK}").json()
        assert body["targets_redacted"] is True
        assert body["id"] == VERIFIABLE_TASK
        assert len(body["samples"]) == 4, "the task text is still fully available"
        assert all(sample["target"] is None for sample in body["samples"])
        assert all(sample["has_target"] is True for sample in body["samples"]), (
            "the client still learns an answer key EXISTS -- just not what it is"
        )
        assert "42" not in client.get(f"/tasks/{VERIFIABLE_TASK}").text

    def test_anonymous_cannot_request_targets(self, client: TestClient) -> None:
        """Fail shut: with no auth, nobody holds `author`, so nobody sees the key."""
        response = client.get(f"/tasks/{VERIFIABLE_TASK}?include_targets=true")
        assert response.status_code == 403
        assert "author" in response.json()["detail"]

    def test_author_role_gets_the_unredacted_spec(self, context: AppContext) -> None:
        """The gate is a role check, so real auth only has to grant the role."""
        from ida_api.app import create_app
        from ida_api.auth import Principal, current_principal

        author = Principal(
            subject="prof",
            display_name="Author",
            is_anonymous=False,
            roles=frozenset({"reader", "runner", "author"}),
        )
        app = create_app(context)
        app.dependency_overrides[current_principal] = lambda: author
        body = TestClient(app).get(f"/tasks/{VERIFIABLE_TASK}?include_targets=true").json()
        assert body["targets_redacted"] is False
        assert body["samples"][0]["target"] == "42"

    def test_content_sha_is_exposed_for_comparability(self, client: TestClient) -> None:
        """B8: a consumer must be able to ask 'is this the same task text?'."""
        body = client.get(f"/tasks/{VERIFIABLE_TASK}").json()
        assert len(body["content_sha"]) == 64

    def test_unknown_task_404s(self, client: TestClient) -> None:
        assert client.get("/tasks/nope/nope").status_code == 404


class TestEnqueue:
    def test_creates_one_queued_run_per_pair(self, client: TestClient, context: AppContext) -> None:
        response = client.post(
            "/runs",
            json={
                "task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK],
                "model_keys": ["mock"],
                "label": "sweep",
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["queued"] == 2
        assert len(body["runs"]) == 2
        assert {r["status"] for r in body["runs"]} == {"queued"}
        assert {r["label"] for r in body["runs"]} == {"sweep"}
        assert context.queue.depth() == 2

    def test_run_ids_are_unique_and_returned_to_the_caller(self, client: TestClient) -> None:
        runs = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        ).json()["runs"]
        assert runs[0]["id"].startswith("run_")

    def test_queue_message_carries_the_same_run_id(
        self, client: TestClient, context: AppContext
    ) -> None:
        """The id is minted before enqueue precisely so these two agree."""
        run_id = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        ).json()["runs"][0]["id"]
        message = context.queue.dequeue(timeout_s=0)
        assert message is not None
        assert message.run_id == run_id
        assert message.task_id == VERIFIABLE_TASK
        assert message.model_key == "mock"
        assert message.schema_version == 1

    def test_records_the_git_sha(self, client: TestClient) -> None:
        run = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        ).json()["runs"][0]
        assert run["task_git_sha"] == "d" * 40

    def test_sample_count_is_populated_up_front(self, client: TestClient) -> None:
        run = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        ).json()["runs"][0]
        assert run["sample_count"] == 4

    def test_sampling_override_reaches_the_queue(
        self, client: TestClient, context: AppContext
    ) -> None:
        client.post(
            "/runs",
            json={
                "task_ids": [VERIFIABLE_TASK],
                "model_keys": ["mock"],
                "sampling_override": {"temperature": 0.7, "max_tokens": 16},
            },
        )
        message = context.queue.dequeue(timeout_s=0)
        assert message.sampling_override.temperature == 0.7

    def test_unknown_task_404s_and_enqueues_nothing(
        self, client: TestClient, context: AppContext
    ) -> None:
        """Validate-then-write: a typo must not leave half a sweep running."""
        response = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK, "nope"], "model_keys": ["mock"]}
        )
        assert response.status_code == 404
        assert context.queue.depth() == 0
        assert client.get("/runs").json()["runs"] == []

    def test_unknown_model_404s_and_enqueues_nothing(
        self, client: TestClient, context: AppContext
    ) -> None:
        response = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["ghost"]}
        )
        assert response.status_code == 404
        assert context.queue.depth() == 0

    def test_disabled_model_409s(self, client: TestClient, context: AppContext) -> None:
        context.registry.get("mock").enabled = False
        response = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        )
        assert response.status_code == 409

    @pytest.mark.parametrize(
        "payload",
        [
            {"task_ids": [], "model_keys": ["mock"]},
            {"task_ids": [VERIFIABLE_TASK], "model_keys": []},
            {"task_ids": [VERIFIABLE_TASK]},
            {"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"], "surprise": 1},
        ],
    )
    def test_malformed_requests_are_422(self, client: TestClient, payload: dict) -> None:
        assert client.post("/runs", json=payload).status_code == 422


class TestListRuns:
    def test_empty_initially(self, client: TestClient) -> None:
        body = client.get("/runs").json()
        assert body == {"runs": [], "total": 0, "limit": 50, "offset": 0}

    def test_total_counts_all_matches_not_just_the_page(self, client: TestClient) -> None:
        """A11: a UI cannot paginate without knowing how many rows exist."""
        client.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK], "model_keys": ["mock"]},
        )
        body = client.get("/runs?limit=1").json()
        assert len(body["runs"]) == 1
        assert body["total"] == 2

    def test_total_respects_filters(self, client: TestClient) -> None:
        client.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK], "model_keys": ["mock"]},
        )
        assert client.get(f"/runs?task_id={VERIFIABLE_TASK}").json()["total"] == 1
        assert client.get("/runs?status=failed").json()["total"] == 0

    def test_newest_first(self, client: TestClient) -> None:
        client.post("/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]})
        client.post("/runs", json={"task_ids": [SUBJECTIVE_TASK], "model_keys": ["mock"]})
        runs = client.get("/runs").json()["runs"]
        assert runs[0]["task_id"] == SUBJECTIVE_TASK

    def test_filters(self, client: TestClient) -> None:
        client.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK], "model_keys": ["mock"]},
        )
        assert len(client.get(f"/runs?task_id={VERIFIABLE_TASK}").json()["runs"]) == 1
        assert len(client.get("/runs?status=queued").json()["runs"]) == 2
        assert len(client.get("/runs?status=succeeded").json()["runs"]) == 0
        assert len(client.get("/runs?model_key=ghost").json()["runs"]) == 0

    def test_limit_is_capped(self, client: TestClient) -> None:
        """An accidental full-table scan should be impossible from the outside."""
        assert client.get("/runs?limit=201").status_code == 422
        assert client.get("/runs?limit=200").status_code == 200

    def test_pagination(self, client: TestClient) -> None:
        client.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK], "model_keys": ["mock"]},
        )
        assert len(client.get("/runs?limit=1").json()["runs"]) == 1
        assert len(client.get("/runs?limit=1&offset=1").json()["runs"]) == 1
        assert len(client.get("/runs?limit=1&offset=5").json()["runs"]) == 0


class TestRunDetail:
    def _seed(self, context: AppContext) -> str:
        run_id = new_run_id()
        serving = ServingConfig(
            model_id="mock-echo-1", registry_key="mock", serving_stack=ServingStack.MOCK
        )
        with session_scope(context.session_factory) as session:
            create_run(
                session,
                RunRecord(
                    id=run_id,
                    status=RunStatus.SUCCEEDED,
                    task_id=VERIFIABLE_TASK,
                    model_key="mock",
                    harness_version="0.1.0",
                    serving_config=serving,
                    sample_count=1,
                    scored_count=1,
                    mean_score=1.0,
                ),
            )
            insert_results(
                session,
                [
                    ResultRecord(
                        id=new_result_id(),
                        run_id=run_id,
                        task_id=VERIFIABLE_TASK,
                        sample_id="add-simple",
                        model_key="mock",
                        serving_config=serving,
                        score=Score(
                            scorer=ScorerKind.NUMERIC_MATCH,
                            value=1.0,
                            passed=True,
                            explanation="got 42, want 42",
                        ),
                        usage=TokenUsage(prompt_tokens=10, completion_tokens=1),
                        transcript_uri=f"s3://ida-artifacts/runs/{run_id}/transcripts/add-simple.json",
                    )
                ],
            )
        return run_id

    def test_returns_run_and_results(self, client: TestClient, context: AppContext) -> None:
        run_id = self._seed(context)
        body = client.get(f"/runs/{run_id}").json()
        assert body["run"]["id"] == run_id
        assert body["run"]["mean_score"] == 1.0
        assert len(body["results"]) == 1

    def test_result_carries_score_serving_config_and_artifact_pointer(
        self, client: TestClient, context: AppContext
    ) -> None:
        """D-1 + D-3: the number, how it was produced, and where the evidence is."""
        run_id = self._seed(context)
        result = client.get(f"/runs/{run_id}").json()["results"][0]
        assert result["score"]["value"] == 1.0
        assert result["score"]["explanation"] == "got 42, want 42"
        assert result["serving_config"]["model_id"] == "mock-echo-1"
        assert result["transcript_uri"].startswith("s3://")

    def test_unknown_run_404s(self, client: TestClient) -> None:
        assert client.get("/runs/run_nope").status_code == 404


class TestTranscriptEndpoint:
    def test_serves_an_archived_transcript(self, client: TestClient, context: AppContext) -> None:
        from ida_core.artifacts import sample_key

        context.artifact_store.put_json(sample_key("run_abc", "add-simple"), {"completion": "42"})
        body = client.get("/runs/run_abc/results/add-simple/transcript").json()
        assert body == {"completion": "42"}

    def test_missing_transcript_404s(self, client: TestClient) -> None:
        assert client.get("/runs/run_abc/results/nope/transcript").status_code == 404

    def test_path_traversal_is_refused(self, client: TestClient) -> None:
        """The key is derived from the convention, never from client input."""
        response = client.get("/runs/run_abc/results/..%2F..%2Fetc/transcript")
        assert response.status_code in (400, 404)
        assert response.status_code != 200


class TestAuthPlaceholder:
    def test_anonymous_principal_when_auth_disabled(self, client: TestClient) -> None:
        assert (
            client.post(
                "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
            ).status_code
            == 202
        )

    def test_unimplemented_auth_mode_fails_loudly_rather_than_allowing_traffic(
        self, context: AppContext
    ) -> None:
        from ida_api.app import create_app

        context.settings.auth_mode = "oidc"
        client = TestClient(create_app(context))
        response = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        )
        assert response.status_code == 501
        assert "not implemented" in response.json()["detail"]

    def test_reads_stay_open_in_the_skeleton(self, context: AppContext) -> None:
        from ida_api.app import create_app

        context.settings.auth_mode = "oidc"
        assert TestClient(create_app(context)).get("/runs").status_code == 200


class TestOpenApi:
    def test_schema_is_generated(self, client: TestClient) -> None:
        """A broken response_model annotation shows up here before it 500s in prod."""
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "Capstone-IDA API"
        assert "/runs/{run_id}" in schema["paths"]


class TestSweepIdentity:
    """B9 — a multi-model sweep must be addressable as one thing."""

    def test_enqueue_returns_a_sweep_id(self, client: TestClient) -> None:
        body = client.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK], "model_keys": ["mock"]},
        ).json()
        assert body["sweep_id"].startswith("swp_")

    def test_every_run_in_the_cross_product_shares_it(self, client: TestClient) -> None:
        body = client.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK], "model_keys": ["mock"]},
        ).json()
        assert {r["sweep_id"] for r in body["runs"]} == {body["sweep_id"]}

    def test_separate_requests_get_separate_sweeps(self, client: TestClient) -> None:
        payload = {"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        first = client.post("/runs", json=payload).json()["sweep_id"]
        second = client.post("/runs", json=payload).json()["sweep_id"]
        assert first != second

    def test_the_comparison_view_can_query_by_it(self, client: TestClient) -> None:
        """The whole point: retrieve a sweep without string-matching a label."""
        sweep = client.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK], "model_keys": ["mock"]},
        ).json()["sweep_id"]
        client.post("/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]})

        listing = client.get(f"/runs?sweep_id={sweep}").json()
        assert listing["total"] == 2
        assert {r["sweep_id"] for r in listing["runs"]} == {sweep}

    def test_it_reaches_the_runner_on_the_queue(
        self, client: TestClient, context: AppContext
    ) -> None:
        sweep = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        ).json()["sweep_id"]
        message = context.queue.dequeue(timeout_s=0)
        assert message.sweep_id == sweep
        assert message.schema_version == 1, "sweep_id is additive; no version bump needed"


class TestSpendGuards:
    """A7 — POST /runs spends money, so duplicates and giant sweeps must not slip through."""

    def test_duplicate_ids_are_collapsed_not_billed_twice(
        self, client: TestClient, context: AppContext
    ) -> None:
        body = client.post(
            "/runs",
            json={
                "task_ids": [VERIFIABLE_TASK, VERIFIABLE_TASK],
                "model_keys": ["mock", "mock"],
            },
        ).json()
        assert body["queued"] == 1, "previously enqueued 4 identical runs"
        assert len(body["runs"]) == 1
        assert context.queue.depth() == 1

    def test_order_is_preserved_when_deduping(self, client: TestClient) -> None:
        body = client.post(
            "/runs",
            json={
                "task_ids": [SUBJECTIVE_TASK, VERIFIABLE_TASK, SUBJECTIVE_TASK],
                "model_keys": ["mock"],
            },
        ).json()
        assert [r["task_id"] for r in body["runs"]] == [SUBJECTIVE_TASK, VERIFIABLE_TASK]

    def test_an_oversized_cross_product_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/runs",
            json={
                "task_ids": [f"t{i}" for i in range(60)],
                "model_keys": [f"m{i}" for i in range(10)],
            },
        )
        assert response.status_code == 422
        assert "600 runs" in response.text

    def test_a_single_dimension_is_bounded(self, client: TestClient) -> None:
        response = client.post(
            "/runs",
            json={"task_ids": [f"t{i}" for i in range(201)], "model_keys": ["mock"]},
        )
        assert response.status_code == 422


class TestPartialEnqueue:
    """A15 — the documented commit-then-push ordering must be honest when push fails."""

    def test_reports_how_many_messages_actually_landed(self, context: AppContext) -> None:
        from ida_api.app import create_app

        real = context.queue

        class FlakyQueue:
            """Accepts the first push, then refuses. A real implementation of
            the failure the ordering rationale contemplates."""

            def __init__(self) -> None:
                self.accepted = 0

            def enqueue(self, message):
                if self.accepted >= 1:
                    raise ConnectionError("redis went away")
                self.accepted += 1
                real.enqueue(message)

            def dequeue(self, timeout_s=5):
                return real.dequeue(timeout_s)

            def depth(self):
                return real.depth()

            def ping(self):
                return True

        context.queue = FlakyQueue()
        client = TestClient(create_app(context))
        body = client.post(
            "/runs",
            json={"task_ids": [VERIFIABLE_TASK, SUBJECTIVE_TASK], "model_keys": ["mock"]},
        ).json()

        assert len(body["runs"]) == 2, "both rows were committed"
        assert body["queued"] == 1, "and the caller is told only one message landed"

    def test_rows_survive_so_the_runs_are_re_drivable(self, context: AppContext) -> None:
        """The point of committing rows first: nothing is invisible."""
        from ida_api.app import create_app

        class DeadQueue:
            def enqueue(self, message):
                raise ConnectionError("redis went away")

            def dequeue(self, timeout_s=5):
                return None

            def depth(self):
                return 0

            def ping(self):
                return True

        context.queue = DeadQueue()
        client = TestClient(create_app(context))
        body = client.post(
            "/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]}
        ).json()
        assert body["queued"] == 0
        assert client.get("/runs").json()["total"] == 1, "the run is visible and queued"
