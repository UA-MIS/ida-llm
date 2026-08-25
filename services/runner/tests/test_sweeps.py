"""The three CronJob entry points.

These sweeps are the only thing in the system that can commission provider spend
on a schedule with nobody watching, so the tests lead with the ways that goes
wrong: an empty registry, a budget blown, a queue that dies halfway, a judge that
does not exist yet. The happy path is one small class at the end.

Nothing here touches a real service. The queue is the in-memory implementation
(a real one, not a mock -- see ``ida_core.queue``), the database is SQLite, and
no sweep in this module ever reaches a model endpoint, because a sweep does not:
it enqueues, and runners execute.
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
    )


def _scorable(ctx: SweepContext):
    return sweeps.scorable_tasks(ctx.catalog)


def _seed_terminal_run(
    session_factory,
    *,
    task_id: str,
    model_key: str,
    content_sha: str | None,
    status: RunStatus = RunStatus.SUCCEEDED,
) -> str:
    """A finished run, exactly as the worker would have left it."""
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
                created_at=utcnow(),
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

    def test_rows_survive_a_queue_failure_so_the_work_is_re_drivable(self, ctx) -> None:
        """Rows are committed BEFORE any push, exactly as `POST /runs` does it.

        The un-pushed runs stay `queued` and visible rather than vanishing, which
        is what makes the failure recoverable instead of merely reported.
        """
        from ida_core.repositories import count_runs

        scoped = _with(ctx, queue=_ExplodingQueue(ok_count=2))

        report = run_rebenchmark(scoped)

        with session_scope(ctx.session_factory) as session:
            assert count_runs(session, status=RunStatus.QUEUED) == report.considered

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
    """Ships as an orchestration shell: the judge is not in main yet.

    Verified against the branch point rather than assumed -- `ScorerKind.
    LLM_JUDGE` is registered and unimplemented and `unscorable_reason()` still
    reports subjective tasks as unscorable.
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

    def test_the_skip_is_logged_with_an_explicit_reason_and_count(self, ctx, caplog) -> None:
        """CronJob logs are the operator surface; the backlog must be visible."""
        self._seed_ungraded(ctx.session_factory, 2)

        with caplog.at_level(logging.WARNING, logger="ida.sweep"):
            run_judge_calibration(ctx)

        assert "judge not yet available" in caplog.text
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

    def test_a_scorable_result_is_never_a_candidate(self, ctx) -> None:
        """Verifiable samples are scored programmatically; a judge must not touch them."""
        run_id = self._seed_ungraded(ctx.session_factory, 0)
        with session_scope(ctx.session_factory) as session:
            insert_results(session, [_ungraded_result(run_id, 99, scorable=True)])

        assert run_judge_calibration(ctx).considered == 0

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

    def test_the_wiring_point_reports_no_grader_today(self) -> None:
        """Pins the shell state so the judge's author sees this test go red."""
        assert sweeps._load_retroactive_grader() is None


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
        monkeypatch.setattr(sweeps, "build_context", lambda _settings=None: ctx)

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
        monkeypatch.setattr(sweeps, "build_context", lambda _settings=None: ctx)

        assert main([name, "--dry-run"]) == 0

    def test_dry_run_changes_nothing(self, ctx, monkeypatch) -> None:
        from ida_core.repositories import count_runs

        monkeypatch.setattr(sweeps, "build_context", lambda _settings=None: ctx)

        assert main(["rebenchmark", "--dry-run"]) == 0

        assert ctx.queue.depth() == 0
        with session_scope(ctx.session_factory) as session:
            assert count_runs(session) == 0

    def test_a_budget_refusal_propagates_to_the_process_exit_code(self, ctx, monkeypatch) -> None:
        tight = _with(ctx, settings={"sweep_max_runs": 1})
        monkeypatch.setattr(sweeps, "build_context", lambda _settings=None: tight)

        assert main(["rebenchmark"]) != 0

    def test_the_force_flag_beats_the_environment(self, ctx, monkeypatch) -> None:
        """A human typing --force outranks a variable somebody set last month."""
        run_rebenchmark(ctx)
        seen: list[bool] = []

        def _capture(settings=None):
            seen.append(settings.sweep_force)
            return _with(ctx, settings={"sweep_force": settings.sweep_force})

        monkeypatch.setattr(sweeps, "build_context", _capture)
        monkeypatch.setenv("IDA_SWEEP_FORCE", "0")

        main(["rebenchmark", "--force", "--dry-run"])

        assert seen == [True]

    def test_a_crashing_sweep_exits_non_zero_rather_than_raising(self, monkeypatch, caplog) -> None:
        """A sweep that dies must LOOK dead, in the operator's log format."""

        def _boom(_settings=None):
            raise RuntimeError("postgres is unreachable")

        monkeypatch.setattr(sweeps, "build_context", _boom)

        with caplog.at_level(logging.ERROR, logger="ida.sweep"):
            assert main(["rebenchmark"]) == 1

        assert "postgres is unreachable" in caplog.text


# ---------------------------------------------------------- happy path -----


class TestRebenchmarkHappyPath:
    def test_it_enqueues_the_full_cross_product_on_a_cold_database(self, ctx) -> None:
        report = run_rebenchmark(ctx)

        expected = len(_scorable(ctx)) * len(ctx.registry.enabled_keys())
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


def _ungraded_result(run_id: str, index: int, *, scorable: bool = False):
    from ida_core.contracts import ResultRecord

    return ResultRecord(
        id=f"res_ungraded_{run_id}_{index}",
        run_id=run_id,
        task_id=SUBJECTIVE_TASK,
        sample_id=f"s{index}",
        model_key="mock",
        serving_config=_serving_config(),
        score=None,
        scorable=scorable,
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
