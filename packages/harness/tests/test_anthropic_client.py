"""Anthropic Messages API client: wire format, parsing, accounting, error paths.

**No test in this file makes a network call.**  Every request goes through an
``httpx.MockTransport``, so the whole file runs with no key, no credits and no
egress -- while still exercising our real request building, real status handling
and real parsing through genuine ``httpx`` machinery.

Fixture provenance
------------------
``OK_BODY`` and ``ERROR_BODY`` are copied from Anthropic's own documentation --
<https://platform.claude.com/docs/en/api/messages> (200 body, headers, required
fields) and the documented error-response shape -- retrieved 2026-08-25, not
invented from the client's own parser.  A fixture invented to match the parser
proves only that the parser matches itself; these prove it matches Anthropic.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ida_core.contracts import (
    ChatMessage,
    ModelEntry,
    Quantization,
    SamplingParams,
    ServingConfig,
    ServingStack,
)
from ida_core.registry import MissingApiKeyError
from ida_harness.anthropic_client import ANTHROPIC_VERSION, AnthropicMessagesClient
from ida_harness.errors import PermanentModelError, TransientModelError

# https://platform.claude.com/docs/en/api/messages -- documented 200 response.
OK_BODY = {
    "id": "msg_1234567890",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-4-5",
    "content": [{"type": "text", "text": "Response text here"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    },
}

# Documented error envelope: a `type: "error"` wrapper around `error.{type,message}`.
ERROR_BODY = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": 'messages: roles must alternate between "user" and "assistant"',
    },
    "request_id": "req_011CSHoEeqs5C35K2UUqR7Fy",
}

MESSAGES = [ChatMessage(role="user", content="What is 40 + 2?")]
SAMPLING = SamplingParams(temperature=0.0, top_p=1.0, max_tokens=64, seed=None)


@pytest.fixture
def anthropic_entry() -> ModelEntry:
    return ModelEntry(
        key="claude-sonnet",
        display_name="Claude Sonnet",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        max_retries=2,
        serving=ServingConfig(
            model_id="claude-sonnet-4-6",
            serving_stack=ServingStack.ANTHROPIC_COMPAT,
            quantization=Quantization.UNKNOWN,
            sampling=SamplingParams(temperature=0.0, top_p=1.0, max_tokens=64, seed=None),
        ),
        cost={"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0},
    )


def _client(entry: ModelEntry, handler, *, api_key: str = "sk-ant-test") -> AnthropicMessagesClient:
    return AnthropicMessagesClient(
        entry,
        api_key=api_key,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        jitter=lambda _lo, hi: hi,
    )


def _capture(entry: ModelEntry, sampling: SamplingParams, messages=None) -> dict:
    """Run one call and return what went on the wire."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=OK_BODY)

    with _client(entry, handler) as client:
        client.complete(MESSAGES if messages is None else messages, sampling)
    return seen


class TestRequestShape:
    def test_posts_to_messages_with_the_registry_model_id(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SAMPLING)
        assert seen["url"] == "https://api.anthropic.com/v1/messages"
        assert seen["body"]["model"] == "claude-sonnet-4-6"
        assert seen["body"]["messages"] == [{"role": "user", "content": "What is 40 + 2?"}]

    def test_key_goes_in_x_api_key_not_authorization(self, anthropic_entry) -> None:
        """The Messages API authenticates with x-api-key; a Bearer header is a 401."""
        seen = _capture(anthropic_entry, SAMPLING)
        assert seen["headers"]["x-api-key"] == "sk-ant-test"
        assert "authorization" not in seen["headers"]

    def test_anthropic_version_header_is_always_sent(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SAMPLING)
        assert seen["headers"]["anthropic-version"] == ANTHROPIC_VERSION

    def test_max_tokens_is_always_sent_because_the_api_requires_it(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SAMPLING)
        assert seen["body"]["max_tokens"] == 64

    def test_system_message_is_hoisted_out_of_the_turn_list(self, anthropic_entry) -> None:
        messages = [
            ChatMessage(role="system", content="Answer with the number only."),
            ChatMessage(role="user", content="What is 40 + 2?"),
        ]
        seen = _capture(anthropic_entry, SAMPLING, messages)
        assert seen["body"]["system"] == "Answer with the number only."
        assert seen["body"]["messages"] == [{"role": "user", "content": "What is 40 + 2?"}]

    def test_multiple_system_messages_collapse_to_one_field(self, anthropic_entry) -> None:
        messages = [
            ChatMessage(role="system", content="First."),
            ChatMessage(role="system", content="Second."),
            ChatMessage(role="user", content="Go."),
        ]
        seen = _capture(anthropic_entry, SAMPLING, messages)
        assert seen["body"]["system"] == "First.\n\nSecond."

    def test_no_system_field_when_the_task_has_no_system_prompt(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SAMPLING)
        assert "system" not in seen["body"]

    def test_stop_becomes_stop_sequences(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SamplingParams(max_tokens=64, stop=["END"]))
        assert seen["body"]["stop_sequences"] == ["END"]

    def test_empty_stop_is_omitted(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SAMPLING)
        assert "stop_sequences" not in seen["body"]


class TestSamplingParameters:
    """Current Claude models 400 on a NON-DEFAULT temperature/top_p, and 400 when
    both are sent together.  A value already at Anthropic's default is therefore
    omitted -- and omitting it is honest, because the endpoint then uses exactly
    the value the stored ServingConfig claims."""

    def test_non_default_temperature_is_sent(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SamplingParams(temperature=0.0, max_tokens=64))
        assert seen["body"]["temperature"] == 0.0

    def test_default_temperature_is_omitted(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SamplingParams(temperature=1.0, max_tokens=64))
        assert "temperature" not in seen["body"]

    def test_default_top_p_is_omitted(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SamplingParams(temperature=0.0, top_p=1.0, max_tokens=64))
        assert "top_p" not in seen["body"]

    def test_non_default_top_p_is_sent(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SamplingParams(temperature=1.0, top_p=0.9, max_tokens=64))
        assert seen["body"]["top_p"] == 0.9

    def test_both_defaults_send_neither(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SamplingParams(temperature=1.0, top_p=1.0, max_tokens=64))
        assert "temperature" not in seen["body"]
        assert "top_p" not in seen["body"]

    def test_a_declared_seed_fails_loudly_rather_than_being_dropped(self, anthropic_entry) -> None:
        """Recording a seed that was never applied is a fabricated measurement."""
        with (
            _client(anthropic_entry, lambda r: httpx.Response(200, json=OK_BODY)) as client,
            pytest.raises(PermanentModelError, match="does not support"),
        ):
            client.complete(MESSAGES, SamplingParams(max_tokens=64, seed=7))

    def test_seed_never_reaches_the_wire(self, anthropic_entry) -> None:
        seen = _capture(anthropic_entry, SAMPLING)
        assert "seed" not in seen["body"]


class TestResponseParsing:
    def test_content_usage_and_metadata(self, anthropic_entry) -> None:
        with _client(anthropic_entry, lambda r: httpx.Response(200, json=OK_BODY)) as client:
            result = client.complete(MESSAGES, SAMPLING)
        assert result.content == "Response text here"
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 20
        assert result.model == "claude-opus-4-5"
        assert result.request_id == "msg_1234567890"
        assert result.latency_ms >= 0
        assert result.raw == OK_BODY

    def test_multiple_text_blocks_concatenate(self, anthropic_entry) -> None:
        body = dict(
            OK_BODY, content=[{"type": "text", "text": "40"}, {"type": "text", "text": "2"}]
        )
        with _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client:
            assert client.complete(MESSAGES, SAMPLING).content == "402"

    def test_non_text_blocks_are_skipped_but_kept_in_raw(self, anthropic_entry) -> None:
        """A thinking block is not the answer, but it is evidence -- the
        transcript archives `raw` verbatim, so skipping it here loses nothing."""
        body = dict(
            OK_BODY,
            content=[
                {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                {"type": "text", "text": "42"},
            ],
        )
        with _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client:
            result = client.complete(MESSAGES, SAMPLING)
        assert result.content == "42"
        assert result.raw["content"][0]["type"] == "thinking"

    def test_empty_answer_on_max_tokens_is_an_error_not_a_zero(self, anthropic_entry) -> None:
        body = dict(
            OK_BODY,
            content=[{"type": "thinking", "thinking": "", "signature": "sig"}],
            stop_reason="max_tokens",
        )
        with (
            _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client,
            pytest.raises(PermanentModelError, match="max_tokens"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_text_answer_on_max_tokens_is_kept(self, anthropic_entry) -> None:
        body = dict(OK_BODY, stop_reason="max_tokens")
        with _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client:
            assert client.complete(MESSAGES, SAMPLING).content == "Response text here"

    def test_empty_content_is_honest_emptiness_not_an_error(self, anthropic_entry) -> None:
        """A refusal (not a max_tokens stop, which is an error above)."""
        body = dict(OK_BODY, content=[], stop_reason="refusal")
        with _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client:
            assert client.complete(MESSAGES, SAMPLING).content == ""

    def test_missing_usage_yields_honest_zeros_not_estimates(self, anthropic_entry) -> None:
        body = {"content": [{"type": "text", "text": "hi"}]}
        with _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client:
            assert client.complete(MESSAGES, SAMPLING).usage.total_tokens == 0

    def test_cache_tokens_are_not_folded_into_prompt_tokens(self, anthropic_entry) -> None:
        """They bill at different rates; summing them would misreport cost.
        They stay visible in `raw` instead of being silently mixed in."""
        body = dict(
            OK_BODY,
            usage={
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_creation_input_tokens": 500,
                "cache_read_input_tokens": 1000,
            },
        )
        with _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client:
            result = client.complete(MESSAGES, SAMPLING)
        assert result.usage.prompt_tokens == 10
        assert result.raw["usage"]["cache_read_input_tokens"] == 1000

    @pytest.mark.parametrize("body", [{}, {"content": "text"}, {"content": None}])
    def test_unexpected_shapes_are_permanent_errors(self, anthropic_entry, body) -> None:
        with (
            _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client,
            pytest.raises(PermanentModelError, match="unexpected body shape"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_non_string_text_is_a_permanent_error(self, anthropic_entry) -> None:
        body = dict(OK_BODY, content=[{"type": "text", "text": {"parts": ["x"]}}])
        with (
            _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client,
            pytest.raises(PermanentModelError, match="not a string"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_non_object_content_block_is_a_permanent_error(self, anthropic_entry) -> None:
        body = dict(OK_BODY, content=["42"])
        with (
            _client(anthropic_entry, lambda r: httpx.Response(200, json=body)) as client,
            pytest.raises(PermanentModelError, match="non-object content block"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_non_json_body_is_a_permanent_error(self, anthropic_entry) -> None:
        """A proxy or WAF answering instead of the API."""
        handler = lambda r: httpx.Response(200, text="<html>gateway</html>")  # noqa: E731
        with (
            _client(anthropic_entry, handler) as client,
            pytest.raises(PermanentModelError, match="non-JSON"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_request_id_falls_back_to_the_anthropic_header(self, anthropic_entry) -> None:
        """Anthropic returns `request-id`, not OpenAI's `x-request-id`."""
        body = {k: v for k, v in OK_BODY.items() if k != "id"}
        handler = lambda r: httpx.Response(  # noqa: E731
            200, json=body, headers={"request-id": "req_abc"}
        )
        with _client(anthropic_entry, handler) as client:
            assert client.complete(MESSAGES, SAMPLING).request_id == "req_abc"


class TestErrorPaths:
    def test_401_is_permanent_and_never_retried(self, anthropic_entry) -> None:
        anthropic_entry.max_retries = 5
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(
                401,
                json={
                    "type": "error",
                    "error": {"type": "authentication_error", "message": "invalid x-api-key"},
                },
            )

        with (
            _client(anthropic_entry, handler) as client,
            pytest.raises(PermanentModelError, match="invalid x-api-key") as exc,
        ):
            client.complete(MESSAGES, SAMPLING)
        assert exc.value.status_code == 401
        assert calls["n"] == 1, "a bad key does not get better by asking again"

    def test_429_is_retried_and_the_provider_message_survives(self, anthropic_entry) -> None:
        anthropic_entry.max_retries = 1
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(
                429,
                json={
                    "type": "error",
                    "error": {"type": "rate_limit_error", "message": "rate limit exceeded"},
                },
                headers={"retry-after": "2"},
            )

        with (
            _client(anthropic_entry, handler) as client,
            pytest.raises(TransientModelError, match="rate limit exceeded") as exc,
        ):
            client.complete(MESSAGES, SAMPLING)
        assert calls["n"] == 2
        assert exc.value.retry_after_s == 2.0

    def test_500_is_transient(self, anthropic_entry) -> None:
        anthropic_entry.max_retries = 0

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500, json={"type": "error", "error": {"type": "api_error", "message": "internal"}}
            )

        with (
            _client(anthropic_entry, handler) as client,
            pytest.raises(TransientModelError) as exc,
        ):
            client.complete(MESSAGES, SAMPLING)
        assert exc.value.status_code == 500

    def test_529_overloaded_is_transient(self, anthropic_entry) -> None:
        """Anthropic's documented overloaded_error. Not in the IANA registry, so
        it is easy to misclassify as permanent -- which would fail a whole run
        over a capacity blip."""
        anthropic_entry.max_retries = 0

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                529,
                json={
                    "type": "error",
                    "error": {"type": "overloaded_error", "message": "Overloaded"},
                },
            )

        with (
            _client(anthropic_entry, handler) as client,
            pytest.raises(TransientModelError, match="Overloaded"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_400_surfaces_the_providers_own_message(self, anthropic_entry) -> None:
        """`returned HTTP 400` points nowhere; the provider's text points at the
        models.yaml line that caused it."""
        anthropic_entry.max_retries = 0
        with (
            _client(anthropic_entry, lambda r: httpx.Response(400, json=ERROR_BODY)) as client,
            pytest.raises(PermanentModelError, match="roles must alternate"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_timeout_is_transient(self, anthropic_entry) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        anthropic_entry.max_retries = 0
        with (
            _client(anthropic_entry, handler) as client,
            pytest.raises(TransientModelError, match="timeout"),
        ):
            client.complete(MESSAGES, SAMPLING)

    def test_all_system_messages_is_a_permanent_error(self, anthropic_entry) -> None:
        with (
            _client(anthropic_entry, lambda r: httpx.Response(200, json=OK_BODY)) as client,
            pytest.raises(PermanentModelError, match="at least one user or assistant turn"),
        ):
            client.complete([ChatMessage(role="system", content="only this")], SAMPLING)


class TestMissingKeyIsLoud:
    def test_construction_without_a_declared_key_raises(self, anthropic_entry) -> None:
        """Never a silent unauthenticated request, and never a mock fallback."""
        with pytest.raises(MissingApiKeyError, match="ANTHROPIC_API_KEY"):
            AnthropicMessagesClient(anthropic_entry, api_key=None)

    def test_empty_string_key_counts_as_missing(self, anthropic_entry) -> None:
        with pytest.raises(MissingApiKeyError):
            AnthropicMessagesClient(anthropic_entry, api_key="")


class TestCostAccounting:
    def test_usage_prices_against_the_registrys_rates(self, anthropic_entry) -> None:
        """Pricing lives in models.yaml (`cost.*_usd_per_mtok`), never in code."""
        with _client(anthropic_entry, lambda r: httpx.Response(200, json=OK_BODY)) as client:
            result = client.complete(MESSAGES, SAMPLING)
        # 10 input tok @ $3/Mtok + 20 output tok @ $15/Mtok
        expected = (10 * 3.0 + 20 * 15.0) / 1_000_000
        assert result.usage.cost_usd(anthropic_entry.cost) == pytest.approx(expected)
