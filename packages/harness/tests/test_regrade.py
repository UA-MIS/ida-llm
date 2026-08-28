"""Retroactive grading: the promise that an ungraded subjective run is not lost.

``tasks/SCHEMA.md`` and the runner both tell an author that a subjective run
without a judge is "loaded, validated, archived, gradable later".  This suite is
what makes that a fact rather than a hope -- and, just as important, pins the
three things a regrade must REFUSE to do:

* re-run the model under test (it grades the archived completion, or nothing),
* overwrite a score that already exists,
* grade an old completion against an edited rubric.

The last one is the subtle one.  Nothing crashes if you do it; you just get a
number that is comparable to nothing, including to the run's own siblings.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ida_core.artifacts import LocalArtifactStore, eval_log_key, judge_key
from ida_core.contracts import RunStatus, TaskSpec
from ida_harness.client import OpenAICompatibleClient
from ida_harness.judge import LLMJudge
from ida_harness.regrade import is_judge_failure, load_eval_log, regrade_run
from ida_harness.runner import run_task

RUN_ID = "run_regrade0000000000000000"


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


def _judge(entry, handler) -> LLMJudge:
    return LLMJudge(entry=entry, client=_client(entry, handler), owns_client=True)


def _judging(score: float = 1.0, *, calls: dict | None = None):
    def handler(_request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls["n"] = calls.get("n", 0) + 1
        payload = json.dumps({"score": score, "rationale": "graded after the fact"})
        return httpx.Response(200, json=_body(payload, prompt_tokens=100, completion_tokens=20))

    return handler


@pytest.fixture
def archived_run(anchored_task, model_entry, tmp_path):
    """A finished, UNGRADED subjective run, exactly as tonight's platform makes one."""
    store = LocalArtifactStore(tmp_path)
    store.ensure_bucket()
    handler = lambda _r: httpx.Response(  # noqa: E731
        200, json=_body("Your thesis needs sharpening.")
    )
    with _client(model_entry, handler) as client:
        log = run_task(
            task=anchored_task,
            entry=model_entry,
            run_id=RUN_ID,
            client=client,
            artifact_store=store,
        )
    assert all(r.score is None and not r.scorable for r in log.results), "precondition"
    return store, log


class TestTheRegradeFlips:
    def test_an_ungraded_run_becomes_a_graded_one(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert report.graded == ["s1", "s2"]
        assert report.failed == []
        assert report.mean_score == pytest.approx(1.0)

    def test_the_change_is_written_back_to_the_archived_eval_log(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """A report nobody persisted is a report nobody can cite."""
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        reloaded = load_eval_log(store, RUN_ID)
        assert reloaded.mean_score == pytest.approx(1.0)
        assert all(r.scorable and r.score is not None for r in reloaded.results)

    def test_the_model_under_test_is_never_called_again(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """Grading a fresh answer would produce a grade of a different run that
        happens to share a run id."""
        store, log = archived_run
        original = [r.usage.model_dump() for r in log.results]
        with _judge(judge_entry, _judging()) as judge:
            regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        reloaded = load_eval_log(store, RUN_ID)
        assert [r.usage.model_dump() for r in reloaded.results] == original

    def test_it_grades_the_completion_that_was_actually_archived(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        blob = store.get_json(judge_key(RUN_ID, "s1"))
        assert blob["graded_completion"] == "Your thesis needs sharpening."

    def test_judge_evidence_and_spend_land_on_the_records(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        record = report.eval_log.results[0]
        assert record.judge_serving_config.model_id == "mock-judge-1"
        assert record.judge_usage.prompt_tokens == 200
        assert record.judge_cost_usd > 0.0
        assert record.judge_transcript_uri is not None
        assert report.judge_cost_usd == pytest.approx(
            sum(r.judge_cost_usd for r in report.eval_log.results)
        )

    def test_a_catalog_can_be_given_instead_of_a_task(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """How the CLI resolves the task: by id, out of the loaded catalog."""
        from ida_harness.tasks import TaskCatalog

        store, _log = archived_run
        catalog = TaskCatalog({anchored_task.id: anchored_task}, {anchored_task.id: None})
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, catalog=catalog)
        assert report.graded == ["s1", "s2"]

    def test_neither_a_task_nor_a_catalog_is_a_programming_error(
        self, archived_run, judge_entry
    ) -> None:
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge, pytest.raises(ValueError, match="task="):
            regrade_run(run_id=RUN_ID, store=store, judge=judge)


class TestTheAttemptCounter:
    """``judge_attempts`` is the only thing that terminates a retry loop.

    The *judge failed* class is retryable by design, so an unbounded retrier is a
    money pump against a judge that stays down. Nothing else in the schema could
    count: ``judge_transcript_uri`` and ``judge_prompt_tokens`` say only *that* an
    attempt happened, and ``judge_cost_usd`` is overwritten with the LAST
    attempt's spend on every retry.
    """

    def test_a_successful_regrade_counts_its_attempt(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, log = archived_run
        assert all(r.judge_attempts == 0 for r in log.results), "precondition: never judged"

        with _judge(judge_entry, _judging()) as judge:
            regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)

        assert [r.judge_attempts for r in load_eval_log(store, RUN_ID).results] == [1, 1]

    def test_a_failed_regrade_counts_its_attempt_too(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """Counting only successes would leave the retry loop unbounded.

        A judge that is down produces no grade -- and that is exactly the state
        the bound has to terminate, so it is exactly the state that must count.
        """
        store, _log = archived_run
        garbage = lambda _r: httpx.Response(200, json=_body("not json"))  # noqa: E731

        with _judge(judge_entry, garbage) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)

        assert report.graded == []
        assert len(report.failed) == 2
        reloaded = load_eval_log(store, RUN_ID)
        assert [r.judge_attempts for r in reloaded.results] == [1, 1]
        assert all(is_judge_failure(r) for r in reloaded.results), "still retryable"

    def test_attempts_accumulate_across_repeated_regrades(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """Three nightly firings against a broken judge read as three, not one."""
        store, _log = archived_run
        garbage = lambda _r: httpx.Response(200, json=_body("not json"))  # noqa: E731

        for _ in range(3):
            with _judge(judge_entry, garbage) as judge:
                regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)

        assert [r.judge_attempts for r in load_eval_log(store, RUN_ID).results] == [3, 3]

    def test_a_dry_run_does_not_count_an_attempt(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """A dry run changes nothing about the records it hands back.

        ⚠ It DOES call the judge and IS billed, so repeated dry runs spend money
        without ever moving toward the bound. ``--dry-run`` answers "what would
        this change", not "what would this cost".
        """
        store, _log = archived_run
        calls: dict = {}

        with _judge(judge_entry, _judging(calls=calls)) as judge:
            report = regrade_run(
                run_id=RUN_ID, store=store, judge=judge, task=anchored_task, dry_run=True
            )

        assert calls["n"] > 0, "the judge was called and billed"
        assert report.judge_cost_usd > 0
        assert [r.judge_attempts for r in load_eval_log(store, RUN_ID).results] == [0, 0]


class TestOnlyResultIds:
    """The per-RESULT bound has to survive being handed to a per-RUN grader.

    ``regrade_run`` grades a whole run from one eval log, but a caller bounds
    retries per sample: within one run some samples are freshly nominated and
    others have exhausted their attempts. A bare per-run call would silently
    re-grade the exhausted ones -- the per-run call widening the per-result bound
    back open and re-billing exactly the samples the bound exists to protect.
    """

    def test_it_grades_only_the_nominated_results(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, log = archived_run
        wanted = log.results[0].id

        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(
                run_id=RUN_ID,
                store=store,
                judge=judge,
                task=anchored_task,
                only_result_ids={wanted},
            )

        assert report.graded == ["s1"]
        reloaded = {r.id: r for r in load_eval_log(store, RUN_ID).results}
        assert reloaded[wanted].score is not None
        other = next(r for rid, r in reloaded.items() if rid != wanted)
        assert other.score is None, "a result nobody nominated must be untouched"
        assert other.judge_attempts == 0, "and must not be charged an attempt"

    def test_it_never_calls_the_judge_for_an_unnominated_result(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """The bound is about MONEY, so the assertion has to be about calls.

        The rubric has two criteria and the judge makes one call per criterion,
        so grading one of two samples is two calls, not four.
        """
        store, log = archived_run
        calls: dict = {}

        with _judge(judge_entry, _judging(calls=calls)) as judge:
            regrade_run(
                run_id=RUN_ID,
                store=store,
                judge=judge,
                task=anchored_task,
                only_result_ids={log.results[0].id},
            )

        assert calls["n"] == len(anchored_task.rubric.criteria)

    def test_unnominated_results_are_still_accounted_for_as_skipped(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """Every sample in the run lands in a bucket, or the report cannot be reconciled."""
        store, log = archived_run

        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(
                run_id=RUN_ID,
                store=store,
                judge=judge,
                task=anchored_task,
                only_result_ids={log.results[0].id},
            )

        assert len(report.graded) + len(report.failed) + len(report.skipped) == len(log.results)
        assert any("not nominated" in reason for _sid, reason in report.skipped)

    def test_an_empty_nomination_set_grades_nothing(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """``set()`` means "none", not "all" -- the difference is a whole run's spend."""
        store, _log = archived_run
        calls: dict = {}

        with _judge(judge_entry, _judging(calls=calls)) as judge:
            report = regrade_run(
                run_id=RUN_ID,
                store=store,
                judge=judge,
                task=anchored_task,
                only_result_ids=set(),
            )

        assert report.graded == []
        assert calls == {}, "no judge call, therefore no spend"

    def test_none_still_means_the_whole_run(self, archived_run, anchored_task, judge_entry) -> None:
        """The CLI passes nothing and must keep grading everything."""
        store, _log = archived_run

        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)

        assert report.graded == ["s1", "s2"]


class TestWhatARegradeRefusesToDo:
    def test_an_already_scored_sample_is_left_alone(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """Running twice must not quietly regrade under a different judge and
        overwrite the first verdict."""
        store, _log = archived_run
        with _judge(judge_entry, _judging(1.0)) as judge:
            regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)

        calls: dict = {}
        with _judge(judge_entry, _judging(0.0, calls=calls)) as judge:
            second = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)

        assert second.graded == []
        assert calls.get("n", 0) == 0, "no judge call, so no spend"
        assert all("already scored" in reason for _s, reason in second.skipped)
        assert load_eval_log(store, RUN_ID).mean_score == pytest.approx(1.0)

    def test_an_errored_sample_has_no_completion_to_grade(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with _client(model_entry, lambda _r: httpx.Response(500)) as client:
            run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
            )
        calls: dict = {}
        with _judge(judge_entry, _judging(calls=calls)) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert report.graded == []
        assert calls.get("n", 0) == 0
        # The reason is the MISSING TRANSCRIPT, not the `error` flag: a dead
        # candidate call leaves nothing to grade, which is a fact about the
        # artifacts rather than about a field. See `is_judge_failure`.
        assert all("no archived transcript" in reason for _s, reason in report.skipped)

    def test_a_verifiable_run_is_not_a_regrade_candidate(
        self, verifiable_task, model_entry, judge_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()

        def answers(request: httpx.Request) -> httpx.Response:
            prompt = json.loads(request.read())["messages"][-1]["content"]
            return httpx.Response(200, json=_body("4" if "2 + 2" in prompt else "100"))

        with _client(model_entry, answers) as client:
            run_task(
                task=verifiable_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
            )
        calls: dict = {}
        with _judge(judge_entry, _judging(calls=calls)) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=verifiable_task)
        assert report.graded == []
        assert calls.get("n", 0) == 0
        assert all("no rubric" in r or "not a subjective" in r for _s, r in report.skipped)

    def test_a_task_that_changed_since_the_run_is_refused(
        self, model_entry, judge_entry, tmp_path
    ) -> None:
        """The comparability gate. Nothing crashes if you grade against an edited
        rubric -- you simply get a number comparable to nothing."""
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        original = _task_document()
        task_v1 = TaskSpec.from_document(original)

        handler = lambda _r: httpx.Response(200, json=_body("feedback"))  # noqa: E731
        with _client(model_entry, handler) as client:
            run_task(
                task=task_v1,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
            )

        edited = _task_document()
        edited["rubric"]["criteria"][0]["description"] = "Something else entirely."
        task_v2 = TaskSpec.from_document(edited)
        assert task_v2.content_sha != task_v1.content_sha, "precondition"

        calls: dict = {}
        with _judge(judge_entry, _judging(calls=calls)) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=task_v2)
        assert report.graded == []
        assert calls.get("n", 0) == 0
        assert all("has changed since this run" in r for _s, r in report.skipped)

    def test_the_refusal_names_both_hashes_and_the_override(
        self, model_entry, judge_entry, tmp_path
    ) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        task_v1 = TaskSpec.from_document(_task_document())
        handler = lambda _r: httpx.Response(200, json=_body("feedback"))  # noqa: E731
        with _client(model_entry, handler) as client:
            run_task(
                task=task_v1, entry=model_entry, run_id=RUN_ID, client=client, artifact_store=store
            )
        edited = _task_document()
        edited["rubric"]["criteria"][0]["weight"] = 9.0
        task_v2 = TaskSpec.from_document(edited)

        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=task_v2)
        reason = report.skipped[0][1]
        assert task_v1.content_sha[:12] in reason
        assert task_v2.content_sha[:12] in reason
        assert "--allow-task-drift" in reason

    def test_drift_can_be_overridden_deliberately(self, model_entry, judge_entry, tmp_path) -> None:
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        task_v1 = TaskSpec.from_document(_task_document())
        handler = lambda _r: httpx.Response(200, json=_body("feedback"))  # noqa: E731
        with _client(model_entry, handler) as client:
            run_task(
                task=task_v1, entry=model_entry, run_id=RUN_ID, client=client, artifact_store=store
            )
        edited = _task_document()
        edited["rubric"]["criteria"][0]["weight"] = 9.0
        task_v2 = TaskSpec.from_document(edited)

        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(
                run_id=RUN_ID,
                store=store,
                judge=judge,
                task=task_v2,
                allow_task_drift=True,
            )
        assert report.graded == ["s1"]

    def test_a_sample_the_task_no_longer_has_is_skipped(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, _log = archived_run
        trimmed = anchored_task.model_copy(deep=True)
        trimmed.samples = [s for s in trimmed.samples if s.id != "s2"]
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=trimmed)
        assert report.graded == ["s1"]
        assert [sample_id for sample_id, _reason in report.skipped] == ["s2"]
        assert "no longer has a sample" in report.skipped[0][1]


class TestRegradeFailures:
    def test_a_failing_judge_leaves_the_sample_gradable_rather_than_errored(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """Flipping it to `error` would make a judge outage look like a broken
        run forever after -- and it would stop the next regrade from retrying."""
        store, _log = archived_run
        handler = lambda _r: httpx.Response(200, json=_body("garbage"))  # noqa: E731
        with _judge(judge_entry, handler) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert report.graded == []
        assert len(report.failed) == 2
        record = report.eval_log.results[0]
        assert record.score is None
        assert record.scorable is False
        assert record.error is None

    def test_a_failed_regrade_still_reports_what_it_spent(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, _log = archived_run
        handler = lambda _r: httpx.Response(200, json=_body("garbage"))  # noqa: E731
        with _judge(judge_entry, handler) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert report.judge_cost_usd > 0.0

    def test_a_failed_sample_can_be_retried_by_a_later_regrade(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, _log = archived_run
        bad = lambda _r: httpx.Response(200, json=_body("garbage"))  # noqa: E731
        with _judge(judge_entry, bad) as judge:
            regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        with _judge(judge_entry, _judging()) as judge:
            second = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert second.graded == ["s1", "s2"]


class TestDryRun:
    def test_it_writes_nothing_back(self, archived_run, anchored_task, judge_entry) -> None:
        store, _log = archived_run
        before = json.dumps(store.get_json(eval_log_key(RUN_ID)), sort_keys=True)
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(
                run_id=RUN_ID, store=store, judge=judge, task=anchored_task, dry_run=True
            )
        assert report.graded == ["s1", "s2"], "it still says what WOULD change"
        assert json.dumps(store.get_json(eval_log_key(RUN_ID)), sort_keys=True) == before
        assert not store.exists(judge_key(RUN_ID, "s1"))

    def test_it_still_calls_the_judge_and_says_so(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """'--dry-run' answers 'what would this change', NOT 'what would this
        cost' -- and a reader must not be able to mistake the two."""
        store, _log = archived_run
        calls: dict = {}
        with _judge(judge_entry, _judging(calls=calls)) as judge:
            report = regrade_run(
                run_id=RUN_ID, store=store, judge=judge, task=anchored_task, dry_run=True
            )
        assert calls["n"] == 4, "two samples x two criteria: real calls, real money"
        assert report.judge_cost_usd > 0.0


class TestReportSummary:
    def test_it_names_every_bucket(self, archived_run, anchored_task, judge_entry) -> None:
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        summary = report.summary()
        assert RUN_ID in summary
        assert "graded 2" in summary and "failed 0" in summary and "skipped 0" in summary
        assert "judge cost" in summary


def _task_document() -> dict:
    """A task as a plain document, so ``from_document`` stamps a real content_sha."""
    return {
        "version": 1,
        "id": "test/drift",
        "title": "Drift",
        "kind": "subjective",
        "scorer": {"kind": "llm_judge", "rubric_id": "drift-v1"},
        "rubric": {
            "id": "drift-v1",
            "scale_min": 0.0,
            "scale_max": 1.0,
            "criteria": [{"name": "c", "description": "Is it specific?", "weight": 1.0}],
        },
        "samples": [{"id": "s1", "input": "Give feedback."}],
    }


class TestAJudgeFailureStaysRegradable:
    """E3 — the runner and this module must agree on what a judge failure is.

    They record it differently, and both are right to:

      * the ONLINE runner sets ``error`` so the run reports ``partial`` rather
        than claiming ``succeeded`` while its grading failed;
      * a REGRADE leaves ``error`` alone so a judge outage does not make the run
        look broken forever.

    Read through ``error`` alone, the runner's shape is indistinguishable from a
    sample whose model call died -- so it was skipped as ungradable, making a
    judge outage **permanently** unrecoverable. That is the exact outcome this
    module exists to prevent, and it would have bitten the moment the runner
    service was wired up.
    """

    def _run_with_a_failing_judge(self, task, entry, judge_entry, tmp_path):
        """A run through the ONLINE path whose judge could not answer."""
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        candidate = lambda _r: httpx.Response(  # noqa: E731
            200, json=_body("Your thesis needs sharpening.")
        )
        garbage = lambda _r: httpx.Response(200, json=_body("not json at all"))  # noqa: E731
        with _client(entry, candidate) as client, _judge(judge_entry, garbage) as judge:
            log = run_task(
                task=task,
                entry=entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
                artifact_store=store,
            )
        return store, log

    def test_the_online_runner_really_does_produce_that_shape(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """Guards the premise of every test below -- if the runner stops setting
        `error` on a judge failure, these would pass vacuously."""
        _store, log = self._run_with_a_failing_judge(
            anchored_task, model_entry, judge_entry, tmp_path
        )
        record = log.results[0]
        assert record.score is None
        assert record.error is not None, "the run must still report the outage"
        assert record.judge_serving_config is not None, "we know who was asked"
        assert record.transcript_uri is not None, "the completion was bought and archived"
        assert log.status is RunStatus.FAILED

    def test_it_is_recognised_as_a_judge_failure_not_a_dead_sample(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        _store, log = self._run_with_a_failing_judge(
            anchored_task, model_entry, judge_entry, tmp_path
        )
        assert all(is_judge_failure(r) for r in log.results)

    def test_a_dead_candidate_call_is_not_mistaken_for_one(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """The distinction must be structural, not a string match: a sample that
        never reached the judge has no judge config and no transcript."""
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        with (
            _client(model_entry, lambda _r: httpx.Response(500)) as client,
            _judge(judge_entry, _judging()) as judge,
        ):
            log = run_task(
                task=anchored_task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                judge=judge,
                artifact_store=store,
            )
        assert not any(is_judge_failure(r) for r in log.results)

    def test_a_later_regrade_recovers_the_run(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """The whole point: the judge came back, so the run must too."""
        store, _log = self._run_with_a_failing_judge(
            anchored_task, model_entry, judge_entry, tmp_path
        )
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert report.graded == ["s1", "s2"]
        assert report.mean_score == pytest.approx(1.0)

    def test_the_stale_judge_error_is_cleared_when_the_retry_succeeds(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """A leftover error would keep the run reporting `partial` forever, and
        would sit next to a score contradicting it."""
        store, _log = self._run_with_a_failing_judge(
            anchored_task, model_entry, judge_entry, tmp_path
        )
        with _judge(judge_entry, _judging()) as judge:
            regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        reloaded = load_eval_log(store, RUN_ID)
        assert all(r.error is None for r in reloaded.results)
        assert reloaded.error_count == 0
        assert reloaded.status is RunStatus.SUCCEEDED, "the run recovered, and says so"

    def test_a_second_failure_leaves_it_retryable_again(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """A judge that is still down must not burn the sample's last chance."""
        store, _log = self._run_with_a_failing_judge(
            anchored_task, model_entry, judge_entry, tmp_path
        )
        still_broken = lambda _r: httpx.Response(503)  # noqa: E731
        with _judge(judge_entry, still_broken) as judge:
            second = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert second.graded == []
        assert len(second.failed) == 2
        assert all(is_judge_failure(r) for r in second.eval_log.results)

        with _judge(judge_entry, _judging()) as judge:
            third = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert third.graded == ["s1", "s2"]

    def test_the_run_keeps_reporting_the_outage_while_it_persists(
        self, anchored_task, model_entry, judge_entry, tmp_path
    ) -> None:
        """Retryable must not mean silent: a record that arrived with an error
        keeps one, refreshed to the latest attempt's."""
        store, _log = self._run_with_a_failing_judge(
            anchored_task, model_entry, judge_entry, tmp_path
        )
        with _judge(judge_entry, lambda _r: httpx.Response(503)) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        record = report.eval_log.results[0]
        assert record.error is not None
        assert "TransientModelError" in record.error, "refreshed to THIS attempt's failure"

    def test_a_verifiable_scoring_error_is_still_not_regradable(
        self, model_entry, judge_entry, tmp_path
    ) -> None:
        """A sample with a transcript and an error that is NOT the judge's must
        stay skipped -- the widened gate must not swallow other failures."""
        store = LocalArtifactStore(tmp_path)
        store.ensure_bucket()
        task = TaskSpec.model_validate(
            {
                "version": 1,
                "id": "test/bad-target",
                "title": "Bad target",
                "kind": "verifiable",
                "scorer": {"kind": "numeric_match"},
                "samples": [{"id": "s1", "input": "What is 2 + 2?", "target": "no number here"}],
            }
        )
        with _client(model_entry, lambda _r: httpx.Response(200, json=_body("4"))) as client:
            log = run_task(
                task=task,
                entry=model_entry,
                run_id=RUN_ID,
                client=client,
                artifact_store=store,
            )
        assert log.results[0].error is not None and log.results[0].transcript_uri is not None
        assert not is_judge_failure(log.results[0])

        calls: dict = {}
        with _judge(judge_entry, _judging(calls=calls)) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=task)
        assert report.graded == []
        assert calls.get("n", 0) == 0


class TestDryRunChangesNothing:
    """E4 — `regrade_run` documents its results as "ready to persist".

    A dry run that hands back scored records makes that sentence a trap: a
    caller following the documented contract would write grades this function
    deliberately did not archive, leaving the store and the database disagreeing
    about a run with nothing to say which is right.
    """

    def test_the_returned_records_are_untouched(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(
                run_id=RUN_ID, store=store, judge=judge, task=anchored_task, dry_run=True
            )
        for record in report.eval_log.results:
            assert record.score is None
            assert record.scorable is False
            assert record.judge_serving_config is None
            assert record.judge_cost_usd == 0.0
            assert record.judge_transcript_uri is None

    def test_persisting_the_report_after_a_dry_run_would_write_nothing_new(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """The failure mode stated directly: a doc-following caller cannot
        write a grade that was never archived."""
        store, log = archived_run
        before = [r.model_dump(mode="json") for r in log.results]
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(
                run_id=RUN_ID, store=store, judge=judge, task=anchored_task, dry_run=True
            )
        assert [r.model_dump(mode="json") for r in report.eval_log.results] == before

    def test_it_still_reports_what_WOULD_have_changed(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """Non-mutating must not mean uninformative."""
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(
                run_id=RUN_ID, store=store, judge=judge, task=anchored_task, dry_run=True
            )
        assert report.graded == ["s1", "s2"]
        assert report.judge_cost_usd > 0.0

    def test_the_report_says_it_was_a_dry_run(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """On the report, not only in the caller's memory: `eval_log` is
        otherwise indistinguishable from a real one."""
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(
                run_id=RUN_ID, store=store, judge=judge, task=anchored_task, dry_run=True
            )
        assert report.dry_run is True
        assert "DRY RUN" in report.summary()

    def test_a_real_run_is_not_flagged_as_one(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            report = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert report.dry_run is False
        assert "DRY RUN" not in report.summary()

    def test_a_dry_run_does_not_block_the_real_one_that_follows(
        self, archived_run, anchored_task, judge_entry
    ) -> None:
        """If dry-run had mutated the records, the real run would then skip them
        as `already scored` -- and grade nothing."""
        store, _log = archived_run
        with _judge(judge_entry, _judging()) as judge:
            regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task, dry_run=True)
        with _judge(judge_entry, _judging()) as judge:
            real = regrade_run(run_id=RUN_ID, store=store, judge=judge, task=anchored_task)
        assert real.graded == ["s1", "s2"]
        assert load_eval_log(store, RUN_ID).mean_score == pytest.approx(1.0)


# --------------------------------------------------------------------------
# The row-level predicate contract (for the judge-calibration sweep, PR #13)
# --------------------------------------------------------------------------

NEVER_JUDGED_SQL = (
    "score_value IS NULL AND transcript_uri IS NOT NULL "
    "AND judge_transcript_uri IS NULL AND judge_prompt_tokens = 0"
)
JUDGE_FAILED_SQL = (
    "score_value IS NULL AND transcript_uri IS NOT NULL "
    "AND (judge_transcript_uri IS NOT NULL OR judge_prompt_tokens > 0)"
)
UNGRADABLE_SQL = "transcript_uri IS NULL"
GRADED_SQL = "score_value IS NOT NULL"


class TestTheRowLevelPredicateContract:
    """What a nightly sweep may SELECT, pinned against a real ``results`` table.

    The judge-calibration sweep picks its candidates in SQL, while
    :mod:`ida_harness.regrade` decides what it will actually grade in Python. If
    those two disagree the failure is not a crash -- it is a **standoff**: the
    sweep nominates a sample every night, the grader declines or fails every
    night, and the only visible symptom is a bill.

    So the contract is asserted here by materialising every state a subjective
    sample can be in through :func:`insert_results`, and querying it.
    """

    @pytest.fixture
    def rows(self, anchored_task, model_entry, judge_entry, tmp_path):
        """One row per reachable state, in a real table, built by real runs."""
        from ida_core.contracts import RunRecord, RunStatus
        from ida_core.db import Base, make_engine, make_session_factory, session_scope
        from ida_core.repositories import create_run, insert_results

        ok = _judging()
        garbage = lambda _r: httpx.Response(200, json=_body("not json"))  # noqa: E731
        answer = lambda _r: httpx.Response(  # noqa: E731
            200, json=_body("Your thesis needs sharpening.")
        )
        dead = lambda _r: httpx.Response(500)  # noqa: E731

        def one_run(name, run_id, candidate_h, judge_h, use_judge, regrade_h=None):
            store = LocalArtifactStore(tmp_path / name)
            store.ensure_bucket()
            judge = _judge(judge_entry, judge_h) if use_judge else None
            with _client(model_entry, candidate_h) as client:
                log = run_task(
                    task=anchored_task,
                    entry=model_entry,
                    run_id=run_id,
                    client=client,
                    judge=judge,
                    artifact_store=store,
                )
            if judge is not None:
                judge.close()
            if regrade_h is None:
                return log.results[0]
            with _judge(judge_entry, regrade_h) as rj:
                report = regrade_run(run_id=run_id, store=store, judge=rj, task=anchored_task)
            return report.eval_log.results[0]

        states = {
            "never judged": one_run("a", "run_pa000000000000000000000", answer, ok, False),
            "judge failed online": one_run(
                "b", "run_pb000000000000000000000", answer, garbage, True
            ),
            "judge failed regrading": one_run(
                "c", "run_pc000000000000000000000", answer, ok, False, regrade_h=garbage
            ),
            "graded regrading": one_run(
                "d", "run_pd000000000000000000000", answer, ok, False, regrade_h=ok
            ),
            "graded online": one_run("e", "run_pe000000000000000000000", answer, ok, True),
            "candidate died": one_run("f", "run_pf000000000000000000000", dead, ok, False),
        }

        engine = make_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = make_session_factory(engine)
        with session_scope(factory) as session:
            for record in states.values():
                create_run(
                    session,
                    RunRecord(
                        id=record.run_id,
                        status=RunStatus.SUCCEEDED,
                        task_id=record.task_id,
                        model_key=record.model_key,
                        harness_version="0.1.0",
                    ),
                )
            insert_results(session, list(states.values()))

        def select(where: str) -> set[str]:
            from sqlalchemy import text

            by_id = {r.id: name for name, r in states.items()}
            with session_scope(factory) as session:
                found = session.execute(
                    text(f"SELECT id FROM results WHERE {where}")  # noqa: S608 - fixed literals
                ).scalars()
                return {by_id[i] for i in found}

        return states, select

    def test_every_state_is_reachable(self, rows) -> None:
        """Guards the guard: six states, six rows, all built by real runs."""
        states, _select = rows
        assert len(states) == 6

    def test_judge_serving_config_IS_NULL_is_a_trap(self, rows) -> None:
        """⚠ THE OBVIOUS MARKER DOES NOT WORK, AND FAILS SILENTLY.

        SQLAlchemy's ``JSON`` column stores Python ``None`` as the JSON literal
        ``'null'``, not as SQL ``NULL``. So ``judge_serving_config IS NULL``
        matches **nothing**, ever -- including rows no judge has touched. Read
        back through the ORM the same column is ``None``, so Python and SQL
        disagree about the identical row and neither says so.

        This is a property of the pre-existing 0002 column, not of the judge
        work; it is pinned here because it is exactly the marker a reader
        reaches for first.
        """
        _states, select = rows
        assert select("judge_serving_config IS NULL") == set()
        assert select("judge_serving_config IS NOT NULL") == {
            "never judged",
            "judge failed online",
            "judge failed regrading",
            "graded regrading",
            "graded online",
            "candidate died",
        }

    def test_the_naive_sweep_predicate_selects_three_different_things(self, rows) -> None:
        """``scorable IS FALSE AND score_value IS NULL`` conflates the class you
        want with a standoff and with a nomination that can never succeed."""
        _states, select = rows
        assert select("scorable = 0 AND score_value IS NULL") == {
            "never judged",  # wanted
            "judge failed regrading",  # the standoff: re-nominated, re-fails, re-bills
            "candidate died",  # can never succeed; no completion exists
        }

    def test_the_naive_predicate_also_MISSES_an_online_judge_failure(self, rows) -> None:
        """The opposite error, and the quieter one: a sample whose online
        grading failed carries ``scorable=TRUE``, so it is never re-nominated at
        all. Silent permanent non-retry, once the runner service is wired."""
        _states, select = rows
        assert "judge failed online" not in select("scorable = 0 AND score_value IS NULL")

    def test_scorable_does_not_answer_the_question_being_asked(self, rows) -> None:
        """``scorable`` records whether a judge was CONFIGURED, not whether this
        sample still needs grading -- which is why no predicate below uses it."""
        _states, select = rows
        assert select("scorable = 1") == {
            "judge failed online",
            "graded regrading",
            "graded online",
        }

    def test_the_four_classes_partition_every_row(self, rows) -> None:
        """Mutually exclusive and exhaustive -- so a sweep can reason about them
        without a fifth 'and otherwise?' case."""
        _states, select = rows
        classes = {
            "never judged": select(NEVER_JUDGED_SQL),
            "judge failed": select(JUDGE_FAILED_SQL),
            "ungradable": select(UNGRADABLE_SQL),
            "graded": select(GRADED_SQL),
        }
        union: set[str] = set()
        for name, members in classes.items():
            assert not (union & members), f"{name} overlaps an earlier class"
            union |= members
        assert union == set(_states)

    def test_the_nomination_class_is_exactly_what_has_never_been_tried(self, rows) -> None:
        _states, select = rows
        assert select(NEVER_JUDGED_SQL) == {"never judged"}

    def test_the_retry_class_catches_a_failure_from_EITHER_path(self, rows) -> None:
        """Online and retroactive grading record a failure differently -- one
        sets ``error``, one does not -- and both must land here."""
        _states, select = rows
        assert select(JUDGE_FAILED_SQL) == {"judge failed online", "judge failed regrading"}

    def test_the_ungradable_class_is_the_one_with_no_completion(self, rows) -> None:
        _states, select = rows
        assert select(UNGRADABLE_SQL) == {"candidate died"}

    def test_the_python_predicates_agree_with_the_sql_row_for_row(self, rows) -> None:
        """The whole point. If these drift, the sweep and the grader disagree
        about the same row and the symptom is a bill, not a failure."""
        from ida_harness.regrade import is_judge_failure, is_never_judged, is_ungradable

        states, select = rows
        for label, sql, python in [
            ("never judged", NEVER_JUDGED_SQL, is_never_judged),
            ("judge failed", JUDGE_FAILED_SQL, is_judge_failure),
            ("ungradable", UNGRADABLE_SQL, is_ungradable),
        ]:
            from_sql = select(sql)
            from_python = {name for name, record in states.items() if python(record)}
            assert from_sql == from_python, f"{label}: SQL {from_sql} vs Python {from_python}"

    def test_regrade_grades_exactly_the_two_classes_it_should(
        self, rows, anchored_task, judge_entry
    ) -> None:
        """Closing the loop: what the sweep may nominate is what the grader will
        actually act on."""
        from ida_harness.regrade import _skip_reason, is_judge_failure, is_never_judged

        states, _select = rows
        for name, record in states.items():
            actionable = _skip_reason(record) is None
            expected = is_never_judged(record) or is_judge_failure(record)
            assert actionable == expected, name
