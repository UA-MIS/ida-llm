"""The one OpenAI-compatible chat client (**D-1**).

There is exactly one HTTP client in this codebase and it speaks
``POST {base_url}/chat/completions``.  Hosted APIs, campus vLLM, a laptop
llama.cpp and the mock model are all reached through it; the only thing that
differs is the base URL, the key and the serving config recorded alongside the
answer.  If you ever find yourself adding ``if provider == ...`` here, D-1 has
been violated.

Retry policy
------------
Exponential backoff with full jitter on :class:`TransientModelError` only, up to
``entry.max_retries`` *additional* attempts.  Permanent errors fail immediately
-- retrying a 401 just burns the rate limit and delays the real error.

Determinism note: jitter uses a caller-supplied ``sleep``/``jitter`` pair so
tests can make backoff deterministic without patching the clock globally.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from ida_core.contracts import ChatMessage, ModelEntry, SamplingParams, TokenUsage
from ida_core.registry import resolve_base_url
from ida_harness.errors import PermanentModelError, TransientModelError

TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
"""HTTP statuses worth retrying.  Everything else in 4xx/5xx is permanent."""

DEFAULT_BACKOFF_BASE_S = 0.5
DEFAULT_BACKOFF_MAX_S = 30.0


@dataclass(frozen=True)
class ChatCompletion:
    """A model's answer plus everything needed to account for it.

    ``usage`` is what the endpoint reported.  Endpoints that omit ``usage``
    (some local servers do) yield zeros -- we record the honest zero rather
    than estimating, because an estimated token count that looks like a
    measurement is worse than a visible gap.
    """

    content: str
    usage: TokenUsage
    latency_ms: float
    model: str
    """The model id the endpoint *says* it used.  May differ from what we asked."""

    request_id: str | None
    raw: dict
    """Verbatim response JSON.  Archived into the transcript for forensics."""


def backoff_delay(
    attempt: int,
    *,
    base_s: float = DEFAULT_BACKOFF_BASE_S,
    max_s: float = DEFAULT_BACKOFF_MAX_S,
    jitter: Callable[[float], float] = random.uniform,
) -> float:
    """Full-jitter exponential backoff for a 1-based ``attempt``.

    ``attempt=1`` -> uniform in ``[0, base]``, ``attempt=2`` -> ``[0, 2*base]``,
    capped at ``max_s``.  Full jitter (rather than fixed exponential) is what
    stops a fleet of runner pods from retrying in lockstep after a vLLM restart.
    """
    if attempt < 1:
        raise ValueError("attempt is 1-based")
    ceiling = min(max_s, base_s * (2 ** (attempt - 1)))
    return jitter(0.0, ceiling)


class OpenAICompatibleClient:
    """Chat-completions client for any OpenAI-compatible endpoint.

    Construct one per model per run; it owns an ``httpx.Client`` and must be
    closed (it is a context manager).
    """

    def __init__(
        self,
        entry: ModelEntry,
        *,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.entry = entry
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            # resolve_base_url, NOT entry.base_url: the endpoint is env-indirect
            # so that ONE promoted image can point at the mock in dev and at a
            # real provider in prod. Reading the literal here would silently
            # defeat the safety switch.
            base_url=resolve_base_url(entry).rstrip("/"),
            headers=headers,
            timeout=entry.timeout_s,
            transport=transport,
        )
        self._sleep = sleep
        self._jitter = jitter

    def __enter__(self) -> OpenAICompatibleClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------

    def complete(self, messages: list[ChatMessage], sampling: SamplingParams) -> ChatCompletion:
        """Send one chat completion, retrying transient failures.

        Raises :class:`~ida_harness.errors.PermanentModelError` immediately on a
        non-retryable failure, or after the final attempt if every attempt was
        transient (the last transient error is re-raised as-is).
        """
        payload = self._build_payload(messages, sampling)
        last_error: TransientModelError | None = None

        for attempt in range(1, self.entry.max_retries + 2):  # 1 try + N retries
            try:
                return self._attempt(payload)
            except TransientModelError as exc:
                last_error = exc
                if attempt > self.entry.max_retries:
                    break
                self._sleep(backoff_delay(attempt, jitter=self._jitter))

        # An invariant, not input validation: every path out of the loop above
        # assigns last_error first. S101 warns because `python -O` strips
        # asserts -- which is fine here, since stripping it leaves
        # `raise last_error` raising the same value it would have anyway.
        assert last_error is not None  # noqa: S101
        raise last_error

    def _build_payload(self, messages: list[ChatMessage], sampling: SamplingParams) -> dict:
        """Build the request body.

        ``seed`` and ``stop`` are omitted when unset rather than sent as null:
        several OpenAI-compatible servers reject explicit nulls for those keys.
        """
        payload: dict = {
            "model": self.entry.serving.model_id,
            "messages": [m.model_dump() for m in messages],
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "max_tokens": sampling.max_tokens,
            "stream": False,
        }
        if sampling.seed is not None:
            payload["seed"] = sampling.seed
        if sampling.stop:
            payload["stop"] = sampling.stop
        return payload

    def _attempt(self, payload: dict) -> ChatCompletion:
        started = time.perf_counter()
        try:
            response = self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise TransientModelError(f"timeout calling {self.entry.key}: {exc}") from exc
        except httpx.TransportError as exc:
            raise TransientModelError(f"transport error calling {self.entry.key}: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000.0

        if response.status_code >= 400:
            self._raise_for_status(response)

        try:
            body = response.json()
        except ValueError as exc:
            raise PermanentModelError(
                f"{self.entry.key} returned non-JSON body: {response.text[:200]!r}"
            ) from exc

        return self._parse(body, latency_ms, response.headers.get("x-request-id"))

    def _raise_for_status(self, response: httpx.Response) -> None:
        snippet = response.text[:300]
        message = f"{self.entry.key} returned HTTP {response.status_code}: {snippet}"
        if response.status_code in TRANSIENT_STATUS_CODES:
            raise TransientModelError(message, status_code=response.status_code)
        raise PermanentModelError(message, status_code=response.status_code)

    def _parse(self, body: dict, latency_ms: float, request_id: str | None) -> ChatCompletion:
        """Extract content + usage from an OpenAI-shaped response body."""
        try:
            choices = body["choices"]
            content = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PermanentModelError(
                f"{self.entry.key} returned an unexpected body shape: {str(body)[:200]}"
            ) from exc
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise PermanentModelError(
                f"{self.entry.key} returned non-string content of type {type(content).__name__}"
            )

        raw_usage = body.get("usage") or {}
        usage = TokenUsage(
            prompt_tokens=int(raw_usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(raw_usage.get("completion_tokens", 0) or 0),
        )
        return ChatCompletion(
            content=content,
            usage=usage,
            latency_ms=latency_ms,
            model=str(body.get("model") or self.entry.serving.model_id),
            request_id=body.get("id") or request_id,
            raw=body,
        )
