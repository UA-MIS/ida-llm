"""Client behaviour: request shape, error classification, retry policy, accounting.

The transient/permanent split drives production retry behaviour, so it is pinned
explicitly here -- moving a status code between the buckets should break a test.
"""

from __future__ import annotations

import httpx
import pytest

from ida_core.contracts import ChatMessage, ModelEntry, SamplingParams
from ida_core.registry import MissingApiKeyError
from ida_harness.client import (
    TRANSIENT_STATUS_CODES,
    ModelClient,
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


class TestRetryAfter:
    """A provider that says how long to wait knows something backoff cannot."""

    def test_retry_after_seconds_becomes_the_floor_of_the_next_delay(
        self, model_entry: ModelEntry
    ) -> None:
        model_entry.max_retries = 1
        slept: list[float] = []
        handler = lambda r: httpx.Response(  # noqa: E731
            429, text="slow down", headers={"retry-after": "7"}
        )
        client = OpenAICompatibleClient(
            model_entry,
            transport=httpx.MockTransport(handler),
            sleep=slept.append,
            jitter=lambda _lo, hi: hi,
        )
        with client, pytest.raises(TransientModelError):
            client.complete(MESSAGES, SAMPLING)
        assert slept == [7.0], "7s beats the 0.5s first-attempt ceiling"

    def test_backoff_wins_when_it_is_longer_than_retry_after(self, model_entry: ModelEntry) -> None:
        """A 0.1s Retry-After three attempts into a storm must not reset us to
        a near-instant poll -- max(), not 'prefer the header'."""
        model_entry.max_retries = 3
        slept: list[float] = []
        handler = lambda r: httpx.Response(  # noqa: E731
            429, text="x", headers={"retry-after": "0.1"}
        )
        client = OpenAICompatibleClient(
            model_entry,
            transport=httpx.MockTransport(handler),
            sleep=slept.append,
            jitter=lambda _lo, hi: hi,
        )
        with client, pytest.raises(TransientModelError):
            client.complete(MESSAGES, SAMPLING)
        assert slept == [0.5, 1.0, 2.0]

    def test_an_implausibly_long_retry_after_stops_instead_of_parking(
        self, model_entry: ModelEntry
    ) -> None:
        """Waiting an hour holds the worker hostage; retrying anyway hammers an
        endpoint that already said no. Neither -- stop, and say why."""
        model_entry.max_retries = 3
        calls = {"n": 0}
        slept: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, text="quota", headers={"retry-after": "3600"})

        client = OpenAICompatibleClient(
            model_entry,
            transport=httpx.MockTransport(handler),
            sleep=slept.append,
            jitter=lambda _lo, hi: hi,
        )
        with client, pytest.raises(TransientModelError, match="not retried") as exc:
            client.complete(MESSAGES, SAMPLING)
        assert calls["n"] == 1
        assert slept == []
        assert exc.value.retry_after_s == 3600.0

    @pytest.mark.parametrize("value", ["Wed, 21 Oct 2015 07:28:00 GMT", "soon", "", "-5"])
    def test_unparseable_retry_after_falls_back_to_our_own_backoff(
        self, model_entry: ModelEntry, value: str
    ) -> None:
        """The HTTP-date form is legal but neither provider sends it, and
        honouring it means trusting our clock against theirs."""
        model_entry.max_retries = 1
        slept: list[float] = []
        handler = lambda r: httpx.Response(429, text="x", headers={"retry-after": value})  # noqa: E731
        client = OpenAICompatibleClient(
            model_entry,
            transport=httpx.MockTransport(handler),
            sleep=slept.append,
            jitter=lambda _lo, hi: hi,
        )
        with client, pytest.raises(TransientModelError):
            client.complete(MESSAGES, SAMPLING)
        assert slept == [0.5]

    def test_permanent_errors_carry_no_retry_after(self, model_entry: ModelEntry) -> None:
        handler = lambda r: httpx.Response(400, text="bad", headers={"retry-after": "5"})  # noqa: E731
        with (
            _client(model_entry, handler) as client,
            pytest.raises(PermanentModelError) as exc,
        ):
            client.complete(MESSAGES, SAMPLING)
        assert exc.value.retry_after_s is None


class TestProviderErrorDetail:
    """`returned HTTP 400` points nowhere. The provider's own text points at the
    models.yaml line that caused it."""

    def test_openai_error_envelope_is_surfaced(self, model_entry: ModelEntry) -> None:
        model_entry.max_retries = 0
        body = {
            "error": {
                "message": "Unrecognized request argument supplied: seed",
                "type": "invalid_request_error",
                "param": None,
                "code": None,
            }
        }
        with (
            _client(model_entry, lambda r: httpx.Response(400, json=body)) as client,
            pytest.raises(PermanentModelError, match="Unrecognized request argument"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_a_non_json_error_body_still_yields_a_snippet(self, model_entry: ModelEntry) -> None:
        with (
            _client(model_entry, lambda r: httpx.Response(502, text="<html>bad gateway")) as client,
            pytest.raises(TransientModelError, match="bad gateway"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_a_json_body_without_the_envelope_still_yields_a_snippet(
        self, model_entry: ModelEntry
    ) -> None:
        with (
            _client(model_entry, lambda r: httpx.Response(400, json={"detail": "nope"})) as client,
            pytest.raises(PermanentModelError, match="nope"),
        ):
            client.complete(MESSAGES, SAMPLING)


class TestOverloadedIsTransient:
    def test_529_is_retryable(self, model_entry: ModelEntry) -> None:
        """Anthropic's overloaded_error. Absent from the IANA registry, so it is
        easy to misclassify as permanent -- which fails a run over a blip."""
        assert 529 in TRANSIENT_STATUS_CODES


class TestMissingKeyIsLoud:
    def test_a_declared_but_unsupplied_key_refuses_to_construct(
        self, model_entry: ModelEntry
    ) -> None:
        model_entry.api_key_env = "OPENAI_API_KEY"
        with pytest.raises(MissingApiKeyError, match="OPENAI_API_KEY"):
            OpenAICompatibleClient(model_entry, api_key=None)

    def test_an_entry_declaring_no_key_still_constructs(self, model_entry: ModelEntry) -> None:
        """The mock model and a NetworkPolicy-protected vLLM are unauthenticated
        by declaration, not by accident."""
        OpenAICompatibleClient(model_entry).close()


class TestProtocolConformance:
    def test_the_openai_client_satisfies_the_model_client_protocol(
        self, model_entry: ModelEntry
    ) -> None:
        client = OpenAICompatibleClient(model_entry)
        with client:
            assert isinstance(client, ModelClient)


# --------------------------------------------------------------------------
# The REAL OpenAI wire shape
# --------------------------------------------------------------------------
#
# OK_BODY above is a minimal hand-written body -- fine for pinning parser
# branches, useless for proving we can read what OpenAI actually sends. This
# fixture is copied verbatim from OpenAI's own published example for
# `CreateChatCompletionResponse`:
#
#   https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml
#   (mirrored at https://developers.openai.com/api/docs/api-reference/chat/object)
#   retrieved 2026-08-25
#
# It carries the fields a hand-written fixture never thinks to include --
# `refusal`, `annotations`, `logprobs`, `service_tier`, `system_fingerprint`,
# and the nested `*_tokens_details` -- which is exactly where a parser that only
# ever saw its own fixture falls over.
DOCUMENTED_OPENAI_BODY = {
    "id": "chatcmpl-B9MHDbslfkBeAs8l4bebGdFOJ6PeG",
    "object": "chat.completion",
    "created": 1741570283,
    "model": "gpt-4o-2024-08-06",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "The image shows a wooden boardwalk path running through a lush green field.",
                "refusal": None,
                "annotations": [],
            },
            "logprobs": None,
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 1117,
        "completion_tokens": 46,
        "total_tokens": 1163,
        "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 0},
        "completion_tokens_details": {
            "reasoning_tokens": 0,
            "audio_tokens": 0,
            "accepted_prediction_tokens": 0,
            "rejected_prediction_tokens": 0,
        },
    },
    "service_tier": "default",
    "system_fingerprint": "fp_fc9f1d7035",
}

# Real captured 401 body (https://github.com/openai/openai-python/issues/1968),
# matching the documented `Error` schema: required keys type/message/param/code.
DOCUMENTED_OPENAI_401 = {
    "error": {
        "message": "Incorrect API key provided: sk-qVL45***...D1Vi. You can find your API key at https://platform.openai.com/account/api-keys.",
        "type": "invalid_request_error",
        "param": None,
        "code": "invalid_api_key",
    }
}


class TestDocumentedOpenAIShape:
    def test_parses_the_published_response_example(self, model_entry: ModelEntry) -> None:
        handler = lambda r: httpx.Response(200, json=DOCUMENTED_OPENAI_BODY)  # noqa: E731
        with _client(model_entry, handler) as client:
            result = client.complete(MESSAGES, SAMPLING)
        assert result.content.startswith("The image shows a wooden boardwalk")
        assert result.usage.prompt_tokens == 1117
        assert result.usage.completion_tokens == 46
        assert result.model == "gpt-4o-2024-08-06"
        assert result.request_id == "chatcmpl-B9MHDbslfkBeAs8l4bebGdFOJ6PeG"

    def test_unmodelled_fields_survive_into_the_transcript(self, model_entry: ModelEntry) -> None:
        """`raw` is archived verbatim, so `service_tier`, `system_fingerprint`
        and the token-detail breakdowns stay auditable even though no field on
        ChatCompletion holds them."""
        handler = lambda r: httpx.Response(200, json=DOCUMENTED_OPENAI_BODY)  # noqa: E731
        with _client(model_entry, handler) as client:
            raw = client.complete(MESSAGES, SAMPLING).raw
        assert raw["system_fingerprint"] == "fp_fc9f1d7035"
        assert raw["usage"]["completion_tokens_details"]["reasoning_tokens"] == 0

    def test_a_refusal_with_null_content_scores_as_empty_not_as_a_crash(
        self, model_entry: ModelEntry
    ) -> None:
        body = {
            "id": "chatcmpl-x",
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "refusal": "I'm sorry, I can't help with that.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 11, "total_tokens": 20},
        }
        with _client(model_entry, lambda r: httpx.Response(200, json=body)) as client:
            result = client.complete(MESSAGES, SAMPLING)
        assert result.content == ""
        assert result.raw["choices"][0]["message"]["refusal"].startswith("I'm sorry")

    def test_the_published_401_body_is_permanent_and_names_the_cause(
        self, model_entry: ModelEntry
    ) -> None:
        handler = lambda r: httpx.Response(401, json=DOCUMENTED_OPENAI_401)  # noqa: E731
        with (
            _client(model_entry, handler) as client,
            pytest.raises(PermanentModelError, match="Incorrect API key provided"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_the_unsupported_parameter_error_reaches_the_operator_verbatim(
        self, model_entry: ModelEntry
    ) -> None:
        """A reasoning model rejecting `max_tokens` is the single most likely
        first failure against real OpenAI, so the message that names the fix
        must survive all the way out of the client.  Captured shape:
        https://github.com/langgenius/dify/issues/10348"""
        model_entry.max_retries = 0
        body = {
            "error": {
                "message": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.",
                "type": "invalid_request_error",
                "param": "max_tokens",
                "code": "unsupported_parameter",
            }
        }
        with (
            _client(model_entry, lambda r: httpx.Response(400, json=body)) as client,
            pytest.raises(PermanentModelError, match="Use 'max_completion_tokens' instead"),
        ):
            client.complete(MESSAGES, SAMPLING)
