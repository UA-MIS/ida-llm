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

    # ── THE DEPLOYED BUILD HAS TO BE IDENTIFIABLE FROM /healthz ────────────
    #
    # `version` came from a HARDCODED `__version__ = "0.1.0"` in ida_api, which
    # nothing in the release process ever updated. The 0.1.1 image therefore
    # served `"version":"0.1.0"` -- and a health endpoint that disagrees with the
    # release it is running is worse than one that says nothing: it is exactly
    # what makes someone conclude a deploy did not land and roll back a good one.
    #
    # IDA_GIT_SHA is already baked into every image at build time
    # (Dockerfile.python, from the GIT_SHA build-arg) and is the ONE identifier
    # that is correct by construction, so /healthz reports it.

    def test_healthz_reports_the_build_git_sha(self, monkeypatch, context: AppContext) -> None:
        """The field that answers "which build is actually running?"."""
        from ida_api.app import create_app

        monkeypatch.setenv("IDA_GIT_SHA", "a" * 40)
        response = TestClient(create_app(context)).get("/healthz")
        assert response.status_code == 200
        assert response.json()["git_sha"] == "a" * 40

    def test_healthz_never_reports_a_fake_sha(self, monkeypatch, context: AppContext) -> None:
        """A wrong SHA looks like a real one -- gitmeta's rule, enforced here too.

        A pipeline that forgets to substitute a variable exports the literal
        ``$GITHUB_SHA``; a repo with no commits makes git print ``HEAD``. Either
        would otherwise be served as though it were provenance.
        """
        from ida_api.app import create_app

        for bogus in ("HEAD", "$GITHUB_SHA", "abc1234", ""):
            monkeypatch.setenv("IDA_GIT_SHA", bogus)
            body = TestClient(create_app(context)).get("/healthz").json()
            assert body["git_sha"] != bogus or body["git_sha"] is None, bogus

    def test_healthz_resolves_the_sha_once_not_per_request(
        self, monkeypatch, context: AppContext
    ) -> None:
        """⚠ LIVENESS MUST NOT FORK A SUBPROCESS.

        With IDA_GIT_SHA unset, ``current_git_sha()`` shells out to ``git``. On
        the liveness path that would be a fork every 20s per replica, forever --
        so the SHA is resolved ONCE when the app is built. Proving it: make the
        subprocess call explode AFTER the app exists; /healthz must still answer.
        """
        import ida_core.gitmeta as gitmeta
        from ida_api.app import create_app

        monkeypatch.delenv("IDA_GIT_SHA", raising=False)
        client = TestClient(create_app(context))

        def _explode(*args, **kwargs):
            raise AssertionError("/healthz shelled out to git on the request path")

        monkeypatch.setattr(gitmeta.subprocess, "run", _explode)
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200

    def test_version_can_be_told_the_truth_by_the_release(
        self, monkeypatch, context: AppContext
    ) -> None:
        """One knob the release process can set, instead of a constant nobody bumps.

        Unset, this stays the packaged ``__version__`` -- see the module comment
        in app.py for why that is a floor and ``git_sha`` is the authority.
        """
        from ida_api.app import create_app

        monkeypatch.setenv("IDA_VERSION", "9.9.9")
        assert TestClient(create_app(context)).get("/healthz").json()["version"] == "9.9.9"

    def test_readyz_identifies_the_build_too(self, monkeypatch, context: AppContext) -> None:
        """Whoever is debugging a degraded pod needs to know which build it is."""
        from ida_api.app import create_app

        monkeypatch.setenv("IDA_GIT_SHA", "b" * 40)
        body = TestClient(create_app(context)).get("/readyz").json()
        assert body["git_sha"] == "b" * 40

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
        assert [m["key"] for m in models] == ["mock", "luna", "qwen-local"]

    def test_a_disabled_model_is_not_offered(self, client: TestClient) -> None:
        """`sparks-local` is unreachable from this cluster. Listing it would let
        the UI enqueue a run that can only fail."""
        assert "sparks-local" not in {m["key"] for m in client.get("/models").json()}

    def test_no_key_material_is_exposed(self, client: TestClient) -> None:
        """`luna` is the first listed model with a real key behind it. The
        endpoint is unauthenticated, so the field whitelist below is now load
        bearing rather than theoretical."""
        body = client.get("/models").text
        assert "sk-" not in body

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
    def test_lists_the_shipped_tasks(self, client: TestClient) -> None:
        """The endpoint serves the whole catalog, in the catalog's order.

        Asserted as a superset plus an ordering check rather than an exact list:
        `tasks/` grows every time someone authors a family, and a test that has
        to be edited for each one stops being read.
        """
        ids = [t["id"] for t in client.get("/tasks").json()]
        assert {VERIFIABLE_TASK, SUBJECTIVE_TASK} <= set(ids)
        assert ids == sorted(ids), "TaskCatalog.ids() is sorted; the wire order must match"

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


class TestRunDetailPagination:
    """`GET /runs/{id}` returns a bounded page, and says how much it did not send.

    A run holds one result per (sample, repetition) and nothing bounds that
    product, so the endpoint used to let authored data decide the response size.
    """

    def _seed(self, context: AppContext, sample_count: int) -> str:
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
                    sample_count=sample_count,
                    scored_count=sample_count,
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
                        # zero-padded so lexical order == numeric order, which is
                        # what lets the offset assertions below name exact rows.
                        sample_id=f"s{i:03d}",
                        model_key="mock",
                        serving_config=serving,
                        score=Score(
                            scorer=ScorerKind.NUMERIC_MATCH,
                            value=1.0,
                            passed=True,
                            explanation="ok",
                        ),
                        usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
                    )
                    for i in range(sample_count)
                ],
            )
        return run_id

    def test_defaults_return_everything_a_real_run_has(
        self, client: TestClient, context: AppContext
    ) -> None:
        """The default page must not silently truncate an existing client."""
        run_id = self._seed(context, 25)
        body = client.get(f"/runs/{run_id}").json()
        assert len(body["results"]) == 25
        assert body["results_total"] == 25
        assert body["results_offset"] == 0

    def test_limit_bounds_the_page_and_total_still_reports_the_truth(
        self, client: TestClient, context: AppContext
    ) -> None:
        run_id = self._seed(context, 25)
        body = client.get(f"/runs/{run_id}?limit=10").json()
        assert len(body["results"]) == 10
        assert body["results_total"] == 25, "total must ignore the page"
        assert body["results_limit"] == 10

    def test_offset_walks_the_run_without_repeating_or_skipping(
        self, client: TestClient, context: AppContext
    ) -> None:
        """The ordering is total, so paging over it is exact rather than roughly right."""
        run_id = self._seed(context, 25)
        seen: list[str] = []
        for offset in range(0, 30, 10):
            page = client.get(f"/runs/{run_id}?limit=10&offset={offset}").json()
            seen.extend(r["sample_id"] for r in page["results"])
        assert seen == [f"s{i:03d}" for i in range(25)]
        assert len(seen) == len(set(seen)), "a row was served twice"

    def test_a_page_past_the_end_is_empty_but_not_a_lie(
        self, client: TestClient, context: AppContext
    ) -> None:
        """The case that makes `results_total` load-bearing.

        `frontend/src/lib/outcome.ts` classifies a run with zero results as
        *all errored*. Without a total, a caller that paged past the end could
        not tell that apart from a run where nothing was measured -- and would
        report a successful run as a total failure.
        """
        run_id = self._seed(context, 5)
        body = client.get(f"/runs/{run_id}?offset=500").json()
        assert body["results"] == []
        assert body["results_total"] == 5, "an empty page must still report the real count"
        assert body["run"]["status"] == "succeeded"

    def test_a_run_with_no_results_reports_zero(
        self, client: TestClient, context: AppContext
    ) -> None:
        """The genuinely-empty case, which must stay distinguishable from the one above."""
        run_id = self._seed(context, 0)
        body = client.get(f"/runs/{run_id}").json()
        assert body["results"] == []
        assert body["results_total"] == 0

    @pytest.mark.parametrize(
        ("query", "why"),
        [
            ("limit=0", "a zero-size page is meaningless"),
            ("limit=-1", "negative page"),
            ("offset=-1", "negative offset"),
            ("limit=100000", "above the cap the API sets on itself"),
        ],
    )
    def test_nonsense_pagination_is_rejected(
        self, client: TestClient, context: AppContext, query: str, why: str
    ) -> None:
        run_id = self._seed(context, 3)
        assert client.get(f"/runs/{run_id}?{query}").status_code == 422, why


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


class TestAuthSeam:
    """The mode switch itself. The `token` mode it selects is exercised in full
    by ``test_auth.py`` -- these are the two properties that must hold whatever
    the mode is: the default is open for local dev, and an unknown mode is a
    loud refusal rather than a quiet allow."""

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

    def test_reads_stay_open_whatever_the_mode(self, context: AppContext) -> None:
        """Even a mode the API cannot implement must not take the public
        benchmark down with it: the 501 is scoped to the route that spends
        money. See docs/sensitive-material.md section 1."""
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


class TestEnqueuedRunsCarryTheBuildIdentity:
    """``POST /runs`` must not stamp a row with a version that identifies nothing.

    THE BUG THIS CLOSES. ``harness_version`` was ``ida_harness.__version__`` -- a
    hardcoded ``"0.1.0"`` that no release step has ever written to -- and the api
    wrote it onto every row it enqueued. On a platform whose D-1 premise is that
    a result can be traced back to the code that produced it, that was wrong
    provenance on every row, in a field whose docstring promised the opposite.

    ⚠ WHY THIS IS ASSERTED AT THE API AND NOT ONLY AT THE HARNESS. The worker
    overwrites the field when the run finishes, so a reader could reasonably ask
    whether the enqueue value matters. It does: it is what the row carries for as
    long as it sits ``queued``, and for a run that never completes it is the only
    value the row ever has.

    ⚠ ``ida_api.app.HARNESS_VERSION`` is resolved AT IMPORT (see its docstring --
    /healthz and the enqueue path must not fork a subprocess per call), so
    monkeypatching ``IDA_GIT_SHA`` here would not change it. These tests assert
    the property that actually matters -- it is the build identity and never the
    dead constant -- rather than re-testing the resolver, which
    ``TestBuildIdentity`` in ida_core already pins.
    """

    def test_the_row_carries_the_resolved_build_identity(self, client: TestClient) -> None:
        from ida_api.app import HARNESS_VERSION

        client.post("/runs", json={"task_ids": [VERIFIABLE_TASK], "model_keys": ["mock"]})
        runs = client.get("/runs").json()["runs"]
        assert runs and {r["harness_version"] for r in runs} == {HARNESS_VERSION}

    def test_it_is_a_build_sha_or_an_honest_unknown_never_a_fake_release(self) -> None:
        """The two shapes allowed, stated as the whole permitted set.

        ``"0.1.0"`` is pinned by value rather than merely implied: it is the
        exact string that shipped on every row for the life of the platform, and
        the one a well-meaning "restore the fallback" edit would reach for.
        """
        from ida_api.app import HARNESS_VERSION
        from ida_core.gitmeta import is_sha

        assert HARNESS_VERSION != "0.1.0"
        assert is_sha(HARNESS_VERSION) or HARNESS_VERSION == "unknown"

    def test_it_is_not_the_packaging_version(self) -> None:
        """Keeping the two apart is the fix; collapsing them is how this happened."""
        import ida_api
        import ida_harness
        from ida_api.app import HARNESS_VERSION

        assert HARNESS_VERSION not in {ida_api.__version__, ida_harness.__version__}
