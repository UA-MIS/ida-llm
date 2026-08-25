"""Cache-key semantics. What is in the key -- and what is deliberately not."""

from __future__ import annotations

from ida_core.contracts import (
    Quantization,
    SamplingParams,
    ServingConfig,
    ServingStack,
    TaskSample,
    TokenUsage,
)
from ida_harness.cache import InMemoryCache, NullCache, cache_key
from ida_harness.client import ChatCompletion


def _serving(**overrides) -> ServingConfig:
    base = {
        "model_id": "m",
        "serving_stack": ServingStack.MOCK,
        "quantization": Quantization.NONE,
    }
    base.update(overrides)
    return ServingConfig(**base)


def _key(**overrides) -> str:
    base = {
        "serving": _serving(),
        "sampling": SamplingParams(temperature=0.0, seed=1),
        "task_id": "t",
        "task_content_sha": "a" * 64,
        "sample": TaskSample(id="s", input="q", target="a"),
    }
    base.update(overrides)
    return cache_key(**base)


class TestCacheKey:
    def test_is_deterministic(self) -> None:
        assert _key() == _key()

    def test_is_a_sha256_hexdigest(self) -> None:
        assert len(_key()) == 64

    def test_model_id_matters(self) -> None:
        assert _key() != _key(serving=_serving(model_id="other"))

    def test_quantization_matters(self) -> None:
        """Same weights at int4 are not the same model for benchmarking purposes."""
        assert _key() != _key(serving=_serving(quantization=Quantization.INT4))

    def test_serving_stack_matters(self) -> None:
        assert _key() != _key(serving=_serving(serving_stack=ServingStack.VLLM))

    def test_revision_matters(self) -> None:
        assert _key() != _key(serving=_serving(revision="v2"))

    def test_sampling_matters(self) -> None:
        assert _key() != _key(sampling=SamplingParams(temperature=0.7, seed=1))

    def test_seed_matters(self) -> None:
        assert _key() != _key(sampling=SamplingParams(temperature=0.0, seed=2))

    def test_task_content_sha_matters(self) -> None:
        """Edit a task, get a cache miss."""
        assert _key() != _key(task_content_sha="b" * 64)

    def test_the_key_is_the_TASK_hash_not_the_repo_hash(self) -> None:
        """B8 — the distinction between a cache that works and one that cannot.

        The cache's stated purpose is "re-running a 500-sample task after fixing
        one scorer bug should not cost 500 API calls". Fixing a scorer bug IS a
        commit, so keying on the repo-wide git SHA invalidated every entry on
        every commit -- including a README typo -- defeating the cache with its
        own key. Only the task's own content may move it.
        """
        import inspect

        params = inspect.signature(cache_key).parameters
        assert "task_content_sha" in params
        assert "task_git_sha" not in params

    def test_repeat_index_matters(self) -> None:
        """B7 — self-consistency needs DIFFERENT completions for the same input,
        so repetitions must not collapse onto one cached answer."""
        assert _key() != _key(repeat_index=1)

    def test_sample_input_matters(self) -> None:
        assert _key() != _key(sample=TaskSample(id="s", input="different", target="a"))

    def test_target_does_not_matter(self) -> None:
        """The gold answer never reaches the model, so it cannot change the answer."""
        assert _key() == _key(sample=TaskSample(id="s", input="q", target="different"))

    def test_hardware_does_not_matter(self) -> None:
        """Recorded for provenance, but it does not change a greedy completion."""
        assert _key() == _key(serving=_serving(hardware="2x GB10"))


def _completion() -> ChatCompletion:
    return ChatCompletion(
        content="42",
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
        latency_ms=1.0,
        model="m",
        request_id="r",
        raw={},
    )


class TestNullCache:
    def test_always_misses(self) -> None:
        cache = NullCache()
        cache.put("k", _completion())
        assert cache.get("k") is None


class TestInMemoryCache:
    def test_round_trip(self) -> None:
        cache = InMemoryCache()
        assert cache.get("k") is None
        completion = _completion()
        cache.put("k", completion)
        assert cache.get("k") is completion

    def test_satisfies_the_protocol(self) -> None:
        from ida_harness.cache import CompletionCache

        assert isinstance(InMemoryCache(), CompletionCache)
        assert isinstance(NullCache(), CompletionCache)


class TestCachedCompletion:
    """B4 — the cache stores the exchange, not just the answer."""

    def test_round_trip_preserves_the_messages(self) -> None:
        from ida_core.contracts import ChatMessage
        from ida_harness.cache import CachedCompletion

        messages = [
            ChatMessage(role="system", content="Answer with the number."),
            ChatMessage(role="user", content="What is 2 + 2?"),
        ]
        cache = InMemoryCache()
        cache.put("k", CachedCompletion(messages=messages, completion=_completion()))
        restored = cache.get("k")
        assert restored is not None
        assert restored.messages == messages
        assert restored.completion.content == "42"

    def test_without_messages_a_hit_cannot_reconstruct_its_evidence(self) -> None:
        """Why messages are cached at all: the transcript is the D-3 evidence.

        A cached result whose archived prompt is empty is not citable -- the UI
        links to it and renders nothing above the completion.
        """
        from ida_harness.cache import CachedCompletion

        entry = CachedCompletion(messages=[], completion=_completion())
        assert entry.messages == [], "the type permits it..."
        # ...and the runner is what must never produce it -- pinned in
        # test_runner.py::TestCaching::test_a_hit_archives_a_faithful_transcript.
