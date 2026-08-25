"""HTTP clients for model endpoints, and the contract they all satisfy (**D-1**).

One protocol, one retry loop, one error taxonomy
------------------------------------------------
:class:`ModelClient` is the contract the rest of the harness codes against --
the solver, the runner and the cache all speak it and none of them knows which
provider answered.  :class:`BaseChatClient` implements *everything that is not
wire format*: transport ownership, timeouts, retry/backoff, ``Retry-After``,
status classification, JSON guarding and latency measurement.  A concrete client
supplies four things and nothing else:

``PATH``            the endpoint path appended to the resolved base URL
``_headers``        how the key is presented
``_build_payload``  how a request body is shaped
``_parse``          how content + usage are read back out

**This is not a relaxation of D-1.**  D-1's invariant is "adding a model is a
YAML edit, not a code change", and it still holds: ``serving_stack`` in
``models.yaml`` selects the client (see :mod:`ida_harness.factory`), and there
is no ``if provider == ...`` inside any client.  What D-1's original comment
assumed -- that one OpenAI-shaped body reaches every provider -- turned out not
to survive contact with Anthropic's Messages API, which is a genuinely different
wire format (``system`` hoisted out of ``messages``, ``content`` as a block
list, ``input_tokens``/``output_tokens``).  Squeezing it through the
chat-completions shape would mean either a translation layer that lies about
what was sent, or Anthropic's thinner OpenAI-compatibility surface.  Two
subclasses of one base is the smaller cost.  See ``docs/model-clients.md``.

Retry policy
------------
Exponential backoff with full jitter on :class:`TransientModelError` only, up to
``entry.max_retries`` *additional* attempts.  Permanent errors fail immediately
-- retrying a 401 just burns the rate limit and delays the real error.  A
``Retry-After`` header raises the floor of the next delay; an implausibly long
one (see :data:`MAX_HONOURED_RETRY_AFTER_S`) stops the retry loop instead of
parking a runner pod on a quota that will not come back in time.

Determinism note: jitter uses a caller-supplied ``sleep``/``jitter`` pair so
tests can make backoff deterministic without patching the clock globally.
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol, runtime_checkable

import httpx

from ida_core.contracts import ChatMessage, ModelEntry, SamplingParams, TokenUsage
from ida_core.registry import MissingApiKeyError, resolve_base_url
from ida_harness.errors import PermanentModelError, TransientModelError

TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
"""HTTP statuses worth retrying.  Everything else in 4xx/5xx is permanent.

529 is Anthropic's ``overloaded_error`` -- a documented, explicitly retryable
"we are busy right now" that is not in the IANA registry.  Classifying it as
permanent would turn a transient capacity blip into a failed benchmark run.
"""

DEFAULT_BACKOFF_BASE_S = 0.5
DEFAULT_BACKOFF_MAX_S = 30.0

MAX_HONOURED_RETRY_AFTER_S = 120.0
"""Longest ``Retry-After`` we will actually wait out.

Beyond this the provider is not saying "try again shortly", it is saying "your
quota is gone for a while".  Sleeping on it holds a runner pod hostage; ignoring
it and retrying anyway hammers an endpoint that already said no.  We do neither:
the attempt loop stops and the error says how long was asked for, so the failure
names its own cause instead of surfacing as a generic 429 three attempts later.
"""


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


@runtime_checkable
class ModelClient(Protocol):
    """What the harness needs from a model endpoint, and all it needs.

    Deliberately narrow: the solver and runner are written against this, so a
    new provider is a new implementation rather than an edit to either.
    """

    def complete(self, messages: list[ChatMessage], sampling: SamplingParams) -> ChatCompletion:
        """Send one completion request, retrying transient failures."""

    def close(self) -> None:
        """Release the underlying connection pool."""

    def __enter__(self) -> ModelClient: ...

    def __exit__(self, *exc_info: object) -> None: ...


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


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a ``Retry-After`` header value, or ``None``.

    Only the delta-seconds form is honoured.  The HTTP-date form is legal but
    neither Anthropic nor OpenAI sends it, and interpreting it correctly means
    trusting our clock against theirs -- so an unparseable value falls back to
    our own backoff rather than to a guessed delay.
    """
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def provider_error_detail(response: httpx.Response) -> str:
    """The provider's own error message, when it sent one.

    Both surfaces nest it identically -- OpenAI as
    ``{"error": {"message": ...}}`` and Anthropic as
    ``{"type": "error", "error": {"message": ...}}`` -- so reading it is one
    shape, not a per-provider branch.  It matters because the generic
    "returned HTTP 400" tells an operator nothing, while
    ``temperature: Extra inputs are not permitted`` points straight at the
    ``models.yaml`` line that caused it.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:300]
    return response.text[:300]


class BaseChatClient(ABC):
    """Transport, retry and error handling shared by every provider client.

    Construct one per model per run; it owns an ``httpx.Client`` and must be
    closed (it is a context manager).
    """

    PATH: ClassVar[str]
    """Path appended to the resolved base URL, e.g. ``/chat/completions``."""

    REQUEST_ID_HEADER: ClassVar[str] = "x-request-id"
    """Response header carrying the provider's request id, for support tickets."""

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
        if entry.api_key_env and not api_key:
            # Loud at construction, not a silent unauthenticated request that
            # comes back as a 401 far from its cause. There is deliberately NO
            # mock fallback: a stand-in model scored under a frontier model's
            # name would poison the results table, and a poisoned number is
            # worse than a failed run because nothing downstream can tell.
            raise MissingApiKeyError(
                f"model {entry.key!r} declares api_key_env={entry.api_key_env!r} but no key "
                f"was supplied; set {entry.api_key_env} in the environment (locally in .env, "
                "in-cluster projected from Vault). The harness will not fall back to a "
                "stand-in model."
            )
        self._client = httpx.Client(
            # resolve_base_url, NOT entry.base_url: the endpoint is env-indirect
            # so that ONE promoted image can point at the mock in dev and at a
            # real provider in prod. Reading the literal here would silently
            # defeat the safety switch.
            base_url=resolve_base_url(entry).rstrip("/"),
            headers=self._headers(api_key),
            timeout=entry.timeout_s,
            transport=transport,
        )
        self._sleep = sleep
        self._jitter = jitter

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- provider surface ------------------------------------------------

    @abstractmethod
    def _headers(self, api_key: str | None) -> dict[str, str]:
        """Request headers, including however this provider presents the key."""

    @abstractmethod
    def _build_payload(self, messages: list[ChatMessage], sampling: SamplingParams) -> dict:
        """The request body for one completion."""

    @abstractmethod
    def _parse(self, body: dict, latency_ms: float, request_id: str | None) -> ChatCompletion:
        """Read content, usage and metadata out of a successful response body."""

    # -- shared machinery ------------------------------------------------

    def complete(self, messages: list[ChatMessage], sampling: SamplingParams) -> ChatCompletion:
        """Send one completion, retrying transient failures.

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
                if exc.retry_after_s is not None and exc.retry_after_s > MAX_HONOURED_RETRY_AFTER_S:
                    # Retrying now would hammer an endpoint that just told us
                    # how long it will stay closed; waiting it out would park
                    # the worker. Stop, and say which it was.
                    break
                self._sleep(self._next_delay(attempt, exc.retry_after_s))

        # An invariant, not input validation: every path out of the loop above
        # assigns last_error first. S101 warns because `python -O` strips
        # asserts -- which is fine here, since stripping it leaves
        # `raise last_error` raising the same value it would have anyway.
        assert last_error is not None  # noqa: S101
        raise last_error

    def _next_delay(self, attempt: int, retry_after_s: float | None) -> float:
        """Backoff for the next attempt, floored by any ``Retry-After``.

        ``max`` rather than "prefer the header": a provider asking for 0.5s
        while we are three attempts into a 503 storm should not reset us to a
        half-second poll, and full jitter must survive either way.
        """
        delay = backoff_delay(attempt, jitter=self._jitter)
        if retry_after_s is not None:
            delay = max(delay, retry_after_s)
        return delay

    def _attempt(self, payload: dict) -> ChatCompletion:
        started = time.perf_counter()
        try:
            response = self._client.post(self.PATH, json=payload)
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

        return self._parse(body, latency_ms, response.headers.get(self.REQUEST_ID_HEADER))

    def _raise_for_status(self, response: httpx.Response) -> None:
        detail = provider_error_detail(response)
        message = f"{self.entry.key} returned HTTP {response.status_code}: {detail}"
        if response.status_code in TRANSIENT_STATUS_CODES:
            retry_after_s = parse_retry_after(response.headers.get("retry-after"))
            if retry_after_s is not None and retry_after_s > MAX_HONOURED_RETRY_AFTER_S:
                message = (
                    f"{message} (provider asked for {retry_after_s:g}s, over the "
                    f"{MAX_HONOURED_RETRY_AFTER_S:g}s we will wait -- not retried)"
                )
            raise TransientModelError(
                message, status_code=response.status_code, retry_after_s=retry_after_s
            )
        raise PermanentModelError(message, status_code=response.status_code)


class OpenAICompatibleClient(BaseChatClient):
    """Chat-completions client for any OpenAI-compatible endpoint.

    Reaches OpenAI itself, campus vLLM, a laptop llama.cpp and the mock model
    -- the only thing that differs between them is the base URL, the key and
    the serving config recorded alongside the answer.
    """

    PATH = "/chat/completions"
    REQUEST_ID_HEADER = "x-request-id"

    def _headers(self, api_key: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

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
