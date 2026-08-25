"""Sample-level caching (**D-4**: the Inspect AI concept, our implementation).

Why it matters: re-running a 500-sample task after fixing one scorer bug should
not cost 500 API calls.  The cache key must therefore cover *everything that
could change the answer* and nothing that cannot:

    key = sha256(model_id | serving_stack | quantization | revision |
                 sampling params | task_id | task_content_sha | sample_id | input)

Note ``task_content_sha`` -- the hash of *this task's* canonicalised definition
(:attr:`ida_core.contracts.TaskSpec.content_sha`) -- and **not** the repo-wide
``task_git_sha``.  That distinction is the difference between a cache that works
and one that cannot: the motivating scenario above ("fix one scorer bug") *is a
commit*, so keying on the repo SHA would invalidate every entry on every commit,
including a README typo.  Edit a task, get a miss; edit anything else, keep the
cache.

Note the *scorer* config is **not** in the key: changing a tolerance must not
force a re-query, which is exactly the case the cache exists for.

What is cached
--------------
A :class:`CachedCompletion` -- the answer **and the messages that produced it**.
Storing only the answer would leave a cache hit unable to reconstruct its own
transcript, and that transcript is the D-3 evidence a score is cited against.
A result whose evidence is an empty message list is not citable.

The skeleton ships the interface and a :class:`NullCache` (always misses), which
is what the tracer bullet runs with.  A Redis- or MinIO-backed implementation
drops in without touching the runner.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ida_core.contracts import ChatMessage, SamplingParams, ServingConfig, TaskSample
from ida_harness.client import ChatCompletion


def cache_key(
    *,
    serving: ServingConfig,
    sampling: SamplingParams,
    task_id: str,
    task_content_sha: str | None,
    sample: TaskSample,
    repeat_index: int = 0,
) -> str:
    """Deterministic cache key.  Stable across processes and machines.

    ``repeat_index`` participates so that repeated sampling (B7) does not
    collapse to one cached answer -- the whole point of self-consistency is
    getting *different* completions for the same input.
    """
    material = {
        "model_id": serving.model_id,
        "serving_stack": serving.serving_stack.value,
        "quantization": serving.quantization.value,
        "revision": serving.revision,
        "sampling": sampling.model_dump(mode="json"),
        "task_id": task_id,
        "task_content_sha": task_content_sha,
        "sample_id": sample.id,
        "input": sample.input,
        "repeat_index": repeat_index,
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class CachedCompletion:
    """A cached answer together with the exchange that produced it.

        ``messages`` is what makes a cache hit's archived transcript faithful.
        Without it the object at ``runs/<run_id>/transcripts/<sample_id>.json``
    (or ``.../<sample_id>/r<n>.json`` for a repetition) --
        the thing the UI links to as evidence -- would contain an empty prompt.
    """

    messages: list[ChatMessage]
    completion: ChatCompletion


@runtime_checkable
class CompletionCache(Protocol):
    """Read-through cache of model exchanges, keyed by :func:`cache_key`."""

    def get(self, key: str) -> CachedCompletion | None:
        """Return a cached exchange, or ``None`` on a miss."""

    def put(self, key: str, entry: CachedCompletion) -> None:
        """Store an exchange.  Must be safe to call concurrently."""


class NullCache:
    """Always misses, never stores.  The skeleton's default.

    A real implementation, not a stub: "no caching" is a legitimate and correct
    configuration, and it is the one the tracer bullet uses so that every run
    genuinely exercises the HTTP path.
    """

    def get(self, key: str) -> CachedCompletion | None:
        return None

    def put(self, key: str, entry: CachedCompletion) -> None:
        return None


class InMemoryCache:
    """Process-local cache.  Useful in tests and for a single-process backfill."""

    def __init__(self) -> None:
        self._store: dict[str, CachedCompletion] = {}

    def get(self, key: str) -> CachedCompletion | None:
        return self._store.get(key)

    def put(self, key: str, entry: CachedCompletion) -> None:
        self._store[key] = entry
