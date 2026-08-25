"""Pick a client for a registry entry.  The one place providers are named.

This is the seam that keeps **D-13** true (the reproducibility decision; the
D-1..D-12 stubs are empty, so the real record is D-13).  Its invariant is *"adding a model is
an edit to ``models.yaml``, not a code change"*, and it survives intact: the
entry's ``serving.serving_stack`` -- a field the registry author already had to
write, because it is part of the reproducibility record -- selects the client.
Nothing else in the harness knows a provider exists, and no client contains an
``if provider == ...``.

Contract resolution (worth knowing before you edit this table)
--------------------------------------------------------------
The scaffold's comment in ``models.yaml`` said Anthropic "exposes an
OpenAI-compatible surface, so it needs no special-casing".  That is true of
Anthropic's compatibility shim and false of the Messages API, which is what the
story asked for and what the Console, the docs and the pricing page all describe.
The shim is a translation layer in front of the real thing; benchmarking through
it would mean recording numbers produced by a surface we did not choose and
cannot version.  So ``anthropic_compat`` now selects
:class:`~ida_harness.anthropic_client.AnthropicMessagesClient`.

The enum member's *name* is now slightly wrong -- it reads "compat" but means
"Anthropic-native".  Renaming :class:`ida_core.contracts.ServingStack` is a core
contract change with a JSON-schema edit and stored ``serving_config`` blobs
behind it, so it is deliberately NOT done here; see ``docs/model-clients.md``.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import httpx

from ida_core.contracts import ModelEntry, ServingStack
from ida_core.registry import resolve_api_key
from ida_harness.anthropic_client import AnthropicMessagesClient
from ida_harness.client import BaseChatClient, ModelClient, OpenAICompatibleClient

CLIENT_BY_SERVING_STACK: dict[ServingStack, type[BaseChatClient]] = {
    ServingStack.ANTHROPIC_COMPAT: AnthropicMessagesClient,
}
"""Serving stacks that need something other than the chat-completions shape.

Everything absent from this table -- ``openai_api``, ``vllm``, ``ollama``,
``llama_cpp``, ``mock`` -- is OpenAI-compatible and uses
:class:`~ida_harness.client.OpenAICompatibleClient`.  That default is the point:
a new vLLM deployment or a laptop llama.cpp server is a YAML edit and touches no
code at all.
"""

DEFAULT_CLIENT: type[BaseChatClient] = OpenAICompatibleClient


def client_class_for(entry: ModelEntry) -> type[BaseChatClient]:
    """The client class ``entry`` will be served by."""
    return CLIENT_BY_SERVING_STACK.get(entry.serving.serving_stack, DEFAULT_CLIENT)


def build_client(
    entry: ModelEntry,
    *,
    api_key: str | None = None,
    env: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[float, float], float] = random.uniform,
) -> ModelClient:
    """Build the right client for ``entry``, resolving its key if needed.

    ``env`` overrides the environment used for KEY lookup only (tests); the base
    URL always resolves against the real process environment, because that is the
    promoted-image safety switch and a test-only override of it would let a test
    pass against an endpoint production cannot reach.

    ``api_key`` is for callers that already resolved one (the runner service
    does, so it can fail a job before any work starts).  Left unset, the key is
    read from the environment variable the entry names -- and a missing one
    raises :class:`~ida_core.registry.MissingApiKeyError` naming that variable.

    There is **no mock fallback** at any point in this function.  An
    unconfigured provider fails; it never quietly becomes a stand-in whose
    answers would be stored under the real model's name.
    """
    if api_key is None and entry.api_key_env:
        api_key = resolve_api_key(entry, env)
    return client_class_for(entry)(
        entry,
        api_key=api_key,
        transport=transport,
        sleep=sleep,
        jitter=jitter,
    )
