"""HTTP clients for model endpoints, and the contract they all satisfy (**D-13**).

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

**This is not a relaxation of D-13** (the reproducibility decision, logged as
D-13; the D-1..D-12 stubs are empty, so cite D-13).  Its invariant is "adding a model is a
YAML edit, not a code change", and it still holds: ``serving_stack`` in
``models.yaml`` selects the client (see :mod:`ida_harness.factory`), and there
is no ``if provider == ...`` inside any client.  What the original comment
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

import json
import random
import re
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
    jitter: Callable[[float, float], float] = random.uniform,
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


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_UNCLOSED_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_thinking(content: str) -> str:
    """Remove inline ``<think>...</think>`` blocks, leaving only the answer.

    Also drops a lone leading ``...</think>`` (chat templates that open the tag
    in the prompt) and an unterminated ``<think>`` tail (truncated mid-thought),
    which leaves an empty answer for the caller to refuse rather than score.
    Content without any tag is returned untouched.
    """
    if "think>" not in content.lower():
        return content
    out = _THINK_BLOCK_RE.sub("", content)
    head, sep, tail = out.partition("</think>")
    if sep and "<think>" not in head.lower():
        out = tail
    return _THINK_UNCLOSED_RE.sub("", out).strip()


def _finish_reason(body: dict) -> str | None:
    try:
        return body["choices"][0].get("finish_reason")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


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
        # Opt-in per entry through `serving.extra` (recorded with every result):
        #   stream: true               -- see _attempt_stream
        #   chat_template_kwargs: {..} -- vLLM chat-template switches, e.g.
        #                                 {"enable_thinking": false}
        extra = self.entry.serving.extra
        if extra.get("stream"):
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        if extra.get("chat_template_kwargs"):
            payload["chat_template_kwargs"] = extra["chat_template_kwargs"]
        return payload

    def _attempt(self, payload: dict) -> ChatCompletion:
        if payload.get("stream"):
            return self._attempt_stream(payload)
        return super()._attempt(payload)

    def _attempt_stream(self, payload: dict) -> ChatCompletion:
        """One completion over server-sent events, accumulated into a whole body.

        WHY. The campus endpoint sits behind Cloudflare, which cuts a
        NON-streaming response at ~30s. A 27B model that thinks can exceed that
        on a long answer; streamed bytes keep the connection alive. The chunks
        are folded back into the single body `_parse` already understands, so
        everything downstream (think-stripping, usage, scoring) is unchanged.
        `reasoning_content` deltas are consumed but not kept: thinking is not
        the answer.
        """
        started = time.perf_counter()
        content: list[str] = []
        finish_reason = None
        usage: dict | None = None
        chunk_id = None
        model = None
        try:
            with self._client.stream("POST", self.PATH, json=payload) as response:
                if response.status_code >= 400:
                    response.read()
                    self._raise_for_status(response)
                request_id = response.headers.get(self.REQUEST_ID_HEADER)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError as exc:
                        raise PermanentModelError(
                            f"{self.entry.key} sent a non-JSON stream chunk: {data[:200]!r}"
                        ) from exc
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("error"):
                        raise TransientModelError(
                            f"{self.entry.key} errored mid-stream: {str(chunk['error'])[:200]}"
                        )
                    chunk_id = chunk.get("id") or chunk_id
                    model = chunk.get("model") or model
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if isinstance(delta.get("content"), str):
                            content.append(delta["content"])
                        finish_reason = choice.get("finish_reason") or finish_reason
        except httpx.TimeoutException as exc:
            raise TransientModelError(f"timeout calling {self.entry.key}: {exc}") from exc
        except httpx.TransportError as exc:
            raise TransientModelError(f"transport error calling {self.entry.key}: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000.0
        body = {
            "id": chunk_id,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "".join(content)},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": usage or {},
        }
        return self._parse(body, latency_ms, request_id)

    def _empty_on_length_message(self) -> str:
        return (
            f"{self.entry.key} returned an EMPTY answer after stopping on 'length': the "
            f"output budget was consumed (by thinking, or an unterminated <think> block) "
            f"before any answer was produced. That is a missing measurement, not a 0.0. "
            f"Raise serving.sampling.max_tokens (currently "
            f"{self.entry.serving.sampling.max_tokens})."
        )

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
        # Thinking models served without a reasoning parser leave their chain of
        # thought inline as <think>...</think>. Scoring that would break exact
        # match, so only the answer is kept. (Servers WITH a parser put the
        # thinking in `reasoning_content` and never reach this.)
        content = strip_thinking(content)
        if not content.strip() and _finish_reason(body) == "length":
            raise PermanentModelError(self._empty_on_length_message())

        # Mirrors the Anthropic client: a flaky local server (vLLM, llama.cpp)
        # returning a non-dict `usage` must land in the same
        # PermanentModelError bucket as every other malformed shape, not
        # escape as a bare AttributeError the runner does not catch.
        raw_usage = body.get("usage") or {}
        if not isinstance(raw_usage, dict):
            raise PermanentModelError(
                f"{self.entry.key} returned a non-object usage of type {type(raw_usage).__name__}"
            )
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


OPENAI_REASONING_DEFAULT_TEMPERATURE = 1.0
OPENAI_REASONING_DEFAULT_TOP_P = 1.0
"""OpenAI's own defaults for these two parameters.

Named constants rather than literals because the omission logic below is only
correct while they ARE the endpoint's defaults: we drop a parameter on the claim
that the server will use this exact value, and the stored
:class:`~ida_core.contracts.ServingConfig` repeats that claim to anyone reading
the results table later.
"""


class OpenAIReasoningClient(OpenAICompatibleClient):
    """Chat-completions as the OpenAI **reasoning** families speak it.

    Same URL, same headers, same response shape -- so everything except
    :meth:`_build_payload` is inherited.  Two request-shape facts differ, and
    both are 400s rather than degradations:

    ``max_tokens``
        Rejected outright: *"Unsupported parameter: 'max_tokens' is not
        supported with this model. Use 'max_completion_tokens' instead."*  The
        o-series and the GPT-5/5.4/5.5/5.6 families all refuse it.  The
        replacement bounds *visible output tokens plus reasoning tokens*, which
        is a genuinely different quantity from the legacy cap -- another reason
        this is a separate stack and not a rename.

    ``temperature`` / ``top_p``
        Only the API default (1.0) is accepted.

    Why a subclass and not a flag on the parent
    -------------------------------------------
    Because it is a wire format, and wire formats are what
    ``serving_stack`` selects (:mod:`ida_harness.factory`).  Adding
    ``if reasoning:`` to the shared payload builder would put a provider's
    quirks inside the client every other OpenAI-compatible server also uses --
    a campus vLLM box, a laptop llama.cpp -- and those accept the legacy name.
    An entry opts in by writing ``serving_stack: openai_reasoning``, so this
    stays a YAML decision (**D-13**) and no code names a model.

    What this client deliberately does NOT do
    -----------------------------------------
    It does not guess which ``model_id`` values are reasoning models.  The
    registry author declares the dialect; sniffing model ids would invent a
    boundary OpenAI does not publish, and would be wrong the day they ship a
    model that does not match the pattern.  :mod:`ida_harness.preflight` warns
    about the combinations that cannot work, at authoring time, where it is
    cheap to fix.
    """

    def _build_payload(self, messages: list[ChatMessage], sampling: SamplingParams) -> dict:
        """The chat-completions body, in the reasoning dialect.

        A parameter already at OpenAI's default is omitted -- the same contract
        :class:`~ida_harness.anthropic_client.AnthropicMessagesClient` makes, and
        for the same reason: the omitted value is exactly the value the endpoint
        then uses, so the recorded ``ServingConfig`` stays true.

        A **non-default** value is always sent.  Dropping it would mean storing a
        result that claims a temperature the run never used, which is the
        fabricated-measurement failure the whole reproducibility record exists to
        prevent.  If the target model refuses it, the operator gets OpenAI's own
        400 naming the parameter.
        """
        payload: dict = {
            "model": self.entry.serving.model_id,
            "messages": [m.model_dump() for m in messages],
            # NOT `max_tokens`: see the class docstring. This bounds visible
            # output PLUS reasoning tokens.
            "max_completion_tokens": sampling.max_tokens,
            "stream": False,
        }
        if sampling.temperature != OPENAI_REASONING_DEFAULT_TEMPERATURE:
            payload["temperature"] = sampling.temperature
        if sampling.top_p != OPENAI_REASONING_DEFAULT_TOP_P:
            payload["top_p"] = sampling.top_p
        # chat-completions HAS a seed field, unlike the Messages API, so it is
        # forwarded rather than refused. Hosted models honour it best-effort at
        # most; that limitation belongs in the entry's comment, not in a client
        # that pretends the parameter does not exist.
        if sampling.seed is not None:
            payload["seed"] = sampling.seed
        if sampling.stop:
            payload["stop"] = sampling.stop
        return payload

    def _empty_on_length_message(self) -> str:
        """The wording of the base client's empty-answer-on-``length`` refusal.

        ``max_completion_tokens`` is shared between reasoning tokens and the
        visible answer.  When the budget is too small the model spends all of it
        thinking and stops with ``finish_reason: "length"`` and empty content.

        That response is perfectly well-formed, so the inherited parser returns
        an honest empty completion -- and the scorer downstream grades it
        **0.0**, storing "the model got this wrong".  It did not get it wrong; it
        was never given room to answer.  A benchmark that cannot distinguish
        those two is manufacturing data, so this is an error, and a permanent
        one: retrying spends the same budget to hit the same wall.

        The check is deliberately narrow -- empty **and** truncated:

        * a truncated but non-empty answer is a real response that a scorer may
          legitimately mark wrong, so it is returned;
        * an empty answer that stopped normally is honest emptiness (a refusal,
          say) and is also a real measurement;
        * a missing ``finish_reason`` -- several OpenAI-compatible servers omit
          it -- is not evidence of truncation and is left alone.
        """
        return (
            f"{self.entry.key} returned an EMPTY answer after stopping on 'length': the "
            f"reasoning budget was consumed before any visible output was produced. This is "
            f"not a score of 0.0, it is a missing measurement. Raise "
            f"serving.sampling.max_tokens for {self.entry.key!r} in models.yaml -- it is sent "
            f"as `max_completion_tokens` and covers reasoning tokens as well as the answer "
            f"(currently {self.entry.serving.sampling.max_tokens})."
        )
