"""The Anthropic **Messages API** client.

Everything that is not wire format -- transport, timeouts, retry, backoff,
``Retry-After``, status classification -- comes from
:class:`~ida_harness.client.BaseChatClient`.  This module is only the four
things that genuinely differ from chat-completions:

===================  ======================================================
chat-completions     Messages API
===================  ======================================================
``Authorization``    ``x-api-key`` plus a required ``anthropic-version``
system in messages   ``system`` hoisted to a top-level field
``max_tokens`` opt   ``max_tokens`` REQUIRED
``choices[0]...``    ``content`` is a list of typed blocks
``prompt_tokens``    ``input_tokens`` / ``output_tokens``
===================  ======================================================

Reference: <https://platform.claude.com/docs/en/api/messages> (retrieved
2026-08-25).  The response fixtures in ``tests/test_anthropic_client.py`` are
copied from that page rather than invented, so a shape change upstream shows up
as a failing test instead of as a production 500.

Sampling parameters
-------------------
Anthropic's defaults are ``temperature=1.0`` and ``top_p=1.0``, and current
Claude models (Opus 5 / Sonnet 5 / Opus 4.8 / 4.7 and Fable 5) **reject a
non-default** ``temperature``/``top_p``/``top_k`` with a 400; Claude 4.x also
400s when both ``temperature`` and ``top_p`` are sent together.  So a parameter
sitting at Anthropic's default is omitted from the body.

That is not a silent drop.  The value we omit is exactly the value the endpoint
then uses, so the :class:`~ida_core.contracts.ServingConfig` stamped on every
result still describes what actually happened -- which is the whole of D-13.  A
*non-default* value is always sent: if the target model rejects it, the operator
gets Anthropic's own 400 text naming the parameter, not a benchmark quietly run
at a temperature nobody chose.
"""

from __future__ import annotations

from ida_core.contracts import ChatMessage, SamplingParams, TokenUsage
from ida_harness.client import BaseChatClient, ChatCompletion
from ida_harness.errors import PermanentModelError

ANTHROPIC_VERSION = "2023-06-01"
"""Value of the required ``anthropic-version`` header.

Pinned, not floated: this header is how the Messages API promises not to change
shape underneath a stored benchmark result.  Bumping it is a deliberate change
with a re-run attached, never an incidental one.
"""

ANTHROPIC_DEFAULT_TEMPERATURE = 1.0
ANTHROPIC_DEFAULT_TOP_P = 1.0


class AnthropicMessagesClient(BaseChatClient):
    """``POST {base_url}/messages`` against the Anthropic Messages API."""

    PATH = "/messages"
    REQUEST_ID_HEADER = "request-id"
    """Anthropic returns ``request-id``, not OpenAI's ``x-request-id``."""

    def _headers(self, api_key: str | None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    def _build_payload(self, messages: list[ChatMessage], sampling: SamplingParams) -> dict:
        if sampling.seed is not None:
            # The Messages API has no seed parameter. Dropping it silently would
            # leave a stored result claiming a seeded, reproducible run that was
            # never seeded -- the exact fabricated-measurement failure D-13
            # exists to prevent.
            raise PermanentModelError(
                f"model {self.entry.key!r} sets sampling.seed={sampling.seed}, which the "
                "Anthropic Messages API does not support; set serving.sampling.seed to null "
                "in models.yaml rather than recording a seed that was never applied"
            )

        system_blocks = [m.content for m in messages if m.role == "system"]
        turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        if not turns:
            raise PermanentModelError(
                f"model {self.entry.key!r}: the Messages API requires at least one user or "
                "assistant turn, but every message was a system message"
            )

        payload: dict = {
            "model": self.entry.serving.model_id,
            "messages": turns,
            # Required by this API, unlike chat-completions where it is optional.
            "max_tokens": sampling.max_tokens,
        }
        if system_blocks:
            # Multiple system messages collapse to one field; the transcript
            # still archives them separately, so nothing is lost from the record.
            payload["system"] = "\n\n".join(system_blocks)
        if sampling.temperature != ANTHROPIC_DEFAULT_TEMPERATURE:
            payload["temperature"] = sampling.temperature
        if sampling.top_p != ANTHROPIC_DEFAULT_TOP_P:
            payload["top_p"] = sampling.top_p
        if sampling.stop:
            payload["stop_sequences"] = list(sampling.stop)
        return payload

    def _parse(self, body: dict, latency_ms: float, request_id: str | None) -> ChatCompletion:
        blocks = body.get("content")
        if not isinstance(blocks, list):
            raise PermanentModelError(
                f"{self.entry.key} returned an unexpected body shape: {str(body)[:200]}"
            )

        texts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                raise PermanentModelError(
                    f"{self.entry.key} returned a non-object content block of type "
                    f"{type(block).__name__}"
                )
            if block.get("type") != "text":
                # thinking / tool_use / redacted blocks are not the answer, but
                # they ARE evidence: `raw` is archived verbatim into the
                # transcript, so nothing is discarded by skipping them here.
                continue
            text = block.get("text")
            if not isinstance(text, str):
                raise PermanentModelError(
                    f"{self.entry.key} returned a text block whose text is "
                    f"{type(text).__name__}, not a string"
                )
            texts.append(text)

        # An empty content list is honest emptiness, not an error: a refusal or
        # a max_tokens stop with only a thinking block both produce one, and a
        # scorer seeing "" is the truthful outcome.
        content = "".join(texts)

        raw_usage = body.get("usage") or {}
        if not isinstance(raw_usage, dict):
            raw_usage = {}
        usage = TokenUsage(
            # input_tokens EXCLUDES cache_creation_input_tokens and
            # cache_read_input_tokens, which bill at different rates. We never
            # send cache_control, so those are zero; folding them in here at the
            # standard rate would misreport cost the moment that changes. They
            # stay visible in `raw`.
            prompt_tokens=int(raw_usage.get("input_tokens", 0) or 0),
            completion_tokens=int(raw_usage.get("output_tokens", 0) or 0),
        )
        return ChatCompletion(
            content=content,
            usage=usage,
            latency_ms=latency_ms,
            model=str(body.get("model") or self.entry.serving.model_id),
            request_id=body.get("id") or request_id,
            raw=body,
        )
