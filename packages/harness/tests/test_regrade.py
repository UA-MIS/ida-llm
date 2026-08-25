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
from ida_core.contracts import TaskSpec
from ida_harness.client import OpenAICompatibleClient
from ida_harness.judge import LLMJudge
from ida_harness.regrade import load_eval_log, regrade_run
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
        assert all("no completion to grade" in reason for _s, reason in report.skipped)

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
