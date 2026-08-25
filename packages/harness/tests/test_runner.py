"""Run orchestration guarantees, straight from ida_harness.runner's docstring.

Each guarantee gets a test that would fail if it were quietly dropped:
one record per sample, model failures degrade one sample, serving config is
stamped everywhere, subjective tasks are not scored.
"""

from __future__ import annotations

import httpx
import pytest

from ida_core.artifacts import LocalArtifactStore, eval_log_key, parse_uri, sample_key
from ida_core.contracts import (
    ChatMessage,
    ModelEntry,
    RunStatus,
    SamplingParams,
    TaskSpec,
)
from ida_harness.cache import InMemoryCache, NullCache
from ida_harness.client import OpenAICompatibleClient
from ida_harness.runner import effective_serving_config, run_task, unscorable_reason

RUN_ID = "run_test0000000000000000000"
SECOND_RUN_ID = "run_test0000000000000000002"


def _body(content: str, prompt_tokens: int = 10, completion_tokens: int = 2) -> dict:
    return {
        "id": "chatcmpl-x",
        "model": "mock-echo-1",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _client(entry: ModelEntry, handler) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        entry,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        jitter=lambda _lo, hi: hi,
    )


def _correct_answers(request: httpx.Request) -> httpx.Response:
    """Answer every arithmetic question correctly, with visible working."""
    import json

    body = json.loads(request.read())
    prompt = body["messages"][-1]["content"]
    answer = "4" if "2 + 2" in prompt else "100"
    return httpx.Response(200, json=_body(f"Let me compute.\n{answer}"))


class TestHappyPath:
    def test_one_result_per_sample(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert len(log.results) == len(verifiable_task.samples)
        assert [r.sample_id for r in log.results] == ["a", "b"]

    def test_all_correct_gives_mean_one(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.mean_score == 1.0
        assert all(r.score is not None and r.score.passed for r in log.results)

    def test_wrong_answers_give_mean_zero(self, verifiable_task, model_entry) -> None:
        """The scorer must actually be able to fail, or a passing score means nothing."""
        with _client(model_entry, lambda r: httpx.Response(200, json=_body("999"))) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.mean_score == 0.0

    def test_status_and_timestamps(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.status is RunStatus.SUCCEEDED
        assert log.finished_at >= log.started_at
        assert log.error is None

    def test_token_and_cost_accounting_flows_through(
        self, verifiable_task, model_entry
    ) -> None:
        model_entry.cost.input_usd_per_mtok = 1_000_000.0  # $1 per input token
        model_entry.cost.output_usd_per_mtok = 0.0
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.total_usage.prompt_tokens == 20
        assert log.total_usage.completion_tokens == 4
        assert sum(r.cost_usd for r in log.results) == pytest.approx(20.0)

    def test_system_prompt_is_sent_when_the_task_has_one(
        self, verifiable_task, model_entry
    ) -> None:
        import json

        seen: list[list[dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.read())["messages"])
            return httpx.Response(200, json=_body("4"))

        with _client(model_entry, handler) as client:
            run_task(task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client)
        assert seen[0][0]["role"] == "system"
        assert seen[0][0]["content"] == verifiable_task.system_prompt


class TestServingConfigStamping:
    """D-1: the config must be on the run AND on every single result."""

    def test_stamped_on_every_result(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert all(r.serving_config == log.serving_config for r in log.results)
        assert log.serving_config.model_id == "mock-echo-1"

    def test_sampling_override_lands_in_the_recorded_config(
        self, verifiable_task, model_entry
    ) -> None:
        """The record must show the params actually used, never the default they replaced."""
        override = SamplingParams(temperature=0.9, max_tokens=8, seed=99)
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                sampling_override=override,
            )
        assert log.serving_config.sampling == override
        assert all(r.serving_config.sampling == override for r in log.results)

    def test_override_does_not_mutate_the_registry_entry(self, model_entry) -> None:
        original = model_entry.serving.sampling.model_copy(deep=True)
        effective_serving_config(model_entry, SamplingParams(temperature=1.5))
        assert model_entry.serving.sampling == original

    def test_no_override_copies_rather_than_aliases(self, model_entry) -> None:
        config = effective_serving_config(model_entry, None)
        config.sampling.temperature = 1.9
        assert model_entry.serving.sampling.temperature == 0.0

    def test_git_sha_is_recorded(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                task_git_sha="c" * 40,
            )
        assert log.task_git_sha == "c" * 40


class TestFailureContainment:
    def test_one_failing_sample_does_not_fail_the_run(
        self, verifiable_task, model_entry
    ) -> None:
        model_entry.max_retries = 0
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="unavailable")
            return httpx.Response(200, json=_body("100"))

        with _client(model_entry, handler) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )

        assert log.status is RunStatus.PARTIAL, (
            "one failure out of two is neither a success nor a total failure"
        )
        assert log.error_count == 1
        assert len(log.results) == 2, "the failed sample still produces a record"
        failed, ok = log.results
        assert failed.error is not None and failed.score is None
        assert ok.score is not None and ok.score.passed

    def test_failed_samples_are_excluded_from_the_mean_not_counted_as_zero(
        self, verifiable_task, model_entry
    ) -> None:
        """Counting an errored sample as 0 would defame the model for our outage."""
        model_entry.max_retries = 0
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(500, text="boom")
            return httpx.Response(200, json=_body("100"))

        with _client(model_entry, handler) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.mean_score == 1.0

    def test_permanent_error_also_degrades_only_one_sample(
        self, verifiable_task, model_entry
    ) -> None:
        with _client(model_entry, lambda r: httpx.Response(401, text="bad key")) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert len(log.results) == 2
        assert all(r.error is not None for r in log.results)
        assert log.mean_score is None

    def test_failed_sample_produces_no_transcript(
        self, verifiable_task, model_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, lambda r: httpx.Response(401, text="x")) as client:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
            )
        assert log.transcripts == []
        assert all(r.transcript_uri is None for r in log.results)


class TestSubjectiveTasks:
    def test_are_run_but_not_scored(self, subjective_task, model_entry) -> None:
        handler = lambda r: httpx.Response(200, json=_body("Some feedback."))  # noqa: E731
        with _client(model_entry, handler) as client:
            log = run_task(
                task=subjective_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert len(log.results) == 1
        result = log.results[0]
        assert result.scorable is False
        assert result.score is None, "a null score, never a zero"
        assert result.error is None, "not scoring is not an error"
        assert log.mean_score is None

    def test_transcript_is_still_captured(self, subjective_task, model_entry, tmp_path) -> None:
        """The judge lands later; the data it will grade must be captured now."""
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        handler = lambda r: httpx.Response(200, json=_body("Some feedback."))  # noqa: E731
        with _client(model_entry, handler) as client:
            log = run_task(
                task=subjective_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
            )
        assert log.results[0].transcript_uri is not None
        assert store.get_json(sample_key(RUN_ID, "s1"))["completion"] == "Some feedback."

    def test_never_calls_the_unimplemented_judge(self, subjective_task, model_entry) -> None:
        handler = lambda r: httpx.Response(200, json=_body("feedback"))  # noqa: E731
        with _client(model_entry, handler) as client:
            run_task(task=subjective_task, entry=model_entry, run_id=RUN_ID, client=client)

    def test_unscorable_reason_explains_why(self, subjective_task, verifiable_task) -> None:
        reason = unscorable_reason(subjective_task)
        assert reason is not None and "judge" in reason
        assert unscorable_reason(verifiable_task) is None


class TestArtifactArchival:
    def test_transcripts_and_eval_log_are_written(
        self, verifiable_task, model_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
            )
        for result in log.results:
            assert result.transcript_uri is not None
            _bucket, key = parse_uri(result.transcript_uri)
            assert key == sample_key(RUN_ID, result.sample_id)
            assert store.exists(key)
        assert store.exists(eval_log_key(RUN_ID))

    def test_transcript_contains_the_full_conversation_and_raw_response(
        self, verifiable_task, model_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, _correct_answers) as client:
            run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
            )
        transcript = store.get_json(sample_key(RUN_ID, "a"))
        assert [m["role"] for m in transcript["messages"]] == ["system", "user"]
        assert transcript["completion"].endswith("4")
        assert transcript["raw_response"]["model"] == "mock-echo-1"
        assert transcript["usage"]["prompt_tokens"] == 10

    def test_no_store_means_no_uri_and_no_crash(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=None,
            )
        assert all(r.transcript_uri is None for r in log.results)


class TestCaching:
    """B4 — a cache hit must be honest about being one.

    The previous test asserted only two things: no further HTTP calls, and
    ``mean_score == 1.0``. Both remained true while the hit archived an empty
    transcript, reported the original call's latency as freshly measured, and
    billed tokens that were never purchased. That is why it is expanded here
    rather than merely kept.
    """

    def _run_twice(self, task, entry, tmp_path, cache):
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return _correct_answers(request)

        with _client(entry, handler) as client:
            miss = run_task(
                task=task,
                entry=entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
                completion_cache=cache,
            )
            hit = run_task(
                task=task,
                entry=entry,
                run_id=SECOND_RUN_ID,
                client=client,
                artifact_store=store,
                completion_cache=cache,
            )
        return miss, hit, store, calls

    def test_second_run_hits_the_cache_and_skips_http(
        self, verifiable_task, model_entry, tmp_path
    ) -> None:
        _miss, hit, _store, calls = self._run_twice(
            verifiable_task, model_entry, tmp_path, InMemoryCache()
        )
        assert calls["n"] == 2, "one call per sample on the miss run, none on the hit run"
        assert hit.mean_score == 1.0, "cached completions are still scored"

    def test_the_hit_is_flagged_and_the_miss_is_not(
        self, verifiable_task, model_entry, tmp_path
    ) -> None:
        miss, hit, _store, _calls = self._run_twice(
            verifiable_task, model_entry, tmp_path, InMemoryCache()
        )
        assert all(r.cached is False for r in miss.results)
        assert all(r.cached is True for r in hit.results)

    def test_a_hit_bills_nothing(self, verifiable_task, model_entry, tmp_path) -> None:
        """Cost accounting (AC-2) must not re-charge tokens that were not re-bought."""
        model_entry.cost.input_usd_per_mtok = 3.0
        model_entry.cost.output_usd_per_mtok = 15.0
        miss, hit, _store, _calls = self._run_twice(
            verifiable_task, model_entry, tmp_path, InMemoryCache()
        )
        assert sum(r.cost_usd for r in miss.results) > 0, "the real call did cost money"
        assert sum(r.cost_usd for r in hit.results) == 0.0, "the cached one did not"

    def test_a_hit_reports_no_latency(self, verifiable_task, model_entry, tmp_path) -> None:
        """A wall-clock figure that was never measured is a fabricated measurement."""
        _miss, hit, _store, _calls = self._run_twice(
            verifiable_task, model_entry, tmp_path, InMemoryCache()
        )
        assert all(r.latency_ms == 0.0 for r in hit.results)

    def test_a_hit_still_retains_token_usage(
        self, verifiable_task, model_entry, tmp_path
    ) -> None:
        """Usage is a property of the exchange, not of who paid: keep it."""
        _miss, hit, _store, _calls = self._run_twice(
            verifiable_task, model_entry, tmp_path, InMemoryCache()
        )
        assert all(r.usage.total_tokens > 0 for r in hit.results)

    def test_a_hit_archives_a_faithful_transcript(
        self, verifiable_task, model_entry, tmp_path
    ) -> None:
        """D-3: the transcript is the evidence a score is cited against.

        A cached result whose archived prompt is an empty list is not citable --
        the UI links to it and renders nothing above the completion.
        """
        _miss, hit, store, _calls = self._run_twice(
            verifiable_task, model_entry, tmp_path, InMemoryCache()
        )
        for result in hit.results:
            assert result.transcript_uri is not None
            archived = store.get_json(sample_key(SECOND_RUN_ID, result.sample_id))
            assert archived["messages"], "the cached run archived an empty prompt"
            assert [m["role"] for m in archived["messages"]] == ["system", "user"]
            assert archived["completion"]

    def test_the_cached_transcript_matches_the_original(
        self, verifiable_task, model_entry, tmp_path
    ) -> None:
        _miss, _hit, store, _calls = self._run_twice(
            verifiable_task, model_entry, tmp_path, InMemoryCache()
        )
        original = store.get_json(sample_key(RUN_ID, "a"))
        cached = store.get_json(sample_key(SECOND_RUN_ID, "a"))
        assert cached["messages"] == original["messages"]
        assert cached["completion"] == original["completion"]

    def test_the_default_cache_never_hits(self, verifiable_task, model_entry, tmp_path) -> None:
        """NullCache is the skeleton's default, so every run exercises real HTTP."""
        _miss, hit, _store, calls = self._run_twice(
            verifiable_task, model_entry, tmp_path, NullCache()
        )
        assert calls["n"] == 4
        assert all(r.cached is False for r in hit.results)


class TestClientLifecycle:
    def test_a_passed_in_client_is_not_closed(self, verifiable_task, model_entry) -> None:
        client = _client(model_entry, _correct_answers)
        run_task(task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client)
        assert client._client.is_closed is False, "the caller still owns this client"
        # Prove it is genuinely still usable, not merely un-closed.
        assert client.complete(
            [ChatMessage(role="user", content="What is 2 + 2?")], SamplingParams()
        ).content.endswith("4")
        client.close()

    def test_a_factory_built_client_is_closed(self, verifiable_task, model_entry) -> None:
        built: list[OpenAICompatibleClient] = []

        def factory() -> OpenAICompatibleClient:
            client = _client(model_entry, _correct_answers)
            built.append(client)
            return client

        run_task(
            task=verifiable_task,
            entry=model_entry,
            run_id=RUN_ID,
            client_factory=factory,
        )
        assert built[0]._client.is_closed is True


class TestHonestRunStatus:
    """B5 — a run must not claim to have measured something it did not.

    Reproduced before the fix: with the endpoint unreachable, all 4 samples
    errored and the run was recorded ``status: succeeded, error: None``, because
    ``run_task`` hardcoded ``SUCCEEDED``. The per-sample records were correct;
    the rollup lied. That rollup is what the UI and the recommendation engine
    read, so the lie propagated (see B1).
    """

    def _all_fail(self, entry: ModelEntry):
        entry.max_retries = 0

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        return handler

    def test_every_sample_erroring_is_failed_not_succeeded(
        self, verifiable_task, model_entry
    ) -> None:
        with _client(model_entry, self._all_fail(model_entry)) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.status is RunStatus.FAILED
        assert log.error_count == len(verifiable_task.samples)
        assert log.scored_count == 0
        assert log.mean_score is None

    def test_a_failed_run_says_why(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, self._all_fail(model_entry)) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.error is not None
        assert "2/2 samples failed" in log.error
        assert "TransientModelError" in log.error

    def test_identical_errors_are_summarised_once(self, verifiable_task, model_entry) -> None:
        """500 samples against one dead endpoint is one problem, not 500."""
        with _client(model_entry, self._all_fail(model_entry)) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.error.count("TransientModelError") == 1

    def test_no_errors_is_succeeded(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.status is RunStatus.SUCCEEDED
        assert log.error_count == 0
        assert log.error is None

    def test_a_subjective_run_still_succeeds_with_nothing_scored(
        self, subjective_task, model_entry
    ) -> None:
        """The distinction B1 turned on: not-yet-scorable is NOT a failure."""
        handler = lambda r: httpx.Response(200, json=_body("feedback"))  # noqa: E731
        with _client(model_entry, handler) as client:
            log = run_task(
                task=subjective_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert log.status is RunStatus.SUCCEEDED
        assert log.error_count == 0
        assert log.scored_count == 0

    def test_errored_and_unscorable_runs_are_distinguishable(
        self, verifiable_task, subjective_task, model_entry
    ) -> None:
        """Both have mean_score None. Only one of them measured nothing.

        This is the exact pair the UI confused. If this test ever fails, the
        frontend's notice logic has lost the signal it needs.
        """
        handler = lambda r: httpx.Response(200, json=_body("feedback"))  # noqa: E731
        with _client(model_entry, handler) as client:
            subjective = run_task(
                task=subjective_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        with _client(model_entry, self._all_fail(model_entry)) as client:
            broken = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )

        assert subjective.mean_score is broken.mean_score is None
        assert (subjective.status, broken.status) == (RunStatus.SUCCEEDED, RunStatus.FAILED)
        assert (subjective.error_count, broken.error_count) == (0, 2)
        assert all(r.scorable is False and r.error is None for r in subjective.results)
        assert all(r.scorable is True and r.error is not None for r in broken.results)


class TestTerminalStatusRule:
    """The succeeded/partial/failed decision lives in exactly one function."""

    @pytest.mark.parametrize(
        "samples,errors,expected",
        [
            (4, 0, RunStatus.SUCCEEDED),
            (4, 1, RunStatus.PARTIAL),
            (4, 3, RunStatus.PARTIAL),
            (4, 4, RunStatus.FAILED),
            (1, 0, RunStatus.SUCCEEDED),
            (1, 1, RunStatus.FAILED),
            (0, 0, RunStatus.FAILED),
        ],
    )
    def test_rule(self, samples: int, errors: int, expected: RunStatus) -> None:
        from ida_core.contracts import terminal_status

        assert terminal_status(sample_count=samples, error_count=errors) is expected


class TestScorerFailureContainment:
    """A8 — a malformed task sample must not discard its siblings' paid completions.

    Reproduced before the fix: a `numeric_match` task with a non-numeric target
    passed the JSON Schema, pydantic and `make lint-tasks`, then raised out of
    `run_task` on the first sample -- aborting the loop and throwing away every
    already-completed sibling's completion. That also punctured the documented
    guarantee that every sample produces exactly one record.
    """

    def _task_with_one_bad_target(self) -> TaskSpec:
        return TaskSpec.model_validate(
            {
                "version": 1,
                "id": "test/bad-target",
                "title": "Bad target",
                "kind": "verifiable",
                "scorer": {"kind": "numeric_match"},
                "samples": [
                    {"id": "a", "input": "What is 2 + 2?", "target": "four"},
                    {"id": "b", "input": "What is 10 * 10?", "target": "100"},
                ],
            }
        )

    def test_one_unscorable_sample_does_not_abort_the_run(self, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=self._task_with_one_bad_target(),
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
            )
        assert len(log.results) == 2, "every sample still produces exactly one record"
        assert log.status is RunStatus.PARTIAL

    def test_the_sibling_result_survives_and_is_scored(self, model_entry) -> None:
        """The point: its completion was paid for and must not be thrown away."""
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=self._task_with_one_bad_target(),
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
            )
        good = next(r for r in log.results if r.sample_id == "b")
        assert good.error is None
        assert good.score is not None and good.score.passed is True

    def test_the_bad_sample_records_a_readable_reason(self, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=self._task_with_one_bad_target(),
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
            )
        bad = next(r for r in log.results if r.sample_id == "a")
        assert bad.score is None
        assert "contains no number" in bad.error


class TestArchivalFailureContainment:
    """A5 — object storage blinking must not discard completions we already bought."""

    class _BrokenStore:
        """Refuses every write. A real failure mode: MinIO down mid-run."""

        bucket = "ida-artifacts"

        def put_json(self, key: str, payload: dict) -> str:
            raise ConnectionError("minio is unreachable")

        def get_json(self, key: str) -> dict:
            raise KeyError(key)

        def exists(self, key: str) -> bool:
            return False

        def ensure_bucket(self) -> None:
            return None

    def test_results_survive_an_archival_outage(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=self._BrokenStore(),
            )
        assert len(log.results) == 2
        assert log.status is RunStatus.SUCCEEDED, "the model answered; storage failed"
        assert log.mean_score == 1.0, "the scores are real and must be kept"

    def test_the_missing_evidence_is_recorded_not_hidden(
        self, verifiable_task, model_entry
    ) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=self._BrokenStore(),
            )
        for result in log.results:
            assert result.transcript_uri is None
            assert "ConnectionError" in result.archive_error


class TestProvenanceFields:
    """B7/B8 — the contract slots that keep the next stories additive."""

    def test_task_content_sha_lands_on_every_result(self, model_entry) -> None:
        from ida_core.contracts import content_sha_of

        document = {
            "version": 1,
            "id": "test/sha",
            "title": "Sha",
            "kind": "verifiable",
            "scorer": {"kind": "numeric_match"},
            "samples": [{"id": "a", "input": "What is 2 + 2?", "target": "4"}],
        }
        task = TaskSpec.from_document(document)
        with _client(model_entry, _correct_answers) as client:
            log = run_task(task=task, entry=model_entry, run_id=RUN_ID, client=client)
        assert log.task_content_sha == content_sha_of(document)
        assert all(r.task_content_sha == task.content_sha for r in log.results)

    def test_repeat_index_defaults_to_zero(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task, entry=model_entry, run_id=RUN_ID, client=client
            )
        assert all(r.repeat_index == 0 for r in log.results)

    def test_sweep_id_is_carried_onto_the_eval_log(self, verifiable_task, model_entry) -> None:
        with _client(model_entry, _correct_answers) as client:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                sweep_id="swp_abc",
            )
        assert log.sweep_id == "swp_abc"
