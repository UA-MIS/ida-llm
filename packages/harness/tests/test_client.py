"""Client behaviour: request shape, error classification, retry policy, accounting.

The transient/permanent split drives production retry behaviour, so it is pinned
explicitly here -- moving a status code between the buckets should break a test.
"""

from __future__ import annotations

import httpx
import pytest

from ida_core.contracts import ChatMessage, ModelEntry, SamplingParams
from ida_harness.client import (
    TRANSIENT_STATUS_CODES,
    OpenAICompatibleClient,
    backoff_delay,
)
from ida_harness.errors import PermanentModelError, TransientModelError

OK_BODY = {
    "id": "chatcmpl-1",
    "model": "mock-echo-1",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "42"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
}


def _client(entry: ModelEntry, handler, **kwargs) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        entry,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        jitter=lambda _lo, hi: hi,
        **kwargs,
    )


MESSAGES = [ChatMessage(role="user", content="What is 40 + 2?")]
SAMPLING = SamplingParams(temperature=0.0, max_tokens=64, seed=7)


class TestRequestShape:
    def test_posts_to_chat_completions_with_the_registry_model_id(
        self, model_entry: ModelEntry
    ) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.read()
            return httpx.Response(200, json=OK_BODY)

        with _client(model_entry, handler) as client:
            client.complete(MESSAGES, SAMPLING)

        import json

        body = json.loads(seen["body"])
        assert seen["url"] == "http://mock-model:8000/v1/chat/completions"
        assert body["model"] == "mock-echo-1"
        assert body["messages"] == [{"role": "user", "content": "What is 40 + 2?"}]
        assert body["temperature"] == 0.0
        assert body["max_tokens"] == 64
        assert body["seed"] == 7
        assert body["stream"] is False

    def test_unset_seed_and_stop_are_omitted_not_nulled(self, model_entry: ModelEntry) -> None:
        """Several OpenAI-compatible servers 400 on an explicit null seed."""
        import json

        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.read())
            return httpx.Response(200, json=OK_BODY)

        with _client(model_entry, handler) as client:
            client.complete(MESSAGES, SamplingParams(seed=None, stop=[]))
        assert "seed" not in seen["body"]
        assert "stop" not in seen["body"]

    def test_api_key_becomes_a_bearer_header(self, model_entry: ModelEntry) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=OK_BODY)

        with _client(model_entry, handler, api_key="sk-secret") as client:
            client.complete(MESSAGES, SAMPLING)
        assert seen["auth"] == "Bearer sk-secret"

    def test_no_auth_header_without_a_key(self, model_entry: ModelEntry) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=OK_BODY)

        with _client(model_entry, handler) as client:
            client.complete(MESSAGES, SAMPLING)
        assert seen["auth"] is None


class TestResponseParsing:
    def test_content_usage_and_metadata(self, model_entry: ModelEntry) -> None:
        with _client(model_entry, lambda r: httpx.Response(200, json=OK_BODY)) as client:
            result = client.complete(MESSAGES, SAMPLING)
        assert result.content == "42"
        assert result.usage.prompt_tokens == 11
        assert result.usage.completion_tokens == 2
        assert result.model == "mock-echo-1"
        assert result.request_id == "chatcmpl-1"
        assert result.latency_ms >= 0
        assert result.raw == OK_BODY

    def test_missing_usage_yields_honest_zeros_not_estimates(self, model_entry: ModelEntry) -> None:
        body = {"choices": [{"message": {"content": "hi"}}]}
        with _client(model_entry, lambda r: httpx.Response(200, json=body)) as client:
            result = client.complete(MESSAGES, SAMPLING)
        assert result.usage.total_tokens == 0

    def test_null_content_becomes_empty_string(self, model_entry: ModelEntry) -> None:
        body = {"choices": [{"message": {"content": None}}]}
        with _client(model_entry, lambda r: httpx.Response(200, json=body)) as client:
            assert client.complete(MESSAGES, SAMPLING).content == ""

    @pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{}]}, {"choices": 5}])
    def test_unexpected_shapes_are_permanent_errors(self, model_entry: ModelEntry, body) -> None:
        with (
            _client(model_entry, lambda r: httpx.Response(200, json=body)) as client,
            pytest.raises(PermanentModelError, match="unexpected body shape"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_non_json_body_is_a_permanent_error(self, model_entry: ModelEntry) -> None:
        handler = lambda r: httpx.Response(200, text="<html>proxy error</html>")  # noqa: E731
        with (
            _client(model_entry, handler) as client,
            pytest.raises(PermanentModelError, match="non-JSON"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_non_string_content_is_a_permanent_error(self, model_entry: ModelEntry) -> None:
        body = {"choices": [{"message": {"content": {"parts": ["x"]}}}]}
        with (
            _client(model_entry, lambda r: httpx.Response(200, json=body)) as client,
            pytest.raises(PermanentModelError, match="non-string content"),
        ):
            client.complete(MESSAGES, SAMPLING)


class TestErrorClassification:
    @pytest.mark.parametrize("status", sorted(TRANSIENT_STATUS_CODES))
    def test_transient_statuses(self, model_entry: ModelEntry, status: int) -> None:
        model_entry.max_retries = 0
        with (
            _client(model_entry, lambda r: httpx.Response(status, text="x")) as client,
            pytest.raises(TransientModelError) as exc,
        ):
            client.complete(MESSAGES, SAMPLING)
        assert exc.value.status_code == status

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 501])
    def test_permanent_statuses(self, model_entry: ModelEntry, status: int) -> None:
        with (
            _client(model_entry, lambda r: httpx.Response(status, text="x")) as client,
            pytest.raises(PermanentModelError) as exc,
        ):
            client.complete(MESSAGES, SAMPLING)
        assert exc.value.status_code == status

    def test_rate_limit_is_transient_but_auth_failure_is_not(self, model_entry: ModelEntry) -> None:
        """The one classification everyone gets wrong: 429 retry, 401 never."""
        assert 429 in TRANSIENT_STATUS_CODES
        assert 401 not in TRANSIENT_STATUS_CODES

    def test_timeout_is_transient(self, model_entry: ModelEntry) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        model_entry.max_retries = 0
        with (
            _client(model_entry, handler) as client,
            pytest.raises(TransientModelError, match="timeout"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_connection_failure_is_transient(self, model_entry: ModelEntry) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        model_entry.max_retries = 0
        with (
            _client(model_entry, handler) as client,
            pytest.raises(TransientModelError, match="transport error"),
        ):
            client.complete(MESSAGES, SAMPLING)


class TestRetryPolicy:
    def test_retries_transient_then_succeeds(self, model_entry: ModelEntry) -> None:
        model_entry.max_retries = 2
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503, text="unavailable")
            return httpx.Response(200, json=OK_BODY)

        with _client(model_entry, handler) as client:
            assert client.complete(MESSAGES, SAMPLING).content == "42"
        assert calls["n"] == 3

    def test_gives_up_after_max_retries(self, model_entry: ModelEntry) -> None:
        model_entry.max_retries = 2
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, text="unavailable")

        with _client(model_entry, handler) as client, pytest.raises(TransientModelError):
            client.complete(MESSAGES, SAMPLING)
        assert calls["n"] == 3, "1 initial attempt + 2 retries"

    def test_permanent_errors_are_never_retried(self, model_entry: ModelEntry) -> None:
        """Retrying a 401 burns rate limit and delays the real error."""
        model_entry.max_retries = 5
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, text="bad key")

        with _client(model_entry, handler) as client, pytest.raises(PermanentModelError):
            client.complete(MESSAGES, SAMPLING)
        assert calls["n"] == 1

    def test_zero_retries_means_one_attempt(self, model_entry: ModelEntry) -> None:
        model_entry.max_retries = 0
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(500, text="boom")

        with _client(model_entry, handler) as client, pytest.raises(TransientModelError):
            client.complete(MESSAGES, SAMPLING)
        assert calls["n"] == 1

    def test_sleeps_between_attempts_with_growing_ceiling(self, model_entry: ModelEntry) -> None:
        model_entry.max_retries = 3
        slept: list[float] = []
        client = OpenAICompatibleClient(
            model_entry,
            transport=httpx.MockTransport(lambda r: httpx.Response(503, text="x")),
            sleep=slept.append,
            jitter=lambda _lo, hi: hi,
        )
        with client, pytest.raises(TransientModelError):
            client.complete(MESSAGES, SAMPLING)
        assert slept == [0.5, 1.0, 2.0]


class TestBackoffDelay:
    def test_full_jitter_bounds(self) -> None:
        for attempt in range(1, 8):
            delay = backoff_delay(attempt)
            assert 0.0 <= delay <= 30.0

    def test_ceiling_doubles_then_caps(self) -> None:
        ceilings = [backoff_delay(a, jitter=lambda _lo, hi: hi) for a in range(1, 9)]
        assert ceilings[:4] == [0.5, 1.0, 2.0, 4.0]
        assert ceilings[-1] == 30.0

    def test_lower_bound_is_zero_so_a_fleet_desynchronises(self) -> None:
        assert backoff_delay(5, jitter=lambda lo, _hi: lo) == 0.0

    def test_attempt_is_one_based(self) -> None:
        with pytest.raises(ValueError):
            backoff_delay(0)
