"""The mock must be indistinguishable from a real OpenAI-compatible endpoint.

If the harness client works against this, it works against vLLM.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ida_mock_model.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _request(content: str = "What is 17 + 25?") -> dict:
    return {"model": "mock-echo-1", "messages": [{"role": "user", "content": content}]}


class TestHealth:
    def test_ok(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["service"] == "mock-model"


class TestModelListing:
    def test_openai_shaped(self, client: TestClient) -> None:
        body = client.get("/v1/models").json()
        assert body["object"] == "list"
        assert body["data"][0]["id"] == "mock-echo-1"


class TestChatCompletions:
    def test_response_shape_matches_openai(self, client: TestClient) -> None:
        body = client.post("/v1/chat/completions", json=_request()).json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert set(body["usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}
        assert body["id"].startswith("chatcmpl-mock-")

    def test_answers_arithmetic_correctly(self, client: TestClient) -> None:
        body = client.post("/v1/chat/completions", json=_request()).json()
        assert body["choices"][0]["message"]["content"] == "42"

    def test_usage_totals_add_up(self, client: TestClient) -> None:
        usage = client.post("/v1/chat/completions", json=_request()).json()["usage"]
        assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]

    def test_is_deterministic_across_requests(self, client: TestClient) -> None:
        first = client.post("/v1/chat/completions", json=_request("hello")).json()
        second = client.post("/v1/chat/completions", json=_request("hello")).json()
        assert (
            first["choices"][0]["message"]["content"] == second["choices"][0]["message"]["content"]
        )

    def test_uses_the_last_user_message(self, client: TestClient) -> None:
        payload = {
            "model": "m",
            "messages": [
                {"role": "system", "content": "be helpful"},
                {"role": "user", "content": "What is 1 + 1?"},
                {"role": "assistant", "content": "2"},
                {"role": "user", "content": "What is 5 * 5?"},
            ],
        }
        body = client.post("/v1/chat/completions", json=payload).json()
        assert body["choices"][0]["message"]["content"] == "25"

    def test_system_message_counts_toward_prompt_tokens(self, client: TestClient) -> None:
        without = client.post("/v1/chat/completions", json=_request()).json()
        payload = _request()
        payload["messages"].insert(0, {"role": "system", "content": "a" * 100})
        with_system = client.post("/v1/chat/completions", json=payload).json()
        assert with_system["usage"]["prompt_tokens"] > without["usage"]["prompt_tokens"]

    def test_no_user_message_is_a_400(self, client: TestClient) -> None:
        payload = {"model": "m", "messages": [{"role": "system", "content": "x"}]}
        assert client.post("/v1/chat/completions", json=payload).status_code == 400

    def test_empty_messages_is_a_422(self, client: TestClient) -> None:
        assert (
            client.post("/v1/chat/completions", json={"model": "m", "messages": []}).status_code
            == 422
        )

    def test_streaming_is_refused_explicitly(self, client: TestClient) -> None:
        payload = _request() | {"stream": True}
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 400
        assert "streaming" in response.json()["detail"]


class TestFailureInjection:
    def test_fail_every_is_deterministic(self, monkeypatch) -> None:
        """Deterministic, not random: a retry test must not be a coin flip."""
        monkeypatch.setenv("MOCK_FAIL_EVERY", "2")
        client = TestClient(create_app())
        codes = [client.post("/v1/chat/completions", json=_request()).status_code for _ in range(4)]
        assert codes == [200, 503, 200, 503]

    def test_disabled_by_default(self, client: TestClient) -> None:
        codes = [client.post("/v1/chat/completions", json=_request()).status_code for _ in range(5)]
        assert codes == [200] * 5


class TestLatencyInjection:
    def test_configurable(self, monkeypatch) -> None:
        monkeypatch.setenv("MOCK_LATENCY_MS", "25")
        client = TestClient(create_app())
        import time

        started = time.perf_counter()
        client.post("/v1/chat/completions", json=_request())
        assert (time.perf_counter() - started) >= 0.02


class TestScriptedResponses:
    def test_state_is_reachable_for_tests(self) -> None:
        app = create_app()
        app.state.mock.responder.script["What is 2 + 2?"] = "banana"
        client = TestClient(app)
        body = client.post("/v1/chat/completions", json=_request("What is 2 + 2?")).json()
        assert body["choices"][0]["message"]["content"] == "banana"


class TestInProcessTransport:
    """The transport the tracer bullet and service tests run through."""

    def test_reaches_the_real_app_from_a_sync_httpx_client(self) -> None:
        import httpx

        from ida_mock_model.testing import make_transport

        with httpx.Client(
            base_url="http://mock-model:8000/v1", transport=make_transport()
        ) as client:
            response = client.post(
                "/chat/completions",
                json={"model": "m", "messages": [{"role": "user", "content": "2 + 2"}]},
            )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "4"

    def test_propagates_error_statuses(self) -> None:
        import httpx

        from ida_mock_model.testing import make_transport

        with httpx.Client(
            base_url="http://mock-model:8000/v1", transport=make_transport()
        ) as client:
            response = client.post(
                "/chat/completions",
                json={"model": "m", "messages": [{"role": "system", "content": "x"}]},
            )
        assert response.status_code == 400

    def test_survives_client_close_so_it_can_be_shared(self) -> None:
        """The harness closes a client per run; a shared transport must outlive that."""
        import httpx

        from ida_mock_model.testing import make_transport

        transport = make_transport()
        payload = {"model": "m", "messages": [{"role": "user", "content": "2 + 2"}]}
        for _ in range(3):
            with httpx.Client(base_url="http://mock-model:8000/v1", transport=transport) as client:
                assert client.post("/chat/completions", json=payload).status_code == 200


class TestProbeContract:
    """The chart probes /healthz for BOTH liveness and readiness; compose and the
    tracer use /health. Losing either path breaks a deployment, not a test."""

    def test_healthz_is_served(self, client) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_and_healthz_agree(self, client) -> None:
        assert client.get("/health").json() == client.get("/healthz").json()

    def test_the_console_entrypoint_exists(self) -> None:
        """`command: ["ida-mock-model"]` in the chart resolves to this."""
        from ida_mock_model.main import main

        assert callable(main)


class TestHealthIdentifiesTheBuild:
    """/healthz must say which build is answering, and must not make it up.

    THE BUG THIS CLOSES. ``version`` was ``ida_mock_model.__version__``, a
    hardcoded ``"0.1.0"`` that no release step has ever written to -- so every
    image ever built, including 0.1.1, introduced itself as 0.1.0. A health
    endpoint that disagrees with the release it is running is worse than one that
    says nothing: it is what convinces an operator a deploy did not land.

    Same shape as the api's /healthz on purpose. ``version`` is whatever the
    release process was told to say (``IDA_VERSION``, baked in by
    ``Dockerfile.python``); ``git_sha`` is the authority, baked in at build time
    and correct by construction.
    """

    def test_it_reports_the_baked_in_git_sha(self, monkeypatch) -> None:
        monkeypatch.setenv("IDA_GIT_SHA", "a" * 40)
        body = TestClient(create_app()).get("/healthz").json()
        assert body["git_sha"] == "a" * 40

    def test_an_unknown_sha_is_null_not_a_placeholder(self, monkeypatch) -> None:
        monkeypatch.delenv("IDA_GIT_SHA", raising=False)
        assert TestClient(create_app()).get("/healthz").json()["git_sha"] is None

    @pytest.mark.parametrize("bogus", ["HEAD", "$GITHUB_SHA", "abc1234", "A" * 40, ""])
    def test_a_lie_from_the_pipeline_is_reported_as_null(self, monkeypatch, bogus) -> None:
        """A wrong SHA looks like a real one -- ``ida_core.gitmeta``'s rule.

        A pipeline that forgets to substitute a variable exports the literal
        ``$GITHUB_SHA``; a repository with no commits makes git print ``HEAD``.
        Serving either would be worse than serving nothing.
        """
        monkeypatch.setenv("IDA_GIT_SHA", bogus)
        assert TestClient(create_app()).get("/healthz").json()["git_sha"] is None

    def test_it_never_shells_out_to_git(self, monkeypatch) -> None:
        """⚠ A STUB MODEL SERVER MUST NOT FORK A SUBPROCESS.

        The chart probes this path for BOTH liveness and readiness. Unlike
        ``ida_core.gitmeta``, this resolver is env-only by design -- proven by
        making ``subprocess.run`` explode for the duration.
        """
        import subprocess

        monkeypatch.delenv("IDA_GIT_SHA", raising=False)

        def _explode(*args, **kwargs):
            raise AssertionError("/healthz shelled out to git")

        monkeypatch.setattr(subprocess, "run", _explode)
        assert TestClient(create_app()).get("/healthz").status_code == 200

    def test_the_release_can_tell_it_the_truth(self, monkeypatch) -> None:
        """``IDA_VERSION`` is the ONE place the release process says what it shipped."""
        monkeypatch.setenv("IDA_VERSION", "0.1.2")
        assert TestClient(create_app()).get("/healthz").json()["version"] == "0.1.2"

    def test_an_unset_release_falls_back_to_the_packaging_version(self, monkeypatch) -> None:
        """Not a fake release -- the version this distribution actually declares."""
        import ida_mock_model

        monkeypatch.delenv("IDA_VERSION", raising=False)
        body = TestClient(create_app()).get("/healthz").json()
        assert body["version"] == ida_mock_model.__version__

    def test_a_blank_release_var_does_not_report_an_empty_version(self, monkeypatch) -> None:
        """``ENV IDA_VERSION=${IDA_VERSION}`` with no --build-arg yields "".

        That is the DEFAULT for any local `docker build`, so it is the case most
        likely to be hit -- and reporting `"version": ""` would read as a broken
        endpoint rather than an unstamped build.
        """
        monkeypatch.setenv("IDA_VERSION", "   ")
        assert TestClient(create_app()).get("/healthz").json()["version"] != ""

    def test_health_and_healthz_still_agree(self, monkeypatch) -> None:
        """Two paths, ONE body -- the existing contract, re-checked with new fields."""
        monkeypatch.setenv("IDA_GIT_SHA", "b" * 40)
        client = TestClient(create_app())
        assert client.get("/health").json() == client.get("/healthz").json()
