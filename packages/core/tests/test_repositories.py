"""Persistence round-trips. The D-1 invariant (serving config by value) lives here."""

from __future__ import annotations

import pytest

from ida_core.contracts import (
    CriterionScore,
    Quantization,
    ResultRecord,
    RunRecord,
    RunStatus,
    SamplingParams,
    Score,
    ScorerKind,
    ServingConfig,
    TokenUsage,
)
from ida_core.db import session_scope
from ida_core.ids import new_result_id, new_run_id
from ida_core.repositories import (
    create_run,
    existing_run_keys,
    finish_run,
    get_run,
    insert_results,
    list_results_for_run,
    list_runs,
    list_ungraded_subjective_results,
    mark_run_running,
    models_with_any_run,
    result_row_to_record,
    run_row_to_record,
)


def _run(serving=None, **overrides) -> RunRecord:
    base = {
        "id": new_run_id(),
        "status": RunStatus.QUEUED,
        "task_id": "demo/t",
        "model_key": "mock",
        "harness_version": "0.1.0",
        "task_git_sha": "a" * 40,
        "sample_count": 2,
        "serving_config": serving,
    }
    base.update(overrides)
    return RunRecord(**base)


def _result(run_id: str, serving: ServingConfig, **overrides) -> ResultRecord:
    base = {
        "id": new_result_id(),
        "run_id": run_id,
        "task_id": "demo/t",
        "sample_id": "s1",
        "model_key": "mock",
        "serving_config": serving,
        "score": Score(scorer=ScorerKind.EXACT_MATCH, value=1.0, passed=True, explanation="ok"),
        "usage": TokenUsage(prompt_tokens=10, completion_tokens=3),
        "cost_usd": 0.0,
        "latency_ms": 12.5,
        "transcript_uri": "s3://ida-artifacts/runs/x/transcripts/s1.json",
    }
    base.update(overrides)
    return ResultRecord(**base)


class TestRunRoundTrip:
    def test_create_then_read(self, session_factory) -> None:
        record = _run()
        with session_scope(session_factory) as session:
            create_run(session, record)
        with session_scope(session_factory) as session:
            restored = run_row_to_record(get_run(session, record.id))
        assert restored.id == record.id
        assert restored.status is RunStatus.QUEUED
        assert restored.task_git_sha == "a" * 40
        assert restored.serving_config is None

    def test_missing_run_returns_none(self, session_factory) -> None:
        with session_scope(session_factory) as session:
            assert get_run(session, "run_nope") is None

    def test_mark_running_records_serving_config(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        record = _run()
        with session_scope(session_factory) as session:
            create_run(session, record)
        with session_scope(session_factory) as session:
            mark_run_running(session, record.id, serving_config)
        with session_scope(session_factory) as session:
            restored = run_row_to_record(get_run(session, record.id))
        assert restored.status is RunStatus.RUNNING
        assert restored.started_at is not None
        assert restored.serving_config == serving_config

    def test_mark_running_unknown_run_raises(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        with session_scope(session_factory) as session, pytest.raises(KeyError):
            mark_run_running(session, "run_nope", serving_config)

    def test_finish_run_writes_rollup(self, session_factory, serving_config: ServingConfig) -> None:
        record = _run()
        with session_scope(session_factory) as session:
            create_run(session, record)
        record.status = RunStatus.SUCCEEDED
        record.serving_config = serving_config
        record.scored_count = 2
        record.mean_score = 0.5
        record.total_usage = TokenUsage(prompt_tokens=20, completion_tokens=6)
        record.total_cost_usd = 0.25
        with session_scope(session_factory) as session:
            finish_run(session, record)
        with session_scope(session_factory) as session:
            restored = run_row_to_record(get_run(session, record.id))
        assert restored.status is RunStatus.SUCCEEDED
        assert restored.mean_score == 0.5
        assert restored.total_usage.total_tokens == 26
        assert restored.total_cost_usd == 0.25
        assert restored.finished_at is not None


class TestListRuns:
    def test_newest_first(self, session_factory) -> None:
        ids = []
        with session_scope(session_factory) as session:
            for _ in range(3):
                record = _run()
                ids.append(record.id)
                create_run(session, record)
        with session_scope(session_factory) as session:
            listed = [r.id for r in list_runs(session)]
        assert listed[0] == ids[-1]

    def test_filters(self, session_factory) -> None:
        with session_scope(session_factory) as session:
            create_run(session, _run(task_id="a", model_key="m1"))
            create_run(session, _run(task_id="b", model_key="m2", status=RunStatus.FAILED))
        with session_scope(session_factory) as session:
            assert len(list_runs(session, task_id="a")) == 1
            assert len(list_runs(session, model_key="m2")) == 1
            assert len(list_runs(session, status=RunStatus.FAILED)) == 1
            assert len(list_runs(session, status=RunStatus.SUCCEEDED)) == 0

    def test_pagination(self, session_factory) -> None:
        with session_scope(session_factory) as session:
            for _ in range(5):
                create_run(session, _run())
        with session_scope(session_factory) as session:
            assert len(list_runs(session, limit=2)) == 2
            assert len(list_runs(session, limit=2, offset=4)) == 1


class TestResults:
    def test_round_trip_preserves_serving_config_by_value(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """D-1: the stored config must survive verbatim, including sampling params."""
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [_result(run.id, serving_config)])
        with session_scope(session_factory) as session:
            rows = list_results_for_run(session, run.id)
        restored = result_row_to_record(rows[0])
        assert restored.serving_config == serving_config
        assert restored.serving_config.sampling.seed == serving_config.sampling.seed

    def test_editing_the_registry_later_cannot_rewrite_history(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """The whole point of copying by value: mutate the source, stored row is untouched."""
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [_result(run.id, serving_config)])
        serving_config.quantization = Quantization.INT4
        serving_config.sampling = SamplingParams(temperature=1.9)
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.serving_config.quantization is Quantization.NONE
        assert restored.serving_config.sampling.temperature == 0.0

    def test_score_is_flattened_and_reassembled(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        run = _run()
        score = Score(
            scorer=ScorerKind.NUMERIC_MATCH,
            value=1.0,
            passed=True,
            explanation="got 42, want 42",
            details={"target": 42.0, "extracted": 42.0},
        )
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [_result(run.id, serving_config, score=score)])
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.score == score

    def test_unscorable_result_has_no_score(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """Subjective samples store a null score, never a zero."""
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [_result(run.id, serving_config, score=None, scorable=False)])
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.score is None
        assert restored.scorable is False

    def test_errored_result_records_the_reason(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(
                session,
                [_result(run.id, serving_config, score=None, error="TransientModelError: 503")],
            )
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.error is not None and "503" in restored.error

    def test_results_are_ordered_by_sample_id(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(
                session,
                [
                    _result(run.id, serving_config, sample_id="z"),
                    _result(run.id, serving_config, sample_id="a"),
                ],
            )
        with session_scope(session_factory) as session:
            assert [r.sample_id for r in list_results_for_run(session, run.id)] == ["a", "z"]

    def test_one_result_per_sample_per_run_is_enforced(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """The unique index is what stops a double-processed job double-counting."""
        from sqlalchemy.exc import IntegrityError

        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
        with pytest.raises(IntegrityError), session_scope(session_factory) as session:
            insert_results(
                session,
                [
                    _result(run.id, serving_config, sample_id="dup"),
                    _result(run.id, serving_config, sample_id="dup"),
                ],
            )


class TestJudgeSpendIsPersistedSeparately:
    """A judged sample buys two things; the row must be able to tell them apart.

    Folding judge tokens into ``prompt_tokens`` would be unrecoverable -- nothing
    downstream could split the number again, and a cheap model graded by an
    expensive judge would read as an expensive model forever.
    """

    def _judged(self, run_id: str, serving: ServingConfig) -> ResultRecord:
        return _result(
            run_id,
            serving,
            score=Score(
                scorer=ScorerKind.LLM_JUDGE,
                value=0.75,
                passed=None,
                explanation="rubric r1: weighted 0.750 over 2 criteria",
                criteria=[
                    CriterionScore(name="specificity", value=1.0, weight=3.0, explanation="cited"),
                    CriterionScore(name="restraint", value=0.0, weight=1.0, explanation="rewrote"),
                ],
                details={"rubric_id": "r1"},
            ),
            usage=TokenUsage(prompt_tokens=10, completion_tokens=3),
            cost_usd=0.0,
            judge_serving_config=serving,
            judge_usage=TokenUsage(prompt_tokens=200, completion_tokens=40),
            judge_cost_usd=0.00028,
            judge_transcript_uri="s3://ida-artifacts/runs/x/judge/s1.json",
        )

    def test_judge_usage_and_cost_survive_the_round_trip(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [self._judged(run.id, serving_config)])
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.judge_usage == TokenUsage(prompt_tokens=200, completion_tokens=40)
        assert restored.judge_cost_usd == 0.00028

    def test_the_candidate_s_own_accounting_is_untouched_by_the_judge_s(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [self._judged(run.id, serving_config)])
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.usage == TokenUsage(prompt_tokens=10, completion_tokens=3)
        assert restored.cost_usd == 0.0

    def test_the_judge_evidence_pointer_survives(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """D-3 applied to the grade: a rubric score with no traceable reasoning
        is an opinion, not evidence."""
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [self._judged(run.id, serving_config)])
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.judge_transcript_uri == "s3://ida-artifacts/runs/x/judge/s1.json"

    def test_the_per_criterion_rows_survive_and_reconstruct_the_total(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """What makes a judge-calibration study a query rather than a re-run."""
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [self._judged(run.id, serving_config)])
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        rows = restored.score.criteria
        assert [(r.name, r.value, r.weight) for r in rows] == [
            ("specificity", 1.0, 3.0),
            ("restraint", 0.0, 1.0),
        ]
        weighted = sum(r.value * r.weight for r in rows) / sum(r.weight for r in rows)
        assert weighted == restored.score.value

    def test_passed_stays_null_rather_than_collapsing_to_false(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [self._judged(run.id, serving_config)])
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.score.passed is None

    def test_an_unjudged_result_stores_honest_zeros(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """Zero is the TRUE answer for a row nothing judged, not a placeholder."""
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(session, [_result(run.id, serving_config)])
        with session_scope(session_factory) as session:
            restored = result_row_to_record(list_results_for_run(session, run.id)[0])
        assert restored.judge_usage.total_tokens == 0
        assert restored.judge_cost_usd == 0.0
        assert restored.judge_transcript_uri is None
        assert restored.judge_serving_config is None


class TestSweepPlanningHelpers:
    """The read-only queries the scheduled sweeps plan against.

    Tested here, at the contracts<->rows layer where they live, and not only
    through the sweeps that call them: these are the predicates that decide
    whether a nightly CronJob spends provider credits, and a wrong answer is
    silent -- a duplicate charge or a measurement that never happens.
    """

    def test_existing_run_keys_returns_the_dedupe_triple(self, session_factory) -> None:
        run = _run(status=RunStatus.SUCCEEDED, task_content_sha="sha-1")
        with session_scope(session_factory) as session:
            create_run(session, run)
        with session_scope(session_factory) as session:
            keys = existing_run_keys(session, statuses=[RunStatus.SUCCEEDED])
        assert keys == {("demo/t", "mock", "sha-1")}

    def test_existing_run_keys_filters_by_status(self, session_factory) -> None:
        """`succeeded` and `failed` must never be conflated.

        Including a failed run in the index would let one bad night permanently
        suppress a pair; excluding a succeeded one would re-buy a number we have.
        """
        with session_scope(session_factory) as session:
            create_run(session, _run(status=RunStatus.SUCCEEDED, task_content_sha="ok"))
            create_run(session, _run(status=RunStatus.FAILED, task_content_sha="bad"))
        with session_scope(session_factory) as session:
            keys = existing_run_keys(session, statuses=[RunStatus.SUCCEEDED])
        assert keys == {("demo/t", "mock", "ok")}

    def test_existing_run_keys_distinguishes_content_shas(self, session_factory) -> None:
        """B8: the same pair at two task versions is two different measurements."""
        with session_scope(session_factory) as session:
            create_run(session, _run(status=RunStatus.SUCCEEDED, task_content_sha="v1"))
            create_run(session, _run(status=RunStatus.SUCCEEDED, task_content_sha="v2"))
        with session_scope(session_factory) as session:
            keys = existing_run_keys(session, statuses=[RunStatus.SUCCEEDED])
        assert keys == {("demo/t", "mock", "v1"), ("demo/t", "mock", "v2")}

    def test_existing_run_keys_keeps_a_null_sha_as_null(self, session_factory) -> None:
        """A NULL must not be coerced into a wildcard that matches every candidate."""
        with session_scope(session_factory) as session:
            create_run(session, _run(status=RunStatus.SUCCEEDED, task_content_sha=None))
        with session_scope(session_factory) as session:
            keys = existing_run_keys(session, statuses=[RunStatus.SUCCEEDED])
        assert keys == {("demo/t", "mock", None)}

    def test_existing_run_keys_honours_the_model_scope(self, session_factory) -> None:
        with session_scope(session_factory) as session:
            create_run(session, _run(status=RunStatus.SUCCEEDED, task_content_sha="s"))
            create_run(
                session,
                _run(status=RunStatus.SUCCEEDED, model_key="other", task_content_sha="s"),
            )
        with session_scope(session_factory) as session:
            assert existing_run_keys(
                session, statuses=[RunStatus.SUCCEEDED], model_keys=["other"]
            ) == {("demo/t", "other", "s")}

    def test_existing_run_keys_short_circuits_on_empty_inputs(self, session_factory) -> None:
        """An empty scope means "nothing", never "everything".

        The dangerous reading is the other one: an empty model list silently
        widening to the whole table would make a scoped sweep dedupe against
        runs that have nothing to do with it.
        """
        with session_scope(session_factory) as session:
            create_run(session, _run(status=RunStatus.SUCCEEDED, task_content_sha="s"))
        with session_scope(session_factory) as session:
            assert existing_run_keys(session, statuses=[]) == set()
            assert (
                existing_run_keys(session, statuses=[RunStatus.SUCCEEDED], model_keys=[]) == set()
            )

    def test_models_with_any_run_reports_only_measured_models(self, session_factory) -> None:
        with session_scope(session_factory) as session:
            create_run(session, _run(status=RunStatus.SUCCEEDED, model_key="measured"))
            create_run(session, _run(status=RunStatus.FAILED, model_key="only-failed"))
        with session_scope(session_factory) as session:
            assert models_with_any_run(session, statuses=[RunStatus.SUCCEEDED]) == {"measured"}

    def test_list_ungraded_subjective_results_finds_unscored_samples(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(
                session,
                [_result(run.id, serving_config, sample_id="s1", score=None, scorable=False)],
            )
        with session_scope(session_factory) as session:
            assert [r.sample_id for r in list_ungraded_subjective_results(session)] == ["s1"]

    def test_a_scored_subjective_sample_is_not_a_candidate(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """The half of the predicate that stops nightly re-grading of graded work.

        Without it every judge-calibration firing would re-grade its entire
        history, at full provider cost, forever.
        """
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(
                session,
                [
                    _result(
                        run.id,
                        serving_config,
                        sample_id="graded",
                        scorable=False,
                        score=Score(
                            scorer=ScorerKind.LLM_JUDGE, value=0.7, passed=True, explanation="ok"
                        ),
                    )
                ],
            )
        with session_scope(session_factory) as session:
            assert list_ungraded_subjective_results(session) == []

    def test_a_scorable_sample_is_never_a_candidate(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """Verifiable samples are scored programmatically; a judge must not touch them."""
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(
                session,
                [_result(run.id, serving_config, sample_id="s1", score=None, scorable=True)],
            )
        with session_scope(session_factory) as session:
            assert list_ungraded_subjective_results(session) == []

    def test_the_candidate_list_is_bounded(
        self, session_factory, serving_config: ServingConfig
    ) -> None:
        """One pass must not become an unbounded transaction."""
        run = _run()
        with session_scope(session_factory) as session:
            create_run(session, run)
            insert_results(
                session,
                [
                    _result(run.id, serving_config, sample_id=f"s{i}", score=None, scorable=False)
                    for i in range(5)
                ],
            )
        with session_scope(session_factory) as session:
            assert len(list_ungraded_subjective_results(session, limit=2)) == 2

    def test_existing_run_keys_honours_the_created_after_bound(self, session_factory) -> None:
        """The bound that stops an abandoned `queued` row suppressing its pair forever.

        A sweep asks "is this pair in flight?" and answers it from a row. A row
        old enough that nothing will ever process it must answer no.
        """
        from datetime import timedelta

        from ida_core.db import utcnow as _utcnow

        now = _utcnow()
        with session_scope(session_factory) as session:
            create_run(
                session,
                _run(
                    status=RunStatus.QUEUED,
                    task_content_sha="fresh",
                    created_at=now - timedelta(seconds=10),
                ),
            )
            create_run(
                session,
                _run(
                    status=RunStatus.QUEUED,
                    task_content_sha="ancient",
                    created_at=now - timedelta(days=30),
                ),
            )

        cutoff = now - timedelta(hours=6)
        with session_scope(session_factory) as session:
            bounded = existing_run_keys(session, statuses=[RunStatus.QUEUED], created_after=cutoff)
            unbounded = existing_run_keys(session, statuses=[RunStatus.QUEUED])

        assert bounded == {("demo/t", "mock", "fresh")}
        assert len(unbounded) == 2, "without the bound both rows answer 'in flight'"
