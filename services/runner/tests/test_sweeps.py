"""The three CronJob entry points.

These sweeps are the only thing in the system that can commission provider spend
on a schedule with nobody watching, so the tests lead with the ways that goes
wrong: an empty registry, a budget blown, a queue that dies halfway, a judge that
is unconfigured or answering garbage. The happy path is one small class at the end.

Nothing here touches a real service. The queue is the in-memory implementation
(a real one, not a mock -- see ``ida_core.queue``), the database is SQLite, and
the two *enqueueing* sweeps never reach a model endpoint, because they do not:
they enqueue, and runners execute.

``judge-calibration`` is the exception and is different in kind -- it is the one
sweep that SPENDS, calling a judge itself rather than enqueueing work. Its tests
drive the real mock-model service in process, so the judge is answered by genuine
service code at zero cost, and no hosted judge is reachable from this file.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ida_core.config import Settings
from ida_core.contracts import ModelRegistry, RunJobMessage, RunRecord, RunStatus
from ida_core.db import session_scope, utcnow
from ida_core.ids import new_run_id
from ida_core.repositories import create_run, get_run, insert_results
from ida_runner import sweeps
from ida_runner.sweeps import (
    BudgetExceeded,
    Candidate,
    SweepContext,
    SweepReport,
    enforce_budget,
    main,
    run_judge_calibration,
    run_model_sweep,
    run_rebenchmark,
)

SUBJECTIVE_TASK = "demo/essay-feedback"
VERIFIABLE_TASK = "demo/arithmetic-quiz-check"
REPO_ROOT = Path(__file__).resolve().parents[3]


# ------------------------------------------------------------- fixtures ----


@pytest.fixture
def settings() -> Settings:
    """Explicit values, never the ambient environment.

    A sweep's whole job is bounded by its settings, so a test that inherited a
    developer's `.env` would be asserting against numbers it cannot see.
    """
    return Settings(
        sweep_max_runs=200,
        sweep_max_samples=2000,
        sweep_force=False,
        sweep_judge_candidate_limit=500,
    )


@pytest.fixture
def ctx(settings, session_factory, queue, registry, catalog) -> SweepContext:
    return SweepContext(
        settings=settings,
        session_factory=session_factory,
        queue=queue,
        registry=registry,
        catalog=catalog,
        git_sha="a" * 40,
    )


def _with(ctx: SweepContext, **overrides) -> SweepContext:
    """A context with some settings replaced.  Keeps the tests declarative."""
    return SweepContext(
        settings=ctx.settings.model_copy(update=overrides.pop("settings", {})),
        session_factory=overrides.pop("session_factory", ctx.session_factory),
        queue=overrides.pop("queue", ctx.queue),
        registry=overrides.pop("registry", ctx.registry),
        catalog=overrides.pop("catalog", ctx.catalog),
        git_sha=overrides.pop("git_sha", ctx.git_sha),
        artifact_store=overrides.pop("artifact_store", ctx.artifact_store),
    )


def _store(tmp_path: Path):
    """A real local artifact store. Retroactive grading reads archived blobs."""
    from ida_core.artifacts import LocalArtifactStore

    store = LocalArtifactStore(tmp_path / "artifacts")
    store.ensure_bucket()
    return store


def _scorable(ctx: SweepContext):
    return sweeps.scorable_tasks(ctx.catalog)


def _seed_terminal_run(
    session_factory,
    *,
    task_id: str,
    model_key: str,
    content_sha: str | None,
    status: RunStatus = RunStatus.SUCCEEDED,
    created_at=None,
) -> str:
    """A run in whatever state the worker (or a crash) would have left it."""
    run_id = new_run_id()
    with session_scope(session_factory) as session:
        create_run(
            session,
            RunRecord(
                id=run_id,
                status=status,
                task_id=task_id,
                model_key=model_key,
                task_content_sha=content_sha,
                task_git_sha="b" * 40,
                harness_version="0.1.0",
                created_at=created_at or utcnow(),
            ),
        )
    return run_id


class _ExplodingQueue:
    """Accepts ``ok_count`` messages, then fails every push.

    Models the realistic mid-sweep failure: Redis was reachable when planning
    started and is not any more. What is under test is that the sweep says how
    many landed rather than reporting the whole plan as enqueued.
    """

    def __init__(self, ok_count: int) -> None:
        self.ok_count = ok_count
        self.accepted: list[RunJobMessage] = []

    def enqueue(self, message: RunJobMessage) -> None:
        if len(self.accepted) >= self.ok_count:
            raise ConnectionError("redis is gone")
        self.accepted.append(message)

    def depth(self) -> int:
        return len(self.accepted)


# ---------------------------------------------------------- empty inputs ----


class TestNothingToDo:
    """A sweep with no work is a quiet success, not a fault.

    This is the steady state of a healthy nightly, so getting it wrong means
    either a permanently-red CronJob nobody trusts or a crash at 02:00.
    """

    def test_an_empty_registry_enqueues_nothing_and_succeeds(self, ctx) -> None:
        empty = _with(ctx, registry=ModelRegistry(models=[]))

        report = run_rebenchmark(empty)

        assert report.considered == 0
        assert report.enqueued == 0
        assert report.exit_code == 0
        assert empty.queue.depth() == 0
        assert report.balances()

    def test_a_registry_with_nothing_enabled_enqueues_nothing(self, ctx) -> None:
        """Disabling every model must not be read as "measure every model"."""
        disabled = ModelRegistry(
            models=[entry.model_copy(update={"enabled": False}) for entry in ctx.registry.models]
        )
        scoped = _with(ctx, registry=disabled)
        assert disabled.enabled_keys() == []

        report = run_rebenchmark(scoped)

        assert report.considered == 0
        assert report.exit_code == 0
        assert scoped.queue.depth() == 0

    def test_model_sweep_with_nothing_enabled_enqueues_nothing(self, ctx) -> None:
        disabled = ModelRegistry(
            models=[entry.model_copy(update={"enabled": False}) for entry in ctx.registry.models]
        )
        scoped = _with(ctx, registry=disabled)

        report = run_model_sweep(scoped)

        assert report.enqueued == 0
        assert report.exit_code == 0
        assert scoped.queue.depth() == 0

    def test_a_catalog_with_no_scorable_task_enqueues_nothing(self, ctx) -> None:
        """Subjective-only tasks are not enqueueable until the judge lands.

        Enqueueing them would spend credits producing completions that persist as
        `scorable=False` -- provider calls that can never become a number.
        """
        from ida_harness.tasks import TaskCatalog

        subjective = ctx.catalog.get(SUBJECTIVE_TASK)
        only_subjective = TaskCatalog({subjective.id: subjective}, {subjective.id: None})
        scoped = _with(ctx, catalog=only_subjective)

        report = run_rebenchmark(scoped)

        assert report.considered == 0
        assert scoped.queue.depth() == 0
        assert report.exit_code == 0


# --------------------------------------------------------------- dedupe ----


class TestDedupe:
    """The property that makes a nightly full-suite job affordable."""

    def test_an_already_succeeded_triple_is_skipped(self, ctx) -> None:
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
        )

        report = run_rebenchmark(ctx)

        assert report.skipped_dedupe == 1
        assert report.enqueued == report.considered - 1
        assert report.balances()
        enqueued_pairs = _drain_pairs(ctx.queue)
        assert (spec.id, "mock") not in enqueued_pairs

    def test_a_changed_content_sha_makes_the_pair_eligible_again(self, ctx) -> None:
        """B8: editing a task invalidates the previous measurement.

        The regression this guards is silent and expensive to discover: a task
        gets rewritten, dedupe still matches on `(task, model)`, and the
        dashboard keeps showing the OLD version's numbers under the new task's
        name forever.
        """
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha="stale-sha-from-a-previous-edition",
        )

        report = run_rebenchmark(ctx)

        assert report.skipped_dedupe == 0
        assert (spec.id, "mock") in _drain_pairs(ctx.queue)

    @pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.PARTIAL])
    def test_a_failed_or_partial_run_does_not_suppress_the_pair(self, ctx, status) -> None:
        """One bad night must not permanently retire a pair.

        A run whose samples errored is a record of an outage, not a measurement,
        so tonight's sweep is exactly what should retry it.
        """
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
            status=status,
        )

        report = run_rebenchmark(ctx)

        assert report.skipped_dedupe == 0
        assert (spec.id, "mock") in _drain_pairs(ctx.queue)

    @pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.RUNNING])
    def test_an_in_flight_pair_is_not_enqueued_twice(self, ctx, status) -> None:
        """`concurrencyPolicy: Forbid` does NOT cover this.

        Forbid stops a sweep stacking on itself. It says nothing about
        rebenchmark (02:00) and model-sweep (03:30) overlapping while a run is
        allowed six hours -- and every duplicate there is a real provider charge
        for a number already commissioned.
        """
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
            status=status,
        )

        report = run_rebenchmark(ctx)

        assert report.skipped_dedupe == 1
        assert (spec.id, "mock") not in _drain_pairs(ctx.queue)

    def test_a_null_sha_row_does_not_suppress_a_hashed_candidate(self, ctx) -> None:
        """A pre-content-hashing row must be re-measured once, not forever skipped.

        Treating NULL as "matches anything" would suppress precisely the run that
        backfills the missing sha.
        """
        spec = _scorable(ctx)[0]
        _seed_terminal_run(ctx.session_factory, task_id=spec.id, model_key="mock", content_sha=None)

        report = run_rebenchmark(ctx)

        assert report.skipped_dedupe == 0
        assert (spec.id, "mock") in _drain_pairs(ctx.queue)

    def test_a_second_firing_enqueues_nothing_new(self, ctx) -> None:
        """Idempotence, stated as the module docstring demands it."""
        first = run_rebenchmark(ctx)
        assert first.enqueued > 0

        second = run_rebenchmark(ctx)

        assert second.enqueued == 0
        assert second.skipped_dedupe == first.enqueued
        assert second.exit_code == 0

    def test_force_re_enqueues_everything(self, ctx) -> None:
        run_rebenchmark(ctx)
        _drain_pairs(ctx.queue)
        forced = _with(ctx, settings={"sweep_force": True})

        report = run_rebenchmark(forced)

        assert report.skipped_dedupe == 0
        assert report.enqueued == report.considered
        assert any("force=on" in note for note in report.notes)


# --------------------------------------------------------- budget guard ----


class TestBudgetGuard:
    """Refuse-and-report, never cap-and-proceed.

    A capped sweep would enqueue an ordering-dependent subset and exit 0, which
    reports a partial suite as a whole one and hides the cap from the operator
    forever. See `enforce_budget`'s docstring for the full reasoning.
    """

    def test_a_plan_over_the_run_cap_enqueues_nothing(self, ctx) -> None:
        tight = _with(ctx, settings={"sweep_max_runs": 2})

        report = run_rebenchmark(tight)

        assert report.considered > 2
        assert report.enqueued == 0, "cap-and-proceed is exactly what must not happen"
        assert report.skipped_budget == report.considered
        assert tight.queue.depth() == 0
        assert report.balances()

    def test_a_plan_over_the_run_cap_exits_non_zero(self, ctx) -> None:
        """The refusal must reach the CronJob's failure count, not just a log."""
        tight = _with(ctx, settings={"sweep_max_runs": 1})

        assert run_rebenchmark(tight).exit_code != 0

    def test_a_plan_over_the_sample_cap_enqueues_nothing(self, ctx) -> None:
        """Samples, not runs, are the unit that costs money.

        A run-count cap alone cannot bound spend: ten runs of two hundred samples
        and two hundred runs of ten samples cost the same.
        """
        tight = _with(ctx, settings={"sweep_max_samples": 3, "sweep_max_runs": 10_000})

        report = run_rebenchmark(tight)

        assert report.enqueued == 0
        assert report.skipped_budget == report.considered
        assert tight.queue.depth() == 0

    def test_no_row_is_written_when_the_budget_refuses(self, ctx) -> None:
        """Refusal means nothing happened -- not even a queued row.

        A row written before the refusal would be picked up by any later
        re-drive, turning a refusal into a delayed spend.
        """
        from ida_core.repositories import count_runs

        tight = _with(ctx, settings={"sweep_max_runs": 1})

        run_rebenchmark(tight)

        with session_scope(ctx.session_factory) as session:
            assert count_runs(session) == 0

    def test_the_refusal_names_the_variable_to_raise(self, ctx, caplog) -> None:
        """A knob nobody can find is not a knob.

        Mirrors `MissingBaseUrlError`, which names its env var for the same
        reason.
        """
        tight = _with(ctx, settings={"sweep_max_runs": 1})

        with caplog.at_level(logging.ERROR, logger="ida.sweep"):
            run_rebenchmark(tight)

        assert "IDA_SWEEP_MAX_RUNS" in caplog.text
        assert "REFUSED" in caplog.text

    def test_force_does_not_bypass_the_budget(self, ctx) -> None:
        """Forcing is a decision about staleness, not permission to spend freely."""
        forced_and_tight = _with(ctx, settings={"sweep_force": True, "sweep_max_runs": 1})

        report = run_rebenchmark(forced_and_tight)

        assert report.enqueued == 0
        assert report.skipped_budget > 0

    def test_a_plan_exactly_at_the_cap_is_allowed(self, ctx) -> None:
        """The cap is a ceiling, not a strict inequality; off-by-one here is spend."""
        exact = _with(ctx, settings={"sweep_max_runs": len(_scorable(ctx))})

        report = run_rebenchmark(exact)

        assert report.skipped_budget == 0
        assert report.enqueued == report.considered

    def test_enforce_budget_is_a_pure_check(self) -> None:
        plan = [Candidate("t", "m", "sha", sample_count=5)]
        loose = Settings(sweep_max_runs=1, sweep_max_samples=5)
        enforce_budget(plan, loose)  # does not raise

        with pytest.raises(BudgetExceeded, match="IDA_SWEEP_MAX_SAMPLES"):
            enforce_budget(plan, Settings(sweep_max_runs=1, sweep_max_samples=4))


# ------------------------------------------------------ partial failures ----


class TestPartialEnqueueFailure:
    """Half a sweep must never be reported as a whole one."""

    def test_a_queue_failure_midway_reports_what_actually_landed(self, ctx) -> None:
        exploding = _ExplodingQueue(ok_count=3)
        scoped = _with(ctx, queue=exploding)

        report = run_rebenchmark(scoped)

        assert report.enqueued == 3
        assert report.failed == report.considered - 3
        assert report.failed > 0
        assert report.balances()

    def test_a_queue_failure_midway_exits_non_zero(self, ctx) -> None:
        scoped = _with(ctx, queue=_ExplodingQueue(ok_count=1))

        assert run_rebenchmark(scoped).exit_code != 0

    def test_rows_are_written_before_any_message_is_pushed(self, ctx) -> None:
        """Rows first, exactly as `POST /runs` does it.

        The other order hands a runner a message for a row that does not exist.
        Asserted by the runs that DID land having rows.
        """
        from ida_core.repositories import count_runs

        scoped = _with(ctx, queue=_ExplodingQueue(ok_count=2))

        report = run_rebenchmark(scoped)

        with session_scope(ctx.session_factory) as session:
            assert count_runs(session) == report.considered

    def test_un_pushed_rows_are_closed_out_failed_not_left_queued(self, ctx) -> None:
        """A row saying `queued` when no message exists is simply FALSE.

        It is also the bug that made this the highest-severity finding on the
        first draft: a sweep reads its own `queued` rows back as "in flight", so
        leaving them there suppressed those pairs on every later night.
        """
        from ida_core.repositories import count_runs

        scoped = _with(ctx, queue=_ExplodingQueue(ok_count=2))

        report = run_rebenchmark(scoped)

        with session_scope(ctx.session_factory) as session:
            assert count_runs(session, status=RunStatus.QUEUED) == 2
            assert count_runs(session, status=RunStatus.FAILED) == report.considered - 2

    def test_the_closed_out_rows_carry_a_reason_naming_the_cause(self, ctx) -> None:
        from ida_core.repositories import list_runs

        scoped = _with(ctx, queue=_ExplodingQueue(ok_count=0))

        run_rebenchmark(scoped)

        with session_scope(ctx.session_factory) as session:
            errors = {row.error for row in list_runs(session, status=RunStatus.FAILED)}
        assert len(errors) == 1
        assert "no queue message was ever pushed" in errors.pop()

    def test_the_next_sweep_re_enqueues_the_pairs_that_never_landed(self, ctx) -> None:
        """THE regression test for the highest-severity finding.

        Reproduced before the fix: after one mid-sweep Redis blip, every pair that
        never landed was skipped as "already in flight" on every subsequent
        night, forever, with a green CronJob each time. Two nights are asserted
        because the first is where the fix acts and the second is where a wrong
        fix would loop.

        The counts are derived from the report rather than written down: the
        plan is one pair per scorable task, so hard-coding them would make this
        regression test fail the day someone authors a new verifiable family.
        """
        blip = _with(ctx, queue=_ExplodingQueue(ok_count=2))
        first = run_rebenchmark(blip)
        orphaned = first.considered - 2
        assert orphaned > 0
        assert first.failed == orphaned

        second = run_rebenchmark(ctx)

        assert second.enqueued == orphaned, "the orphaned pairs must come back"
        assert second.skipped_dedupe == 2, "the two that really landed stay skipped"
        assert second.exit_code == 0

        third = run_rebenchmark(ctx)
        assert third.enqueued == 0, "and then it settles"

    def test_a_database_failure_during_cleanup_does_not_mask_the_report(
        self, ctx, monkeypatch, caplog
    ) -> None:
        """The cleanup must never replace "N of M landed" with its own traceback."""
        monkeypatch.setattr(
            sweeps, "fail_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone"))
        )
        scoped = _with(ctx, queue=_ExplodingQueue(ok_count=1))

        with caplog.at_level(logging.ERROR, logger="ida.sweep"):
            report = run_rebenchmark(scoped)

        assert report.enqueued == 1
        assert report.failed == report.considered - 1
        assert report.exit_code != 0
        assert "could not close out" in caplog.text

    def test_the_failure_is_logged_with_the_landed_count(self, ctx, caplog) -> None:
        scoped = _with(ctx, queue=_ExplodingQueue(ok_count=2))

        with caplog.at_level(logging.ERROR, logger="ida.sweep"):
            run_rebenchmark(scoped)

        assert "queue push failed" in caplog.text


# --------------------------------------------------------- model sweep -----


class TestModelSweep:
    """The registry diff: measure models that have never been measured."""

    def test_a_model_with_no_runs_at_all_is_enqueued(self, ctx) -> None:
        report = run_model_sweep(ctx)

        assert report.enqueued == len(_scorable(ctx))
        assert {model for _task, model in _drain_pairs(ctx.queue)} == {"mock"}

    def test_a_model_that_already_has_a_measurement_is_left_to_rebenchmark(self, ctx) -> None:
        """Not "has every current task" -- that is the nightly's job.

        Conflating the two would make the cheap targeted sweep re-enqueue the
        whole suite every night.
        """
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
        )

        report = run_model_sweep(ctx)

        assert report.enqueued == 0
        assert report.considered == 0
        assert ctx.queue.depth() == 0
        assert any("no new models" in note for note in report.notes)

    def test_a_failed_run_does_not_count_as_having_measured_the_model(self, ctx) -> None:
        """A model whose only run errored is still unmeasured."""
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
            status=RunStatus.FAILED,
        )

        assert run_model_sweep(ctx).enqueued > 0

    def test_it_still_skips_pairs_another_sweep_left_in_flight(self, ctx) -> None:
        """The 02:00 rebenchmark queues; the 03:30 model-sweep must not re-queue."""
        run_rebenchmark(ctx)
        depth_after_nightly = ctx.queue.depth()

        report = run_model_sweep(ctx)

        assert report.enqueued == 0
        assert ctx.queue.depth() == depth_after_nightly

    def test_it_respects_the_budget_guard(self, ctx) -> None:
        tight = _with(ctx, settings={"sweep_max_runs": 1})

        report = run_model_sweep(tight)

        assert report.enqueued == 0
        assert report.skipped_budget > 0
        assert report.exit_code != 0


# ---------------------------------------------------- judge calibration ----


class TestJudgeCalibration:
    """The retroactive grading path: candidate selection, bounds, and spend.

    Selection is the load-bearing half. The sweep picks candidates in SQL and
    the grader decides what it will actually grade in Python, and when those
    disagree the failure is not a crash but a **standoff** -- nominated nightly,
    declined nightly, visible only as a bill. So these tests assert on which rows
    are chosen at least as hard as on what happens to them.
    """

    def _seed_ungraded(self, session_factory, count: int) -> str:
        run_id = new_run_id()
        with session_scope(session_factory) as session:
            create_run(
                session,
                RunRecord(
                    id=run_id,
                    status=RunStatus.SUCCEEDED,
                    task_id=SUBJECTIVE_TASK,
                    model_key="mock",
                    task_git_sha="c" * 40,
                    harness_version="0.1.0",
                    created_at=utcnow(),
                ),
            )
            insert_results(session, [_ungraded_result(run_id, i) for i in range(count)])
        return run_id

    def test_it_exits_zero_when_the_judge_is_unavailable(self, ctx) -> None:
        """A known-and-accepted gap is not tonight's failure.

        Failing the CronJob for it would paint a permanent red mark no operator
        action can clear -- and a permanently-red alarm is one nobody reads on
        the night it means something.
        """
        self._seed_ungraded(ctx.session_factory, 3)

        report = run_judge_calibration(ctx)

        assert report.exit_code == 0

    def test_it_reports_how_many_candidates_it_skipped(self, ctx) -> None:
        self._seed_ungraded(ctx.session_factory, 4)

        report = run_judge_calibration(ctx)

        assert report.considered == 4
        assert report.skipped_unavailable == 4
        assert report.enqueued == 0
        assert report.balances()

    def test_the_skip_is_logged_with_an_explicit_reason_and_count(
        self, ctx, caplog, tmp_path
    ) -> None:
        """CronJob logs are the operator surface; the backlog must be visible."""
        self._seed_ungraded(ctx.session_factory, 2)

        with caplog.at_level(logging.WARNING, logger="ida.sweep"):
            run_judge_calibration(_with(ctx, artifact_store=_store(tmp_path)))

        assert "no judge configured" in caplog.text
        assert "skipped 2 candidate(s)" in caplog.text

    def test_skipped_candidates_are_not_counted_as_deduped(self, ctx) -> None:
        """ "Already have this number" and "nothing can produce it" are opposites."""
        self._seed_ungraded(ctx.session_factory, 2)

        report = run_judge_calibration(ctx)

        assert report.skipped_dedupe == 0
        assert report.skipped_unavailable == 2

    def test_an_already_graded_sample_is_not_a_candidate(self, ctx) -> None:
        """The predicate the judge's own writes will fall out of.

        Without the `score_value IS NULL` half, every night would re-grade
        everything already graded, at full provider cost.
        """
        run_id = self._seed_ungraded(ctx.session_factory, 1)
        with session_scope(ctx.session_factory) as session:
            insert_results(session, [_graded_result(run_id)])

        assert run_judge_calibration(ctx).considered == 1

    def test_a_sample_whose_online_grading_failed_IS_a_candidate(self, ctx) -> None:
        """``scorable`` is not the predicate, and this is the direction that bit.

        Online grading failure writes ``scorable=True`` (the run must not report
        itself ``succeeded``), so the old ``scorable IS FALSE`` predicate never
        re-nominated it: a silent, permanent non-retry that arrived the moment
        the runner was wired to a judge. The completion is sound and only the
        grade is missing -- exactly what retroactive grading is for.
        """
        run_id = self._seed_ungraded(ctx.session_factory, 0)
        with session_scope(ctx.session_factory) as session:
            insert_results(session, [_ungraded_result(run_id, 99, scorable=True, judge_attempts=1)])

        assert run_judge_calibration(ctx).considered == 1

    def test_a_sample_with_no_completion_is_never_a_candidate(self, ctx) -> None:
        """The *ungradable* class: the model call died, so nothing exists to grade.

        It costs no judge money -- the grader skips it before calling -- but it
        can never succeed, so selecting it is doing nothing, forever.
        """
        run_id = self._seed_ungraded(ctx.session_factory, 0)
        with session_scope(ctx.session_factory) as session:
            insert_results(session, [_ungraded_result(run_id, 99, transcript_uri=None)])

        assert run_judge_calibration(ctx).considered == 0

    def test_a_sample_past_the_attempt_bound_is_no_longer_a_candidate(self, ctx) -> None:
        """The money pump's off switch, at the sweep level."""
        run_id = self._seed_ungraded(ctx.session_factory, 0)
        with session_scope(ctx.session_factory) as session:
            insert_results(session, [_ungraded_result(run_id, 99, judge_attempts=3)])

        bounded = _with(ctx, settings={"sweep_judge_max_attempts": 3})
        assert run_judge_calibration(bounded).considered == 0

        reopened = _with(ctx, settings={"sweep_judge_max_attempts": 4})
        assert run_judge_calibration(reopened).considered == 1

    def test_a_row_from_a_task_with_no_rubric_is_not_counted_as_backlog(self, ctx) -> None:
        """SQL cannot see task kind, so the catalog filter has to.

        ``results`` stores ``task_id``, not kind. A verifiable task's row that
        somehow carries no score would otherwise be nominated every night and
        inflate the reported backlog forever, while the grader declined it every
        night for having no rubric.
        """
        run_id = self._seed_ungraded(ctx.session_factory, 0)
        with session_scope(ctx.session_factory) as session:
            insert_results(session, [_ungraded_result(run_id, 99, task_id=VERIFIABLE_TASK)])

        report = run_judge_calibration(ctx)

        assert report.considered == 0
        assert any("not judgeable" in note for note in report.notes)
        assert report.balances()

    def test_nothing_to_grade_is_a_quiet_success(self, ctx) -> None:
        report = run_judge_calibration(ctx)

        assert report.considered == 0
        assert report.exit_code == 0

    def test_hitting_the_candidate_bound_is_said_out_loud(self, ctx) -> None:
        """A truncated pass must never read as "that was all"."""
        self._seed_ungraded(ctx.session_factory, 5)
        bounded = _with(ctx, settings={"sweep_judge_candidate_limit": 3})

        report = run_judge_calibration(bounded)

        assert report.considered == 3
        assert any("more candidates remain" in note for note in report.notes)

    def test_no_judge_configured_is_still_a_quiet_success(self, ctx, tmp_path) -> None:
        """Judging is opt-in, so "off" is a configuration state, not tonight's failure.

        Distinct from a judge that IS configured and failing, which does go red:
        that one an operator can fix, and a permanently-red alarm for a gap
        nobody can clear is one nobody reads on the night it means something.
        """
        self._seed_ungraded(ctx.session_factory, 2)

        report = run_judge_calibration(_with(ctx, artifact_store=_store(tmp_path)))

        assert report.exit_code == 0
        assert report.graded == 0
        assert report.skipped_unavailable == 2
        assert any("no judge configured" in note for note in report.notes)
        assert report.balances()


class TestRetroactiveGradingEndToEnd:
    """A real ungraded run, graded by a real sweep, asserted on the real table.

    Everything here is genuine except the provider: a subjective run is executed
    through the runner's own ``execute_job`` with no judge (the state every
    subjective run has been in), its completions and eval log are archived to a
    real local artifact store, and then the nightly sweep grades it. The judge is
    the mock-model service answering in process, so the judge protocol is
    exercised for real at zero cost.

    ⚠ THE ASSERTIONS ARE ON POSTGRES-SHAPED ROWS, NOT ON THE EVAL LOG. Archiving
    a grade and persisting it are two different writes, and for as long as only
    the first existed a regrade updated object storage while the UI kept showing
    the original blank -- and ``judge_attempts`` never moved, so the bound that
    stops a nightly re-bill could never engage.
    """

    def _ungraded_run(self, ctx, store, *, judge_mode: str = "json"):
        """Execute a subjective run with NO judge, archiving everything."""
        from _runner_helpers import job_message, seed_run

        from ida_mock_model.app import create_app
        from ida_mock_model.testing import make_transport
        from ida_runner.worker import execute_job

        app = create_app()
        app.state.mock.responder.judge_mode = judge_mode
        transport = make_transport(app)

        def client_factory():
            from ida_harness.client import OpenAICompatibleClient

            return OpenAICompatibleClient(
                ctx.registry.get("mock"),
                transport=transport,
                sleep=lambda _s: None,
                jitter=lambda _lo, hi: hi,
            )

        run_id = seed_run(ctx.session_factory, task_id=SUBJECTIVE_TASK)
        execute_job(
            job_message(run_id, task_id=SUBJECTIVE_TASK),
            session_factory=ctx.session_factory,
            registry=ctx.registry,
            catalog=ctx.catalog,
            artifact_store=store,
            client_factory=client_factory,
        )
        return run_id

    def _rows(self, ctx, run_id):
        from ida_core.repositories import list_results_for_run, result_row_to_record

        with session_scope(ctx.session_factory) as session:
            return [result_row_to_record(r) for r in list_results_for_run(session, run_id)]

    def _judging_ctx(self, ctx, store, monkeypatch, *, judge_mode: str = "json", **settings):
        """A context with object storage and the mock judge configured.

        ⚠ THE TRANSPORT HAS TO BE INJECTED, AND ``monkeypatch`` IS WHY THIS TAKES
        A FIXTURE. ``build_judge_from_settings`` builds the judge's client
        through the ordinary factory, which resolves the ``mock`` entry's
        ``base_url`` -- ``http://mock-model:8000/v1``, a real socket that does
        not exist in a unit test. Substituting the constructor is the only seam;
        the judge, the client and the service answering it are all the real ones.

        Via ``monkeypatch`` rather than a bare assignment so the patch is undone
        at teardown. An earlier draft assigned the module attribute directly and
        the ``malformed`` judge leaked into every test that ran after it -- which
        is exactly the kind of order-dependent green a suite must not have.
        """
        import ida_runner.sweeps as sweeps_mod
        from ida_harness.client import OpenAICompatibleClient
        from ida_harness.judge import LLMJudge
        from ida_mock_model.app import create_app
        from ida_mock_model.testing import make_transport

        base = {"judge_model_key": "mock"}
        base.update(settings)
        judging = _with(ctx, artifact_store=store, settings=base)

        app = create_app()
        app.state.mock.responder.judge_mode = judge_mode
        transport = make_transport(app)
        entry = ctx.registry.get("mock")

        def _build(settings_arg, registry_arg):
            # Honour the real "off by default" policy even here: an empty key
            # must still mean no judge, or the test would prove nothing about
            # the unconfigured path.
            if not settings_arg.judge_model_key:
                return None
            return LLMJudge(
                entry=entry,
                client=OpenAICompatibleClient(
                    entry,
                    transport=transport,
                    sleep=lambda _s: None,
                    jitter=lambda _lo, hi: hi,
                ),
                owns_client=True,
            )

        monkeypatch.setattr(sweeps_mod, "build_judge_from_settings", _build)
        return judging

    def test_it_grades_an_ungraded_run_and_persists_the_grades(
        self, ctx, tmp_path, monkeypatch
    ) -> None:
        store = _store(tmp_path)
        run_id = self._ungraded_run(ctx, store)
        assert all(r.score is None for r in self._rows(ctx, run_id)), "precondition: ungraded"

        report = run_judge_calibration(self._judging_ctx(ctx, store, monkeypatch))

        assert report.considered == 2
        assert report.graded == 2
        assert report.failed == 0
        assert report.exit_code == 0
        assert report.balances()

        rows = self._rows(ctx, run_id)
        assert all(r.score is not None for r in rows), "grades must reach the TABLE, not just S3"
        assert all(r.scorable for r in rows)
        assert all(r.judge_serving_config is not None for r in rows)
        assert all(r.score.criteria for r in rows), "the per-criterion breakdown is the evidence"

    def test_grading_counts_an_attempt_on_every_row_it_touched(
        self, ctx, tmp_path, monkeypatch
    ) -> None:
        store = _store(tmp_path)
        run_id = self._ungraded_run(ctx, store)

        run_judge_calibration(self._judging_ctx(ctx, store, monkeypatch))

        assert [r.judge_attempts for r in self._rows(ctx, run_id)] == [1, 1]

    def test_a_graded_run_is_not_re_graded_on_the_next_firing(
        self, ctx, tmp_path, monkeypatch
    ) -> None:
        """Without this, every night re-grades all of history at full cost."""
        store = _store(tmp_path)
        self._ungraded_run(ctx, store)

        first = run_judge_calibration(self._judging_ctx(ctx, store, monkeypatch))
        second = run_judge_calibration(self._judging_ctx(ctx, store, monkeypatch))

        assert first.graded == 2
        assert second.considered == 0
        assert second.graded == 0
        assert second.judge_cost_usd == 0.0

    def test_a_failing_judge_converges_instead_of_billing_forever(
        self, ctx, tmp_path, monkeypatch
    ) -> None:
        """THE MONEY PUMP, AND ITS OFF SWITCH.

        A judge that answers unparseable prose fails the same samples every
        night. The *judge failed* class is retryable by design -- that is what
        stops an outage making a sample permanently ungradable -- so without a
        bound the sweep re-nominates, re-fails and re-bills forever, and the
        only symptom is the invoice.

        Three firings against a permanently-broken judge: attempts climb to the
        bound and nomination then stops. The fourth night costs nothing.
        """
        store = _store(tmp_path)
        run_id = self._ungraded_run(ctx, store)

        considered = []
        for _ in range(4):
            report = run_judge_calibration(
                self._judging_ctx(
                    ctx, store, monkeypatch, judge_mode="malformed", sweep_judge_max_attempts=3
                )
            )
            considered.append(report.considered)

        assert considered == [2, 2, 2, 0], (
            "three attempts per sample, then the bound stops nomination"
        )
        assert [r.judge_attempts for r in self._rows(ctx, run_id)] == [3, 3]
        assert all(r.score is None for r in self._rows(ctx, run_id)), "no grade was fabricated"

    def test_a_failing_judge_makes_the_cronjob_go_red(self, ctx, tmp_path, monkeypatch) -> None:
        """A configured judge that cannot grade is a fixable fault; say so.

        Distinct from "no judge configured", which exits 0 -- an operator can
        clear this one, so it earns the alarm.
        """
        store = _store(tmp_path)
        self._ungraded_run(ctx, store)

        report = run_judge_calibration(
            self._judging_ctx(ctx, store, monkeypatch, judge_mode="malformed")
        )

        assert report.failed == 2
        assert report.graded == 0
        assert report.exit_code != 0
        assert report.balances()

    def test_a_sample_past_its_bound_is_not_regraded_by_a_run_level_call(
        self, ctx, tmp_path, monkeypatch
    ) -> None:
        """The per-RESULT bound must survive being handed to a per-RUN grader.

        ``regrade_run`` grades a whole run from one eval log. Within a single run
        some samples can be freshly nominated while others have exhausted their
        attempts -- so a bare per-run call would silently re-grade the exhausted
        ones, widening the bound back open and re-billing exactly the samples it
        exists to protect. ``only_result_ids`` is what keeps them apart.

        Here one of the run's two samples is pushed past the bound directly; the
        firing must touch the other one only.
        """
        from ida_core.db import ResultRow

        store = _store(tmp_path)
        run_id = self._ungraded_run(ctx, store)
        rows = self._rows(ctx, run_id)
        exhausted_id, spared_id = rows[0].id, rows[1].id

        with session_scope(ctx.session_factory) as session:
            session.get(ResultRow, exhausted_id).judge_attempts = 3

        report = run_judge_calibration(
            self._judging_ctx(ctx, store, monkeypatch, sweep_judge_max_attempts=3)
        )

        assert report.considered == 1, "only the un-exhausted sample is a candidate"
        assert report.graded == 1

        by_id = {r.id: r for r in self._rows(ctx, run_id)}
        assert by_id[spared_id].score is not None
        assert by_id[exhausted_id].score is None, "the exhausted sample must be left alone"
        assert by_id[exhausted_id].judge_attempts == 3, "and must not be charged another attempt"

    def test_a_failed_write_back_is_reported_and_does_not_double_count(
        self, ctx, tmp_path, monkeypatch
    ) -> None:
        """Grades archived but not persisted is a DIVERGENCE, and must go red.

        Object storage and Postgres disagreeing about a run is the state nobody
        discovers until the numbers are needed, so it cannot be a quiet success.

        The arithmetic is the other half of this test. An earlier draft added the
        graded rows to ``failed`` while leaving them in ``graded``, counting them
        twice: the sweep exited red, which looked right, on a summary line whose
        buckets no longer added up to ``considered``. ``balances()`` is what makes
        that visible rather than plausible.
        """
        import ida_runner.sweeps as sweeps_mod

        store = _store(tmp_path)
        self._ungraded_run(ctx, store)

        def _boom(_session, _records):
            raise RuntimeError("postgres is down")

        monkeypatch.setattr(sweeps_mod, "persist_regraded_results", _boom)

        report = run_judge_calibration(self._judging_ctx(ctx, store, monkeypatch))

        assert report.considered == 2
        assert report.graded == 0, "nothing reached the table, so nothing is graded"
        assert report.failed == 2
        assert report.exit_code != 0
        assert report.balances(), "every considered candidate lands in exactly one bucket"
        assert any("not persisted" in note for note in report.notes)

    def test_a_failed_write_back_after_a_failed_GRADE_still_balances(
        self, ctx, tmp_path, monkeypatch
    ) -> None:
        """The case that actually discriminates the two arithmetics.

        When the write-back fails after every grade ALSO failed, the buggy
        ``failed += graded + failed`` counts the judge failures a second time --
        ``failed`` reaches 4 for 2 candidates -- while the correct
        ``failed += graded`` (with ``graded`` at 0) leaves it at 2. The
        all-succeeded case cannot tell them apart, because ``failed`` is 0 there
        and both formulas agree; this one is why ``balances()`` is asserted
        rather than the buckets being eyeballed.

        ⚠ It also names a real consequence: the ``judge_attempts`` increments
        were in that failed write-back too, so these samples are retried on the
        next firing rather than converging. The bound counts *persisted*
        attempts, and an unpersisted one never happened as far as it is concerned.
        """
        import ida_runner.sweeps as sweeps_mod

        store = _store(tmp_path)
        run_id = self._ungraded_run(ctx, store)

        def _boom(_session, _records):
            raise RuntimeError("postgres is down")

        monkeypatch.setattr(sweeps_mod, "persist_regraded_results", _boom)

        report = run_judge_calibration(
            self._judging_ctx(ctx, store, monkeypatch, judge_mode="malformed")
        )

        assert report.considered == 2
        assert report.graded == 0
        assert report.failed == 2, "two judge failures, counted once"
        assert report.balances()
        assert [r.judge_attempts for r in self._rows(ctx, run_id)] == [0, 0], (
            "the increments were in the write-back that failed"
        )

    def test_a_dry_run_writes_nothing_and_counts_no_attempt(
        self, ctx, tmp_path, monkeypatch
    ) -> None:
        """It answers "what would change", not "what would this cost" -- it still spends."""
        store = _store(tmp_path)
        run_id = self._ungraded_run(ctx, store)

        report = run_judge_calibration(self._judging_ctx(ctx, store, monkeypatch), dry_run=True)

        assert report.planned == 2
        assert report.graded == 0
        assert report.balances()
        assert any("billed" in note for note in report.notes), (
            "a dry run that silently spends is the expensive surprise"
        )

        rows = self._rows(ctx, run_id)
        assert all(r.score is None for r in rows)
        assert all(r.judge_attempts == 0 for r in rows)


# --------------------------------------------------------------- report ----


class TestSummaryLine:
    """One line per firing.  It is the whole operator surface for a CronJob."""

    def test_it_carries_every_counter(self) -> None:
        line = SweepReport(
            sweep="rebenchmark",
            considered=10,
            enqueued=7,
            skipped_dedupe=2,
            skipped_budget=0,
            skipped_unavailable=0,
            failed=1,
            samples_enqueued=42,
        ).summary()

        for fragment in (
            "sweep=rebenchmark",
            "considered=10",
            "enqueued=7",
            "skipped_dedupe=2",
            "skipped_budget=0",
            "skipped_unavailable=0",
            "failed=1",
            "samples=42",
        ):
            assert fragment in line

    def test_a_clean_sweep_exits_zero(self) -> None:
        assert SweepReport(sweep="x", considered=3, enqueued=3).exit_code == 0

    def test_the_summary_is_logged_once_on_success(self, ctx, caplog, monkeypatch) -> None:
        monkeypatch.setattr(sweeps, "build_context", lambda _settings=None, **_kw: ctx)

        with caplog.at_level(logging.INFO, logger="ida.sweep"):
            assert main(["rebenchmark"]) == 0

        assert len([r for r in caplog.records if "considered=" in r.message]) == 1


# ------------------------------------------------------------ entrypoint ----


class TestEntrypoint:
    def test_an_unknown_sweep_name_exits_non_zero(self) -> None:
        """The scaffold's contract, preserved.

        The chart hardcodes three argv values; a typo'd fourth must fail loudly
        rather than no-op its way to a green CronJob.
        """
        with pytest.raises(SystemExit) as excinfo:
            main(["not-a-sweep"])

        assert excinfo.value.code != 0

    @pytest.mark.parametrize("name", ["rebenchmark", "model-sweep", "judge-calibration"])
    def test_every_name_the_chart_fires_is_dispatchable(self, name, ctx, monkeypatch) -> None:
        """`.devops/chart/base/cronjobs.yaml` hardcodes these three.

        Renaming one here without the chart -- which this story does not own --
        would leave a CronJob failing every night on a usage message.
        """
        monkeypatch.setattr(sweeps, "build_context", lambda _settings=None, **_kw: ctx)

        assert main([name, "--dry-run"]) == 0

    def test_dry_run_changes_nothing(self, ctx, monkeypatch) -> None:
        from ida_core.repositories import count_runs

        monkeypatch.setattr(sweeps, "build_context", lambda _settings=None, **_kw: ctx)

        assert main(["rebenchmark", "--dry-run"]) == 0

        assert ctx.queue.depth() == 0
        with session_scope(ctx.session_factory) as session:
            assert count_runs(session) == 0

    def test_a_budget_refusal_propagates_to_the_process_exit_code(self, ctx, monkeypatch) -> None:
        tight = _with(ctx, settings={"sweep_max_runs": 1})
        monkeypatch.setattr(sweeps, "build_context", lambda _settings=None, **_kw: tight)

        assert main(["rebenchmark"]) != 0

    def test_the_force_flag_beats_the_environment(self, ctx, monkeypatch) -> None:
        """A human typing --force outranks a variable somebody set last month."""
        run_rebenchmark(ctx)
        seen: list[bool] = []

        def _capture(settings=None, **_kw):
            seen.append(settings.sweep_force)
            return _with(ctx, settings={"sweep_force": settings.sweep_force})

        monkeypatch.setattr(sweeps, "build_context", _capture)
        monkeypatch.setenv("IDA_SWEEP_FORCE", "0")

        main(["rebenchmark", "--force", "--dry-run"])

        assert seen == [True]

    def test_a_crashing_sweep_exits_non_zero_rather_than_raising(self, monkeypatch, caplog) -> None:
        """A sweep that dies must LOOK dead, in the operator's log format."""

        def _boom(_settings=None, **_kw):
            raise RuntimeError("postgres is unreachable")

        monkeypatch.setattr(sweeps, "build_context", _boom)

        with caplog.at_level(logging.ERROR, logger="ida.sweep"):
            assert main(["rebenchmark"]) == 1

        assert "postgres is unreachable" in caplog.text


# ---------------------------------------------------------- happy path -----


class TestRebenchmarkHappyPath:
    def test_it_enqueues_the_full_cross_product_on_a_cold_database(self, ctx) -> None:
        report = run_rebenchmark(ctx)

        # SWEEPABLE, not merely enabled: `luna` is enabled so an operator can
        # select it deliberately, and held back from scheduled sweeps by its
        # `testing-only` tag because its key carries a $25 cap. See
        # `sweepable_model_keys` and TestScheduledSweepsRespectExcludeTags.
        sweepable = sweeps.sweepable_model_keys(
            ctx.registry, ctx.settings, report=SweepReport(sweep="probe")
        )
        expected = len(_scorable(ctx)) * len(sweepable)
        assert report.considered == expected
        assert report.enqueued == expected
        assert ctx.queue.depth() == expected
        assert report.exit_code == 0

    def test_it_never_enqueues_a_subjective_task(self, ctx) -> None:
        run_rebenchmark(ctx)

        assert SUBJECTIVE_TASK not in {task for task, _model in _drain_pairs(ctx.queue)}

    def test_every_enqueued_run_gets_a_persisted_queued_row(self, ctx) -> None:
        """A message whose row does not exist is a 500 in the runner."""
        run_rebenchmark(ctx)

        with session_scope(ctx.session_factory) as session:
            while (message := ctx.queue.dequeue(timeout_s=0)) is not None:
                row = get_run(session, message.run_id)
                assert row is not None, message.run_id
                assert row.status == RunStatus.QUEUED.value

    def test_the_whole_firing_shares_one_sweep_id(self, ctx) -> None:
        """B9: "what did last night's rebenchmark do" must be a filter, not a guess."""
        report = run_rebenchmark(ctx)

        sweep_ids = set()
        while (message := ctx.queue.dequeue(timeout_s=0)) is not None:
            sweep_ids.add(message.sweep_id)
        assert sweep_ids == {report.sweep_id}
        assert report.sweep_id is not None

    def test_rows_record_the_provenance_dedupe_depends_on(self, ctx) -> None:
        """content_sha on the row IS the dedupe key; an unset one breaks the sweep."""
        run_rebenchmark(ctx)
        by_id = {spec.id: spec for spec in _scorable(ctx)}

        with session_scope(ctx.session_factory) as session:
            while (message := ctx.queue.dequeue(timeout_s=0)) is not None:
                row = get_run(session, message.run_id)
                assert row.task_content_sha == by_id[row.task_id].content_sha
                assert row.task_git_sha == "a" * 40
                assert row.sample_count == len(by_id[row.task_id].samples)

    def test_runs_are_labelled_with_the_sweep_that_made_them(self, ctx) -> None:
        run_rebenchmark(ctx)

        with session_scope(ctx.session_factory) as session:
            message = ctx.queue.dequeue(timeout_s=0)
            assert get_run(session, message.run_id).label == "sweep:rebenchmark"

    def test_the_sample_counter_matches_what_was_enqueued(self, ctx) -> None:
        """The number the budget guard reasons about must be the number it spent."""
        report = run_rebenchmark(ctx)

        assert report.samples_enqueued == sum(len(spec.samples) for spec in _scorable(ctx))


# --------------------------------------------------------------- helpers ----


def _drain_pairs(queue) -> set[tuple[str, str]]:
    """Every `(task_id, model_key)` sitting on the queue, consuming it."""
    pairs = set()
    while (message := queue.dequeue(timeout_s=0)) is not None:
        pairs.add((message.task_id, message.model_key))
    return pairs


def _serving_config():
    from ida_core.contracts import ServingConfig, ServingStack

    return ServingConfig(model_id="mock-1", serving_stack=ServingStack.OPENAI_API)


def _ungraded_result(
    run_id: str,
    index: int,
    *,
    scorable: bool = False,
    judge_attempts: int = 0,
    transcript_uri: str | None = "s3://ida-artifacts/x.json",
    task_id: str = SUBJECTIVE_TASK,
):
    """A subjective sample carrying no score.

    ``transcript_uri`` defaults to a real-looking URI because that is what a
    completed sample HAS: the candidate answered, the answer was archived, and
    only the grade is missing. A row without one is the *ungradable* class -- the
    model call died -- and is never a candidate; pass ``transcript_uri=None`` to
    build that state deliberately.
    """
    from ida_core.contracts import ResultRecord

    return ResultRecord(
        id=f"res_ungraded_{run_id}_{index}",
        run_id=run_id,
        task_id=task_id,
        sample_id=f"s{index}",
        model_key="mock",
        serving_config=_serving_config(),
        score=None,
        scorable=scorable,
        judge_attempts=judge_attempts,
        transcript_uri=transcript_uri,
        created_at=utcnow(),
    )


def _graded_result(run_id: str):
    from ida_core.contracts import ResultRecord, Score, ScorerKind

    return ResultRecord(
        id=f"res_graded_{run_id}",
        run_id=run_id,
        task_id=SUBJECTIVE_TASK,
        sample_id="already-graded",
        model_key="mock",
        serving_config=_serving_config(),
        score=Score(scorer=ScorerKind.LLM_JUDGE, value=0.8, passed=True, explanation="ok"),
        scorable=False,
        transcript_uri="s3://ida-artifacts/x.json",
        created_at=utcnow(),
    )


class TestTheChartAndTheEntrypointAgree:
    """Drive the ACTUAL CronJob manifests against the dispatch table.

    Same shape, same reasoning, as `TestTheRealConfigMapIsUsable` in
    packages/core: the chart is a contract this code cannot see at import time,
    and a mismatch is SILENT until 02:00 in a cluster. `ida-sweep <name>` with an
    unknown name exits 2 on a usage message, so a rename here and not there gives
    three CronJobs that fail every night -- and the pod log says only "invalid
    choice", pointing nowhere near the file that caused it.

    This story does not own `.devops`, so the manifests are ground truth and this
    test is the direction of the coupling made explicit. Read-only.
    """

    @staticmethod
    def _cronjob_commands() -> list[list[str]]:
        import yaml

        path = REPO_ROOT / ".devops" / "chart" / "base" / "cronjobs.yaml"
        assert path.is_file(), f"the deploy contract moved: {path}"
        commands = []
        for document in yaml.safe_load_all(path.read_text()):
            if not document or document.get("kind") != "CronJob":
                continue
            containers = document["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
            commands.extend(c["command"] for c in containers if "command" in c)
        return commands

    def test_the_chart_still_fires_three_sweeps(self) -> None:
        assert len(self._cronjob_commands()) == 3

    def test_every_argv_the_chart_fires_is_a_name_this_module_accepts(self) -> None:
        for command in self._cronjob_commands():
            assert command[0] == "ida-sweep", command
            assert command[1] in sweeps.SWEEPS, (
                f"the chart fires `{' '.join(command)}` but ida-sweep does not know "
                f"{command[1]!r}; it would exit 2 on a usage message every night"
            )

    def test_every_name_this_module_accepts_has_a_handler(self) -> None:
        """An argparse choice with no handler is a KeyError at 02:00."""
        assert set(sweeps.SWEEPS) == set(sweeps.HANDLERS)


class TestDryRunAccounting:
    """A preview must be legible as a preview, not as a sweep that lost its work."""

    def test_a_dry_run_reports_what_it_would_have_enqueued(self, ctx) -> None:
        report = run_rebenchmark(ctx, dry_run=True)

        assert report.considered > 0
        assert report.enqueued == 0
        assert report.planned == report.considered
        assert ctx.queue.depth() == 0

    def test_a_dry_run_still_balances(self, ctx) -> None:
        """The invariant is TOTAL -- no "except in dry-run" caveat.

        Without the `planned` bucket a dry run would report `enqueued=0` with
        nothing accounting for the plan, which reads exactly like a sweep that
        silently dropped every candidate.
        """
        assert run_rebenchmark(ctx, dry_run=True).balances()

    def test_a_dry_run_after_dedupe_reports_only_the_remainder(self, ctx) -> None:
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
        )

        report = run_rebenchmark(ctx, dry_run=True)

        assert report.skipped_dedupe == 1
        assert report.planned == report.considered - 1
        assert report.balances()

    def test_a_dry_run_exits_zero(self, ctx) -> None:
        assert run_rebenchmark(ctx, dry_run=True).exit_code == 0

    def test_the_summary_line_shows_the_planned_count(self, ctx) -> None:
        report = run_rebenchmark(ctx, dry_run=True)

        assert f"planned={report.considered}" in report.summary()


class TestTheDedupeRuleIsWhatTheDocstringSays:
    """Pins the PRECISE rule, because an earlier docstring stated a different one.

    The draft claimed dedupe re-ran "a pair whose LAST run failed". The code
    implements "a pair with NO succeeded run at this content sha" -- which is the
    right rule, but the two differ exactly when a success is followed by a
    failure, and nothing covered that case.
    """

    def test_a_success_followed_by_a_failure_is_still_skipped(self, ctx) -> None:
        """A valid measurement of this task version exists; re-buying it teaches nothing."""
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
            status=RunStatus.SUCCEEDED,
        )
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
            status=RunStatus.FAILED,
        )

        report = run_rebenchmark(ctx)

        assert report.skipped_dedupe == 1
        assert (spec.id, "mock") not in _drain_pairs(ctx.queue)

    def test_a_success_at_an_older_sha_does_not_cover_the_current_one(self, ctx) -> None:
        """Content sha, not the clock, is what expires a measurement."""
        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha="an-older-edition",
            status=RunStatus.SUCCEEDED,
        )

        assert (spec.id, "mock") in _drain_pairs_after(run_rebenchmark, ctx)


class TestAbandonedQueuedRowsExpire:
    """ "In flight" is a claim about right now, and it has to expire.

    The exception path is closed out explicitly (see TestPartialEnqueueFailure),
    but a sweep SIGKILLed between committing rows and pushing messages runs no
    handler at all. Without an age bound those rows would suppress their pairs
    forever -- the same permanent-invisibility failure, reached a different way.
    """

    def _orphan(self, ctx, *, age_s: int) -> str:
        from datetime import timedelta

        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
            status=RunStatus.QUEUED,
            created_at=utcnow() - timedelta(seconds=age_s),
        )
        return spec.id

    def test_a_recent_queued_row_still_counts_as_in_flight(self, ctx) -> None:
        task_id = self._orphan(ctx, age_s=60)

        report = run_rebenchmark(ctx)

        assert report.skipped_dedupe == 1
        assert (task_id, "mock") not in _drain_pairs(ctx.queue)

    def test_a_queued_row_older_than_the_stale_ttl_is_re_planned(self, ctx) -> None:
        task_id = self._orphan(ctx, age_s=ctx.settings.stale_run_ttl_s + 60)

        report = run_rebenchmark(ctx)

        assert report.skipped_dedupe == 0
        assert (task_id, "mock") in _drain_pairs(ctx.queue)

    def test_an_old_SUCCEEDED_row_never_expires(self, ctx) -> None:
        """Only the in-flight half is time-bounded.

        A measurement is timeless -- ageing one out would re-buy every number in
        the database on a schedule, which is the most expensive possible bug here.
        """
        from datetime import timedelta

        spec = _scorable(ctx)[0]
        _seed_terminal_run(
            ctx.session_factory,
            task_id=spec.id,
            model_key="mock",
            content_sha=spec.content_sha,
            status=RunStatus.SUCCEEDED,
            created_at=utcnow() - timedelta(days=3650),
        )

        assert run_rebenchmark(ctx).skipped_dedupe == 1


class TestTheTruncationNoteIsNeverAFalseStatement:
    """`len(rows) == limit` cannot tell a full backlog from an exact fit."""

    def _seed(self, ctx, count: int) -> None:
        run_id = new_run_id()
        with session_scope(ctx.session_factory) as session:
            create_run(
                session,
                RunRecord(
                    id=run_id,
                    status=RunStatus.SUCCEEDED,
                    task_id=SUBJECTIVE_TASK,
                    model_key="mock",
                    task_git_sha="c" * 40,
                    harness_version="0.1.0",
                    created_at=utcnow(),
                ),
            )
            insert_results(session, [_ungraded_result(run_id, i) for i in range(count)])

    def test_exactly_limit_candidates_does_not_claim_more_remain(self, ctx) -> None:
        """The off-by-one that would put a lie on the operator's only surface."""
        self._seed(ctx, 3)
        bounded = _with(ctx, settings={"sweep_judge_candidate_limit": 3})

        report = run_judge_calibration(bounded)

        assert report.considered == 3
        assert not any("more candidates remain" in note for note in report.notes)

    def test_one_more_than_the_limit_does_claim_more_remain(self, ctx) -> None:
        self._seed(ctx, 4)
        bounded = _with(ctx, settings={"sweep_judge_candidate_limit": 3})

        report = run_judge_calibration(bounded)

        assert report.considered == 3
        assert any("more candidates remain" in note for note in report.notes)

    def test_the_extra_probe_row_is_never_counted_as_a_candidate(self, ctx) -> None:
        """limit + 1 is fetched; limit is reported. Reporting limit+1 would
        overstate the backlog and, once the judge lands, over-grade it."""
        self._seed(ctx, 10)
        bounded = _with(ctx, settings={"sweep_judge_candidate_limit": 4})

        report = run_judge_calibration(bounded)

        assert report.considered == 4
        assert report.skipped_unavailable == 4
        assert report.balances()


def _drain_pairs_after(sweep, ctx) -> set[tuple[str, str]]:
    sweep(ctx)
    return _drain_pairs(ctx.queue)


class TestObjectStoreIsOptional:
    """The enqueueing sweeps must not depend on MinIO.

    They write rows and push messages and touch no blobs. Building an object
    store client for them anyway would turn an unrelated MinIO outage into a
    failed nightly benchmark -- an availability coupling with nothing behind it.
    """

    def test_only_judge_calibration_asks_for_object_storage(self) -> None:
        assert set(sweeps.NEEDS_ARTIFACTS) == {"judge-calibration"}
        assert not set(sweeps.NEEDS_ARTIFACTS) - set(sweeps.SWEEPS), (
            "an entry for a sweep that no longer exists"
        )

    def test_the_enqueueing_sweeps_run_with_no_store_at_all(self, ctx) -> None:
        assert ctx.artifact_store is None

        assert run_rebenchmark(ctx).exit_code == 0
        assert run_model_sweep(ctx).exit_code == 0

    def test_build_context_does_not_construct_a_store_unless_asked(self, monkeypatch) -> None:
        """Asserted at the constructor, because "we never call it" is not the same
        as "we never build it" -- an S3 client is built eagerly."""
        built: list[bool] = []
        monkeypatch.setattr(
            sweeps, "build_artifact_store", lambda _s: built.append(True) or object()
        )
        monkeypatch.setattr(sweeps, "make_engine", lambda _url: None)
        monkeypatch.setattr(sweeps, "make_session_factory", lambda _e: None)
        monkeypatch.setattr(
            sweeps, "RedisQueue", type("Q", (), {"from_url": staticmethod(lambda *a, **k: None)})
        )

        sweeps.build_context(Settings(), need_artifacts=False)
        assert built == []

        sweeps.build_context(Settings(), need_artifacts=True)
        assert built == [True]


# ------------------------------------------------------------ provenance ----


class TestEnqueuedRowsCarryTheBuildIdentity:
    """A sweep's rows must name the build that will execute them (D-1).

    THE BUG THIS CLOSES. ``harness_version`` was ``ida_harness.__version__``, a
    hardcoded ``"0.1.0"`` no release step has ever written to -- so every row the
    nightly CronJobs have ever written claims a version that identifies nothing.
    The sweeps are the biggest single writer of run rows in the platform, which
    makes them the biggest single source of that false provenance.

    ⚠ The worker later OVERWRITES this field with the harness's own answer
    (``worker.py``: ``eval_log.harness_version or build_identity()``). Both sides
    call the same resolver, so they agree -- but the enqueue value is what a row
    carries for as long as it sits ``queued``, and "wrong until something fixes
    it" is not a standard worth keeping.
    """

    def _enqueued_rows(self, ctx):
        report = run_rebenchmark(ctx)
        assert report.enqueued > 0, "nothing enqueued -- the assertion below would be vacuous"
        run_ids = []
        while (message := ctx.queue.dequeue(timeout_s=0)) is not None:
            run_ids.append(message.run_id)
        with session_scope(ctx.session_factory) as session:
            return [get_run(session, run_id) for run_id in run_ids]

    def test_the_rows_carry_the_build_sha(self, ctx, monkeypatch) -> None:
        monkeypatch.setenv("IDA_GIT_SHA", "9" * 40)
        rows = self._enqueued_rows(ctx)
        assert {r.harness_version for r in rows} == {"9" * 40}

    def test_the_rows_never_carry_the_old_hardcoded_constant(
        self, ctx, monkeypatch, tmp_path
    ) -> None:
        """Outside a build the answer is ``"unknown"`` -- honest, not invented."""
        monkeypatch.delenv("IDA_GIT_SHA", raising=False)
        monkeypatch.chdir(tmp_path)
        rows = self._enqueued_rows(ctx)
        assert {r.harness_version for r in rows} == {"unknown"}

    def test_a_full_sha_survives_the_round_trip_through_the_column(self, ctx, monkeypatch) -> None:
        """⚠ ``VARCHAR(32)`` COULD NOT HOLD THIS -- see migration 0004.

        ``"0.1.0"`` fit in the old width; a 40-character SHA does not. SQLite
        does not enforce VARCHAR lengths, so this asserts the LENGTH survives
        rather than trusting the database to complain -- on Postgres it would
        have been a rejected INSERT in production.
        """
        monkeypatch.setenv("IDA_GIT_SHA", "8" * 40)
        rows = self._enqueued_rows(ctx)
        assert all(len(r.harness_version) == 40 for r in rows)


class TestScheduledSweepsRespectExcludeTags:
    """`enabled: true` must not silently mean "and bill this every night".

    Enabling `luna` (#48) put a metered, $25-capped hosted model into the
    registry. Both nightly sweeps plan over the enabled set, so without a filter
    the 02:00 rebenchmark would sweep the full suite against it, and the 03:30
    `model-sweep` -- whose entire job is giving a *newly enabled* model its first
    numbers -- would do the same thing again on the very first night.

    These tests pin the filter and, just as importantly, pin that it is LOUD.
    """

    def _keys(self, ctx, **overrides) -> tuple[list[str], SweepReport]:
        settings = ctx.settings.model_copy(update=overrides) if overrides else ctx.settings
        report = SweepReport(sweep="probe")
        return sweeps.sweepable_model_keys(ctx.registry, settings, report=report), report

    def test_a_testing_only_model_is_held_back_by_default(self, ctx) -> None:
        keys, _ = self._keys(ctx)
        assert "luna" not in keys

    def test_the_ordinary_models_are_still_swept(self, ctx) -> None:
        """The filter must remove one entry, not disable sweeping."""
        keys, _ = self._keys(ctx)
        assert "mock" in keys

    def test_holding_a_model_back_is_reported(self, ctx) -> None:
        """A sweep that narrowed its own scope silently would report "nothing
        left to measure" about a suite it chose not to measure."""
        _, report = self._keys(ctx)
        assert any("luna" in note for note in report.notes)

    def test_the_note_names_the_tag_that_caused_it(self, ctx) -> None:
        """An operator asking "why was luna skipped" should not have to read
        this module to find out."""
        _, report = self._keys(ctx)
        assert any("testing-only" in note for note in report.notes)

    def test_nothing_is_reported_when_nothing_is_held_back(self, ctx) -> None:
        _, report = self._keys(ctx, sweep_exclude_tags="")
        assert report.notes == []

    def test_an_empty_setting_sweeps_every_enabled_model(self, ctx) -> None:
        """The escape hatch: an operator who has done the arithmetic can turn the
        filter off for a deliberate firing."""
        keys, _ = self._keys(ctx, sweep_exclude_tags="")
        assert set(keys) == set(ctx.registry.enabled_keys())

    def test_matching_is_case_insensitive(self, ctx) -> None:
        keys, _ = self._keys(ctx, sweep_exclude_tags="TESTING-ONLY")
        assert "luna" not in keys

    def test_a_disabled_model_never_appears_regardless_of_tags(self, ctx) -> None:
        """`sparks-local` is disabled AND untagged by the exclude list. Enabled-ness
        is still the first gate."""
        keys, _ = self._keys(ctx, sweep_exclude_tags="")
        assert "sparks-local" not in keys

    def test_rebenchmark_does_not_enqueue_the_held_back_model(self, ctx) -> None:
        """The end-to-end statement: no queue message names luna."""
        run_rebenchmark(ctx)
        assert "luna" not in {model for _task, model in _drain_pairs(ctx.queue)}

    def test_model_sweep_does_not_treat_it_as_a_new_model(self, ctx) -> None:
        """The sharpest edge. `model-sweep` looks for enabled models with no
        measured run and enqueues the whole suite for them -- which is exactly
        what luna is on the night it lands."""
        report = run_model_sweep(ctx)
        assert "luna" not in {model for _task, model in _drain_pairs(ctx.queue)}
        assert report.exit_code == 0
