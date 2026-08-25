"""The judge as the runner sees it: the flip from not-yet-scorable to scored.

Three obligations are asserted here that :mod:`test_judge` cannot:

1. **The flip is real and it is opt-in.**  The same subjective task, the same
   completions, run with and without a judge -- scored one way, honestly blank
   the other.  Without a judge nothing changes at all, which is what makes
   shipping this safe for a deployment that has not chosen to spend money.
2. **Verifiable tasks are provably untouched.**  A judge passed alongside a
   verifiable task is never called, and no judge field lands on the record.
3. **Judge spend is attributed separately.**  ``usage``/``cost_usd`` stay the
   candidate model's; the judge's land in ``judge_usage``/``judge_cost_usd``.
   The two models are priced differently in the fixtures precisely so that a
   test could not pass by accident if the two were folded together.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ida_core.artifacts import LocalArtifactStore, judge_key, parse_uri, sample_key
from ida_core.contracts import RunStatus
from ida_harness.client import OpenAICompatibleClient
from ida_harness.judge import LLMJudge
from ida_harness.runner import run_task, unscorable_reason

RUN_ID = "run_rjudge00000000000000000"


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


def _client(entry, handler) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        entry,
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        jitter=lambda _lo, hi: hi,
    )


def _candidate(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_body("Your thesis needs sharpening."))


def _judging(*, score: float = 1.0, calls: dict | None = None):
    def handler(_request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls["n"] = calls.get("n", 0) + 1
        payload = json.dumps({"score": score, "rationale": "anchored at the top level"})
        return httpx.Response(200, json=_body(payload, prompt_tokens=100, completion_tokens=20))

    return handler


def _judge(judge_entry, handler) -> LLMJudge:
    return LLMJudge(entry=judge_entry, client=_client(judge_entry, handler), owns_client=True)


class TestTheFlip:
    """Same task, same answers -- the judge is the only difference."""

    def test_without_a_judge_the_run_is_honestly_blank(self, anchored_task, model_entry) -> None:
        with _client(model_entry, _candidate) as client:
            log = run_task(task=anchored_task, entry=model_entry, run_id=RUN_ID, client=client)
        assert [r.scorable for r in log.results] == [False, False]
        assert all(r.score is None and r.error is None for r in log.results)
        assert log.mean_score is None
        assert log.status is RunStatus.SUCCEEDED, "not scoring is not failing"

    def test_with_a_judge_the_same_run_is_scored(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        with _client(model_entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        assert [r.scorable for r in log.results] == [True, True]
        assert log.mean_score == pytest.approx(1.0)
        assert log.scored_count == 2
        assert log.error_count == 0

    def test_the_per_criterion_breakdown_reaches_the_record(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        with _client(model_entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        criteria = log.results[0].score.criteria
        assert [c.name for c in criteria] == ["specificity", "restraint"]
        assert all(c.explanation for c in criteria)

    def test_passed_stays_none_on_a_judged_result(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        """A rubric-weighted score is graded by construction; a pass mark here
        would be a cutoff nobody chose, applied to every comparison downstream."""
        with _client(model_entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        assert log.results[0].score.passed is None

    def test_the_reason_shown_to_a_user_changes_with_the_configuration(
        self, anchored_task, verifiable_task
    ) -> None:
        unconfigured = unscorable_reason(anchored_task)
        assert unconfigured is not None and "no judge model is configured" in unconfigured
        assert "retroactively" in unconfigured, "tell them the work is not lost"
        assert unscorable_reason(anchored_task, judge_configured=True) is None
        assert unscorable_reason(verifiable_task) is None


class TestVerifiableTasksAreUntouched:
    """The regression guard for the path that already worked."""

    def test_a_judge_passed_with_a_verifiable_task_is_never_called(
        self, verifiable_task, model_entry, judge_entry
    ) -> None:
        """Paying a model to re-decide an answer we can check with `==` would be
        slower, more expensive AND less accurate."""
        calls: dict = {}

        def answers(request: httpx.Request) -> httpx.Response:
            prompt = json.loads(request.read())["messages"][-1]["content"]
            return httpx.Response(200, json=_body("4" if "2 + 2" in prompt else "100"))

        with (
            _client(model_entry, answers) as client,
            _judge(judge_entry, _judging(calls=calls)) as judge,
        ):
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        assert calls.get("n", 0) == 0
        assert log.mean_score == 1.0

    def test_no_judge_field_lands_on_a_programmatically_scored_record(
        self, verifiable_task, model_entry, judge_entry
    ) -> None:
        def answers(request: httpx.Request) -> httpx.Response:
            prompt = json.loads(request.read())["messages"][-1]["content"]
            return httpx.Response(200, json=_body("4" if "2 + 2" in prompt else "100"))

        with _client(model_entry, answers) as client, _judge(judge_entry, _judging()) as judge:
            log = run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        for record in log.results:
            assert record.judge_serving_config is None
            assert record.judge_usage.total_tokens == 0
            assert record.judge_cost_usd == 0.0
            assert record.judge_transcript_uri is None
        assert log.total_judge_cost_usd == 0.0


class TestJudgeSpendAttribution:
    """Two models answered; two bills.  Adding them is the caller's choice."""

    def _run(self, task, entry, judge_entry):
        with _client(entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            return run_task(task=task, entry=entry, run_id=RUN_ID, client=client, judge=judge)

    def test_candidate_usage_is_not_inflated_by_the_judge(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        log = self._run(anchored_task, model_entry, judge_entry)
        record = log.results[0]
        assert record.usage.prompt_tokens == 10, "the candidate call, and only it"
        assert record.usage.completion_tokens == 2

    def test_judge_usage_is_recorded_and_is_the_judge_s(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        log = self._run(anchored_task, model_entry, judge_entry)
        record = log.results[0]
        # two criteria x (100 prompt + 20 completion)
        assert record.judge_usage.prompt_tokens == 200
        assert record.judge_usage.completion_tokens == 40

    def test_each_side_is_billed_at_its_own_rates(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        """Both fixtures are priced, and neither rate is a multiple of the
        other's, so each number below identifies exactly ONE arithmetic.

        This assertion used to read ``record.cost_usd == 0.0``, which was
        trivially true because the candidate fixture was unpriced -- a
        regression billing the candidate at the judge's rates, or summing the
        two, would have sailed through it. The three ``!=`` lines are the ones
        that would have caught that.
        """
        log = self._run(anchored_task, model_entry, judge_entry)
        record = log.results[0]

        candidate = (10 * 0.5 + 2 * 4.0) / 1_000_000  # 10 prompt + 2 completion
        judge = (200 * 1.0 + 40 * 2.0) / 1_000_000  # 2 criteria x (100 + 20)
        assert record.cost_usd == pytest.approx(candidate)
        assert record.judge_cost_usd == pytest.approx(judge)

        # The three ways this could go wrong, each a visibly different number.
        assert record.cost_usd != pytest.approx((10 * 1.0 + 2 * 2.0) / 1_000_000), (
            "candidate billed at the judge's rates"
        )
        assert record.judge_cost_usd != pytest.approx((200 * 0.5 + 40 * 4.0) / 1_000_000), (
            "judge billed at the candidate's rates"
        )
        assert record.cost_usd != pytest.approx(candidate + judge), "the two bills were summed"

    def test_the_log_reports_both_totals_separately(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        log = self._run(anchored_task, model_entry, judge_entry)
        assert log.total_usage.prompt_tokens == 20, "two samples, candidate only"
        assert log.total_judge_usage.prompt_tokens == 400, "two samples x two criteria"
        assert log.total_judge_cost_usd > 0.0

    def test_the_judge_serving_config_is_stamped_by_value(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        """D-13 applied to the grade: swapping the judge moves the score as
        surely as swapping the model under test."""
        log = self._run(anchored_task, model_entry, judge_entry)
        record = log.results[0]
        assert record.serving_config.model_id == "mock-echo-1"
        assert record.judge_serving_config.model_id == "mock-judge-1"
        assert record.judge_serving_config.sampling.seed == 11


class TestJudgeFailureDegradesOneSample:
    def test_a_failing_judge_does_not_take_the_run_down(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        calls = {"n": 0}

        def flaky_judge(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            # Sample 1 needs calls 1-2; sample 2 starts at call 3 and fails.
            if calls["n"] >= 3:
                return httpx.Response(200, json=_body("unparseable"))
            payload = json.dumps({"score": 1.0, "rationale": "fine"})
            return httpx.Response(200, json=_body(payload))

        with _client(model_entry, _candidate) as client, _judge(judge_entry, flaky_judge) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        assert log.status is RunStatus.PARTIAL
        assert log.results[0].score is not None
        assert log.results[1].score is None
        assert log.results[1].error is not None

    def test_the_failed_sample_is_excluded_from_the_mean_not_counted_as_zero(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        """Our judge outage is not the model's wrong answer."""
        calls = {"n": 0}

        def flaky_judge(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] >= 3:
                return httpx.Response(503)
            payload = json.dumps({"score": 1.0, "rationale": "fine"})
            return httpx.Response(200, json=_body(payload))

        with _client(model_entry, _candidate) as client, _judge(judge_entry, flaky_judge) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        assert log.mean_score == pytest.approx(1.0), "not 0.5"
        assert log.error_count == 1

    def test_the_spend_on_a_failed_grading_is_still_recorded(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        handler = lambda _r: httpx.Response(200, json=_body("garbage"))  # noqa: E731
        with _client(model_entry, _candidate) as client, _judge(judge_entry, handler) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        assert log.results[0].score is None
        assert log.results[0].judge_usage.total_tokens > 0
        assert log.results[0].judge_cost_usd > 0.0

    def test_a_run_whose_judge_is_entirely_down_is_failed_not_succeeded(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        handler = lambda _r: httpx.Response(500)  # noqa: E731
        with _client(model_entry, _candidate) as client, _judge(judge_entry, handler) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
            )
        assert log.status is RunStatus.FAILED
        assert log.mean_score is None


class TestJudgeTranscriptArchival:
    def test_the_judge_transcript_is_written_to_its_own_prefix(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
                artifact_store=store,
            )
        record = log.results[0]
        assert record.judge_transcript_uri is not None
        _bucket, key = parse_uri(record.judge_transcript_uri)
        assert key == judge_key(RUN_ID, "s1")
        assert store.exists(key)

    def test_the_sample_transcript_prefix_is_unchanged(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """Additive means additive: everything already written stays where it
        was, and 'one transcript per sample' stays true of transcripts/."""
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
                artifact_store=store,
            )
        assert store.exists(sample_key(RUN_ID, "s1"))
        assert sample_key(RUN_ID, "s1") != judge_key(RUN_ID, "s1")

    def test_the_archived_judgment_carries_the_criteria_and_the_raw_replies(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
                artifact_store=store,
            )
        blob = store.get_json(judge_key(RUN_ID, "s1"))
        assert [j["criterion"] for j in blob["judgments"]] == ["specificity", "restraint"]
        assert blob["graded_completion"] == "Your thesis needs sharpening."
        assert blob["judge_model_key"] == "mock-judge"

    def test_a_storage_outage_costs_the_pointer_never_the_score(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """A5 applied to the grade: the judge calls are already paid for."""

        class OnlyJudgeWritesFail(LocalArtifactStore):
            def put_json(self, key: str, payload: dict) -> str:
                if "/judge/" in key:
                    raise OSError("minio said no")
                return super().put_json(key, payload)

        store = OnlyJudgeWritesFail(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
                artifact_store=store,
            )
        record = log.results[0]
        assert record.score is not None, "the grade survives"
        assert record.judge_transcript_uri is None
        assert "judge: OSError" in record.archive_error

    def test_two_archival_failures_are_both_reported(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """The second failure must not erase the first -- same class of mistake
        as reporting a partly-failed run as succeeded."""

        class NothingWrites(LocalArtifactStore):
            def put_json(self, key: str, payload: dict) -> str:
                if "eval-log" in key:
                    return super().put_json(key, payload)
                raise OSError(f"refused {key}")

        store = NothingWrites(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, _candidate) as client, _judge(judge_entry, _judging()) as judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
                artifact_store=store,
            )
        archive_error = log.results[0].archive_error
        assert "transcripts/" in archive_error
        assert "judge:" in archive_error


class TestEndToEndAgainstTheMockService:
    """The real mock-model service answers the real judge protocol.

    Not a stub replying to a fixture: the code that answers here is the code
    that answers in docker-compose. If the judge prompt's shape drifts, the mock
    stops recognising it and this fails -- which is the point of running the
    service rather than a canned handler.
    """

    def _entries(self, model_entry, judge_entry):
        from ida_mock_model.testing import make_transport

        transport = make_transport()
        candidate = OpenAICompatibleClient(model_entry, transport=transport)
        judge_client = OpenAICompatibleClient(judge_entry, transport=transport)
        return candidate, LLMJudge(entry=judge_entry, client=judge_client, owns_client=True)

    def test_a_subjective_run_flips_to_scored(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        candidate, judge = self._entries(model_entry, judge_entry)
        with candidate, judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=candidate,
                judge=judge,
                artifact_store=store,
            )
        assert log.status is RunStatus.SUCCEEDED
        assert log.mean_score is not None
        assert 0.0 <= log.mean_score <= 1.0
        assert all(r.scorable and r.score is not None for r in log.results)

    def test_the_mock_judge_is_deterministic(self, anchored_task, model_entry, judge_entry) -> None:
        """Two runs, same numbers -- otherwise this test suite could not tell a
        judge regression from mock noise."""
        scores = []
        for _ in range(2):
            candidate, judge = self._entries(model_entry, judge_entry)
            with candidate, judge:
                log = run_task(
                    task=anchored_task,
                    entry=model_entry,
                    run_id=RUN_ID,
                    client=candidate,
                    judge=judge,
                )
            scores.append(log.mean_score)
        assert scores[0] == scores[1]

    def test_a_misbehaving_judge_service_degrades_honestly(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        """MOCK_JUDGE_MODE=malformed: a real service returning real prose with a
        real number in it. Nothing is scraped out of it."""
        from ida_mock_model.app import create_app
        from ida_mock_model.testing import InProcessTransport

        app = create_app()
        app.state.mock.responder.judge_mode = "malformed"
        transport = InProcessTransport(app)
        candidate = OpenAICompatibleClient(model_entry, transport=transport)
        judge = LLMJudge(
            entry=judge_entry,
            client=OpenAICompatibleClient(judge_entry, transport=transport),
            owns_client=True,
        )
        with candidate, judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=candidate,
                judge=judge,
            )
        assert log.status is RunStatus.FAILED
        assert all(r.score is None for r in log.results)
        assert log.mean_score is None

    def test_an_out_of_range_judge_service_is_refused_not_clamped(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        from ida_mock_model.app import create_app
        from ida_mock_model.testing import InProcessTransport

        app = create_app()
        app.state.mock.responder.judge_mode = "out_of_range"
        transport = InProcessTransport(app)
        candidate = OpenAICompatibleClient(model_entry, transport=transport)
        judge = LLMJudge(
            entry=judge_entry,
            client=OpenAICompatibleClient(judge_entry, transport=transport),
            owns_client=True,
        )
        with candidate, judge:
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=candidate,
                judge=judge,
            )
        assert all(r.score is None for r in log.results)
        assert "outside the rubric's scale" in log.results[0].error


class TestCachingDoesNotCacheGrades:
    """The completion cache caches ANSWERS, not verdicts.

    A re-run that hits the cache costs nothing in candidate tokens and still
    pays the judge in full. That is the correct behaviour -- a grade is a
    function of the judge as well as the completion, and serving a stale grade
    after the judge changed would be exactly the silent incomparability
    `judge_serving_config` exists to prevent -- but it is a real operational
    surprise, so it is pinned rather than left to be discovered on a bill.
    """

    def _run_twice(self, task, entry, judge_entry):
        from ida_harness.cache import InMemoryCache

        cache = InMemoryCache()
        candidate_calls = {"n": 0}
        judge_calls: dict = {}

        def candidate(request: httpx.Request) -> httpx.Response:
            candidate_calls["n"] += 1
            return _candidate(request)

        with (
            _client(entry, candidate) as client,
            _judge(judge_entry, _judging(calls=judge_calls)) as judge,
        ):
            first = run_task(
                task=task,
                entry=entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
                completion_cache=cache,
            )
            second = run_task(
                task=task,
                entry=entry,
                run_id="run_rjudge00000000000000002",
                client=client,
                judge=judge,
                completion_cache=cache,
            )
        return first, second, candidate_calls, judge_calls

    def test_the_second_run_skips_the_model_but_not_the_judge(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        _first, second, candidate_calls, judge_calls = self._run_twice(
            anchored_task, model_entry, judge_entry
        )
        assert candidate_calls["n"] == 2, "two samples, answered once and then cached"
        assert judge_calls["n"] == 8, "2 runs x 2 samples x 2 criteria -- judged every time"
        assert all(r.cached for r in second.results)

    def test_a_cached_run_still_reports_its_judge_spend(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        """`cost_usd == 0` on a hit is true of the CANDIDATE only. A run whose
        total cost read as zero while the judge was billed would be a lie in the
        one direction that matters."""
        _first, second, _c, _j = self._run_twice(anchored_task, model_entry, judge_entry)
        assert all(r.cost_usd == 0.0 for r in second.results)
        assert second.total_judge_cost_usd > 0.0

    def test_the_cached_run_is_scored_identically(
        self, anchored_task, model_entry, judge_entry
    ) -> None:
        first, second, _c, _j = self._run_twice(anchored_task, model_entry, judge_entry)
        assert first.mean_score == second.mean_score
