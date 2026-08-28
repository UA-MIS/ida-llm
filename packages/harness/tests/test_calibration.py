"""Calibration slices: the module's whole value is the numbers it REFUSES to report.

A calibration run that says "within tolerance" is a claim that this harness
measures what the field measures.  Every test here exists because there is an
obvious implementation that would make that claim when it is not true:

* average the per-task means, and a 5-sample task outvotes its own size;
* let a partly-errored run report its surviving mean, and an outage looks like
  agreement;
* score a wholly-failed run 0.0, and "we measured nothing" becomes "the model
  got everything wrong";
* accept a published number with no citation, and the comparison is against
  a number somebody remembered;
* compare a number published for model A against a run of model B, and the
  result is about neither.

Nothing here touches the network, needs an API key, or calls a model.  Eval logs
are built by hand and :func:`ida_harness.runner.run_task` is stubbed, so every
assertion is about the aggregation and the verdict rules rather than about HTTP.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from ida_core.contracts import (
    EvalLog,
    ModelEntry,
    ResultRecord,
    RunStatus,
    Score,
    ScorerKind,
    TaskKind,
    TaskSpec,
    terminal_status,
)
from ida_harness.calibration import (
    VERDICT_ERRORS,
    VERDICT_NO_MEASUREMENT,
    VERDICT_OUTSIDE,
    VERDICT_PLACEHOLDER,
    VERDICT_WITHIN,
    CalibrationRefusal,
    CalibrationSlice,
    CalibrationSliceError,
    load_calibration_slice,
    main,
    run_calibration,
)
from ida_harness.tasks import TaskCatalog

REPO_ROOT = Path(__file__).resolve().parents[3]
SHIPPED_SLICE = REPO_ROOT / "calibration" / "gsm8k-slice.yaml"


# --------------------------------------------------------------------------
# Fixtures: tasks of DIFFERENT sizes, and hand-built eval logs
# --------------------------------------------------------------------------


def _task(task_id: str, sample_count: int) -> TaskSpec:
    """A verifiable task with ``sample_count`` samples.

    Sizes are the point: the weighting test needs two tasks whose sample counts
    differ enough that a per-task mean and a per-sample mean are visibly
    different numbers.
    """
    return TaskSpec.model_validate(
        {
            "version": 1,
            "id": task_id,
            "title": task_id,
            "kind": TaskKind.VERIFIABLE,
            "scorer": {"kind": "numeric_match"},
            "samples": [
                {"id": f"s{i}", "input": f"item {i}", "target": str(i)} for i in range(sample_count)
            ],
        }
    )


SMALL = _task("cal/small", 2)
LARGE = _task("cal/large", 8)


@pytest.fixture
def catalog() -> TaskCatalog:
    tasks = {spec.id: spec for spec in (SMALL, LARGE)}
    return TaskCatalog(tasks, {spec_id: Path(f"{spec_id}.yaml") for spec_id in tasks})


def _eval_log(
    *,
    task: TaskSpec,
    entry: ModelEntry,
    scores: list[float | None],
    errors: int = 0,
    cost_usd: float = 0.0,
) -> EvalLog:
    """A finished eval log with exactly the scores/errors asked for.

    Built by hand rather than by running the real runner against a mock
    transport: these tests are about what ``run_calibration`` does with a log,
    and constructing the awkward shapes (all-errored, half-scored) directly is
    both faster and impossible to get accidentally wrong.  ``status`` still goes
    through :func:`~ida_core.contracts.terminal_status`, so the logs cannot claim
    a status the real runner would never produce.
    """
    now = datetime.now(UTC)
    results: list[ResultRecord] = []
    for index, value in enumerate(scores):
        record = ResultRecord(
            id=f"res_{task.id}_{index}",
            run_id="run_x",
            task_id=task.id,
            sample_id=f"s{index}",
            model_key=entry.key,
            serving_config=entry.serving,
            cost_usd=cost_usd,
        )
        if index < errors:
            record.error = "TransientModelError: endpoint refused the connection"
        elif value is not None:
            record.score = Score(scorer=ScorerKind.NUMERIC_MATCH, value=value)
        results.append(record)
    return EvalLog(
        run_id="run_x",
        task_id=task.id,
        task_git_sha=None,
        model_key=entry.key,
        serving_config=entry.serving,
        harness_version="test",
        status=terminal_status(sample_count=len(results), error_count=errors),
        results=results,
        transcripts=[],
        started_at=now,
        finished_at=now,
    )


def _stub(logs_by_task: dict[str, EvalLog]):
    """A ``run_task`` stand-in that hands back a prepared log per task id."""

    def fake_run_task(*, task: TaskSpec, **_kwargs) -> EvalLog:
        return logs_by_task[task.id]

    return fake_run_task


def _reference(**overrides) -> dict:
    base = {
        "benchmark": "gsm8k",
        "slice_id": "s1",
        "model_key": "mock",
        "published_score": 0.78,
        "published_source": "https://example.org/paper",
        "published_retrieved": "2026-01-15",
        "tolerance": 0.05,
        "task_ids": [LARGE.id],
    }
    base.update(overrides)
    return base


def _slice(**overrides) -> CalibrationSlice:
    return CalibrationSlice.model_validate({"version": 1, "references": [_reference(**overrides)]})


# --------------------------------------------------------------------------
# The comparison itself
# --------------------------------------------------------------------------


class TestTheComparison:
    def test_a_matching_measurement_is_within_tolerance(self, catalog, model_entry) -> None:
        """The happy path, and the only shape allowed to report agreement."""
        logs = {LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[1.0] * 6 + [0.0] * 2)}
        report = run_calibration(
            slice_=_slice(),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.measured_score == pytest.approx(0.75)
        assert outcome.delta == pytest.approx(-0.03)
        assert outcome.within_tolerance is True
        assert outcome.verdict == VERDICT_WITHIN
        assert report.ok is True
        assert report.exit_code == 0

    def test_a_measurement_that_disagrees_is_reported_as_disagreeing(
        self, catalog, model_entry
    ) -> None:
        """The interesting failure: the harness works, and it does not match.

        This is the finding the module exists to produce, so it must be
        distinguishable from an outage -- hence its own verdict.
        """
        logs = {LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[1.0] * 2 + [0.0] * 6)}
        report = run_calibration(
            slice_=_slice(),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.measured_score == pytest.approx(0.25)
        assert outcome.delta == pytest.approx(-0.53)
        assert outcome.within_tolerance is False
        assert outcome.verdict == VERDICT_OUTSIDE
        assert report.exit_code == 1

    def test_the_tolerance_boundary_is_inclusive_and_not_rounded_away(
        self, catalog, model_entry
    ) -> None:
        """``abs(delta) <= tolerance``, decided on the raw floats.

        A ``round(delta, 2)`` anywhere before the comparison would pull a delta
        of 0.126 inside a tolerance of 0.125 and flip the verdict -- so this
        pins a delta that sits just outside a tolerance the display would round
        to the same two decimals.
        """
        logs = {LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[1.0] * 5 + [0.0] * 3)}
        report = run_calibration(
            slice_=_slice(published_score=0.5, tolerance=0.124),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.measured_score == pytest.approx(0.625)
        assert outcome.delta == pytest.approx(0.125)
        assert outcome.within_tolerance is False, "0.125 > 0.124, and rounding must not hide it"
        # And the display still shows both to three decimals, which is exactly
        # why the verdict may not be computed from the display.
        assert "0.124" in report.table()


# --------------------------------------------------------------------------
# Rule 1: a broken run is never a calibration result
# --------------------------------------------------------------------------


class TestABrokenRunNeverReportsAgreement:
    def test_a_partly_errored_run_is_not_passed_just_because_the_mean_lands_close(
        self, catalog, model_entry
    ) -> None:
        """The dangerous case: the surviving samples average to the right number.

        Six of eight samples died; the two that lived both scored 1.0, so the
        partial mean is 0.80 -- exactly the published figure. Reporting that as
        agreement would turn an outage into evidence that the harness is
        correct.
        """
        logs = {
            LARGE.id: _eval_log(
                task=LARGE, entry=model_entry, scores=[None] * 6 + [1.0, 1.0], errors=6
            )
        }
        report = run_calibration(
            slice_=_slice(published_score=1.0),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.measured_score == pytest.approx(1.0), "the arithmetic really does match"
        assert outcome.delta == pytest.approx(0.0)
        assert outcome.within_tolerance is False, "and it is still not a calibration result"
        assert outcome.verdict == VERDICT_ERRORS
        assert outcome.error_count == 6
        assert report.ok is False
        assert report.exit_code == 1

    def test_the_explanation_says_how_much_of_the_slice_is_missing(
        self, catalog, model_entry
    ) -> None:
        """A verdict nobody can act on is a verdict nobody acts on."""
        logs = {
            LARGE.id: _eval_log(
                task=LARGE, entry=model_entry, scores=[None] * 6 + [1.0, 1.0], errors=6
            )
        }
        report = run_calibration(
            slice_=_slice(),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        explanation = report.outcomes[0].explanation
        assert "6 sample(s) errored" in explanation
        assert "2 that survived" in explanation

    def test_a_wholly_failed_run_measures_nothing_rather_than_zero(
        self, catalog, model_entry
    ) -> None:
        """``measured_score is None``, never ``0.0``.

        "We measured zero" is a claim about the model; "we measured nothing" is a
        claim about the run.  A zero here would defame a model for our outage --
        the same mistake ``EvalLog.mean_score`` refuses to make within a task.
        """
        logs = {LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[None] * 8, errors=8)}
        report = run_calibration(
            slice_=_slice(),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert logs[LARGE.id].status is RunStatus.FAILED, "precondition"
        assert outcome.measured_score is None
        assert outcome.delta is None
        assert outcome.within_tolerance is False
        assert outcome.verdict == VERDICT_NO_MEASUREMENT

    def test_a_failed_task_does_not_drag_a_surviving_task_towards_zero(
        self, catalog, model_entry
    ) -> None:
        """A failed log contributes to neither numerator nor denominator.

        Folding its samples in as zeros would report 0.20 for a slice whose one
        real measurement is 1.00 -- an outage rendered as a model failing.
        """
        logs = {
            SMALL.id: _eval_log(task=SMALL, entry=model_entry, scores=[1.0, 1.0]),
            LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[None] * 8, errors=8),
        }
        report = run_calibration(
            slice_=_slice(task_ids=[SMALL.id, LARGE.id], published_score=1.0),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.measured_score == pytest.approx(1.0)
        assert outcome.scored_count == 2
        assert outcome.sample_count == 10, "the missing samples are still counted"
        assert outcome.error_count == 8
        assert outcome.within_tolerance is False, "8 of 10 samples are missing"

    def test_an_empty_report_is_not_a_passing_report(self, model_entry) -> None:
        """A calibration that compared nothing must not read as one that passed."""
        from ida_harness.calibration import CalibrationReport

        assert CalibrationReport(model_key=model_entry.key).ok is False


# --------------------------------------------------------------------------
# Rule 2: weight by scored samples, not by task
# --------------------------------------------------------------------------


class TestAggregationIsWeightedBySample:
    def test_two_tasks_of_different_sizes_are_one_measurement_of_their_samples(
        self, catalog, model_entry
    ) -> None:
        """8 samples at 1.0 and 2 at 0.0 is 0.80, not the 0.50 of a task-mean.

        The per-task means here are 1.00 and 0.00; averaging THOSE gives 0.50 and
        silently promotes each sample of the 2-sample task to four times the
        weight of a sample in the 8-sample task.  Published benchmark numbers are
        means over items, so the task-weighted figure would be a different
        statistic wearing the same name.
        """
        logs = {
            LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[1.0] * 8),
            SMALL.id: _eval_log(task=SMALL, entry=model_entry, scores=[0.0, 0.0]),
        }
        report = run_calibration(
            slice_=_slice(task_ids=[LARGE.id, SMALL.id]),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.measured_score == pytest.approx(0.8)
        assert outcome.measured_score != pytest.approx(0.5), "that would be the task-mean"
        assert outcome.scored_count == 10
        assert outcome.sample_count == 10

    def test_unscored_samples_leave_the_mean_alone_and_are_counted_separately(
        self, catalog, model_entry
    ) -> None:
        """An unscorable sample is excluded from the denominator, not zeroed.

        Six samples scored 1.0 and two produced no score at all: the mean is
        1.00 over six, and ``scored_count`` is what tells the reader the mean
        covers six of eight.
        """
        logs = {LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[1.0] * 6 + [None, None])}
        report = run_calibration(
            slice_=_slice(published_score=1.0),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.measured_score == pytest.approx(1.0)
        assert outcome.scored_count == 6
        assert outcome.sample_count == 8
        assert outcome.error_count == 0

    def test_cost_is_summed_across_every_task_in_the_reference(self, catalog, model_entry) -> None:
        """What a calibration cost is part of what it reports; a slice you cannot
        price is a slice nobody will re-run."""
        logs = {
            LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[1.0] * 8, cost_usd=0.001),
            SMALL.id: _eval_log(task=SMALL, entry=model_entry, scores=[1.0, 1.0], cost_usd=0.002),
        }
        report = run_calibration(
            slice_=_slice(task_ids=[LARGE.id, SMALL.id], published_score=1.0),
            catalog=catalog,
            entry=model_entry,
            run_task_fn=_stub(logs),
        )
        assert report.total_cost_usd == pytest.approx(8 * 0.001 + 2 * 0.002)


# --------------------------------------------------------------------------
# Rule 4: provenance
# --------------------------------------------------------------------------


class TestProvenanceIsMandatory:
    def test_a_reference_with_no_source_is_rejected(self) -> None:
        """A published number with no citation is a number somebody remembered."""
        with pytest.raises(ValueError, match="published_source"):
            CalibrationSlice.model_validate(
                {"version": 1, "references": [_reference(published_source="   ")]}
            )

    def test_a_reference_with_no_retrieval_date_is_rejected(self) -> None:
        """Leaderboards are edited in place, so the URL alone does not say WHICH
        version of the page was read."""
        payload = _reference()
        del payload["published_retrieved"]
        with pytest.raises(ValueError, match="published_retrieved"):
            CalibrationSlice.model_validate({"version": 1, "references": [payload]})

    def test_a_source_that_is_not_a_url_is_rejected(self) -> None:
        """ "the paper" is not a citation somebody who distrusts us can open."""
        with pytest.raises(ValueError, match="must be a URL"):
            CalibrationSlice.model_validate(
                {"version": 1, "references": [_reference(published_source="the GSM8K paper")]}
            )

    def test_a_slice_needs_at_least_one_reference(self) -> None:
        with pytest.raises(ValueError):
            CalibrationSlice.model_validate({"version": 1, "references": []})

    def test_a_reference_needs_at_least_one_task_id(self) -> None:
        with pytest.raises(ValueError):
            CalibrationSlice.model_validate({"version": 1, "references": [_reference(task_ids=[])]})

    def test_a_repeated_task_id_is_rejected(self) -> None:
        """It would weight that task's samples twice over."""
        with pytest.raises(ValueError, match="duplicates"):
            CalibrationSlice.model_validate(
                {"version": 1, "references": [_reference(task_ids=[LARGE.id, LARGE.id])]}
            )


class TestLoadingASliceFile:
    def test_a_valid_file_round_trips(self, tmp_path) -> None:
        path = tmp_path / "slice.yaml"
        path.write_text(yaml.safe_dump({"version": 1, "references": [_reference()]}))
        loaded = load_calibration_slice(path)
        assert loaded.references[0].benchmark == "gsm8k"
        assert loaded.references[0].label == "gsm8k/s1"

    def test_a_missing_file_is_a_calibration_slice_error(self, tmp_path) -> None:
        """One error type for every way an authored file can be wrong: the
        caller's remedy is always "fix the file", and a run must never proceed on
        a slice we are guessing at."""
        with pytest.raises(CalibrationSliceError, match="not found"):
            load_calibration_slice(tmp_path / "nope.yaml")

    def test_unparseable_yaml_is_a_calibration_slice_error(self, tmp_path) -> None:
        path = tmp_path / "slice.yaml"
        path.write_text("references: [oops\n")
        with pytest.raises(CalibrationSliceError, match="could not parse YAML"):
            load_calibration_slice(path)

    def test_a_semantic_failure_names_the_file(self, tmp_path) -> None:
        path = tmp_path / "slice.yaml"
        path.write_text(
            yaml.safe_dump({"version": 1, "references": [_reference(published_source="")]})
        )
        with pytest.raises(CalibrationSliceError, match=r"slice\.yaml"):
            load_calibration_slice(path)


# --------------------------------------------------------------------------
# Rule 5: whose number is this?
# --------------------------------------------------------------------------


class TestTheModelKeyMustMatch:
    def test_a_mismatch_is_refused_before_anything_runs(self, catalog, model_entry) -> None:
        """Published-for-A vs measured-on-B is not a weak result, it is a result
        about neither model.  Refused up front, so the refusal is free."""
        called: list[str] = []

        def tripwire(**_kwargs) -> EvalLog:
            called.append("boom")
            raise AssertionError("run_calibration called a model after refusing")

        with pytest.raises(CalibrationRefusal, match="published for model 'gpt-4o'"):
            run_calibration(
                slice_=_slice(model_key="gpt-4o"),
                catalog=catalog,
                entry=model_entry,
                run_task_fn=tripwire,
            )
        assert called == []

    def test_the_escape_hatch_runs_but_marks_the_outcome_cross_model(
        self, catalog, model_entry
    ) -> None:
        """``allow_model_mismatch`` exists for the real case where models.yaml
        and the benchmark name the same underlying model differently -- so it
        must not be silent, and it must not be secretly fatal either."""
        logs = {LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[1.0] * 6 + [0.0] * 2)}
        report = run_calibration(
            slice_=_slice(model_key="gpt-4o"),
            catalog=catalog,
            entry=model_entry,
            allow_model_mismatch=True,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.cross_model is True
        assert outcome.reference_model_key == "gpt-4o"
        assert outcome.model_key == model_entry.key
        assert "CROSS-MODEL" in outcome.explanation
        assert "CROSS-MODEL" in report.table()
        assert outcome.within_tolerance is True, (
            "the arithmetic still stands; the LABEL is the warning"
        )

    def test_a_matching_key_is_never_marked_cross_model(self, catalog, model_entry) -> None:
        logs = {LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[1.0] * 6 + [0.0] * 2)}
        report = run_calibration(
            slice_=_slice(), catalog=catalog, entry=model_entry, run_task_fn=_stub(logs)
        )
        assert report.outcomes[0].cross_model is False
        assert "CROSS-MODEL" not in report.table()


class TestPlaceholderCitations:
    def test_a_placeholder_reference_is_refused_by_default(self, catalog, model_entry) -> None:
        """A draft citation is not a citation.  Refused before spending money."""
        with pytest.raises(CalibrationRefusal, match="TODO-PLACEHOLDER"):
            run_calibration(
                slice_=_slice(published_source="TODO-PLACEHOLDER(published-source)"),
                catalog=catalog,
                entry=model_entry,
                run_task_fn=_stub({}),
            )

    def test_allowing_it_measures_the_slice_but_can_never_report_agreement(
        self, catalog, model_entry
    ) -> None:
        """The one legitimate use is learning the number you are about to write
        down.  If this could go green, CI could go green on a stub."""
        logs = {LARGE.id: _eval_log(task=LARGE, entry=model_entry, scores=[0.0] * 8)}
        report = run_calibration(
            slice_=_slice(
                published_source="TODO-PLACEHOLDER(published-source)", published_score=0.0
            ),
            catalog=catalog,
            entry=model_entry,
            allow_placeholder=True,
            run_task_fn=_stub(logs),
        )
        outcome = report.outcomes[0]
        assert outcome.measured_score == pytest.approx(0.0)
        assert outcome.delta == pytest.approx(0.0), "the arithmetic agrees exactly"
        assert outcome.within_tolerance is False, "and it still means nothing"
        assert outcome.verdict == VERDICT_PLACEHOLDER
        assert report.exit_code == 1


# --------------------------------------------------------------------------
# Resolution, dry runs, and the file this repo actually ships
# --------------------------------------------------------------------------


class TestResolutionHappensBeforeSpending:
    def test_an_unknown_task_id_is_refused_and_names_the_id(self, catalog, model_entry) -> None:
        """A typo must be a startup failure, not a short measurement nobody
        notices three references and two invoices in."""
        with pytest.raises(CalibrationSliceError, match="cal/nope"):
            run_calibration(
                slice_=_slice(task_ids=["cal/nope"]),
                catalog=catalog,
                entry=model_entry,
                run_task_fn=_stub({}),
            )

    def test_a_later_bad_reference_stops_an_earlier_good_one_from_running(
        self, catalog, model_entry
    ) -> None:
        """Everything is resolved before anything executes, so a slice that is
        going to be rejected costs nothing at all."""
        slice_ = CalibrationSlice.model_validate(
            {
                "version": 1,
                "references": [
                    _reference(slice_id="good"),
                    _reference(slice_id="bad", task_ids=["cal/nope"]),
                ],
            }
        )

        def tripwire(**_kwargs) -> EvalLog:
            raise AssertionError("a task ran before the whole slice was resolved")

        with pytest.raises(CalibrationSliceError):
            run_calibration(slice_=slice_, catalog=catalog, entry=model_entry, run_task_fn=tripwire)

    def test_a_dry_run_plans_without_calling_anything(self, catalog, model_entry) -> None:
        """ "what would run" and "what was measured" are different lists, so a
        preview can never be mistaken for a result."""

        def tripwire(**_kwargs) -> EvalLog:
            raise AssertionError("a dry run called a model")

        report = run_calibration(
            slice_=_slice(task_ids=[LARGE.id, SMALL.id]),
            catalog=catalog,
            entry=model_entry,
            dry_run=True,
            run_task_fn=tripwire,
        )
        assert report.outcomes == []
        assert report.planned[0].sample_count == 10
        assert report.dry_run is True
        assert report.ok is False, "a dry run measured nothing"
        assert report.exit_code == 0, "but it did what it was asked to do"
        assert "DRY RUN" in report.summary()

    def test_a_dry_run_reports_every_refusal_instead_of_raising_on_the_first(
        self, catalog, model_entry
    ) -> None:
        """An author fixing a slice wants all of its problems in one pass.

        Raising would hide the placeholder citation behind the model mismatch --
        and would make the free, keyless, offline preview unusable on exactly the
        files (templates, drafts) that most need previewing.
        """
        report = run_calibration(
            slice_=_slice(
                model_key="gpt-4o", published_source="TODO-PLACEHOLDER(published-source)"
            ),
            catalog=catalog,
            entry=model_entry,
            dry_run=True,
            run_task_fn=_stub({}),
        )
        item = report.planned[0]
        assert item.cross_model is True
        assert item.is_placeholder is True
        notes = " | ".join(report.notes)
        assert "published for model 'gpt-4o'" in notes
        assert "TODO-PLACEHOLDER" in notes
        assert report.exit_code == 0, "the preview succeeded; it is the RUN that is refused"

    def test_an_unresolvable_task_id_is_fatal_even_in_a_dry_run(self, catalog, model_entry) -> None:
        """Not a policy refusal -- a slice naming tasks that do not exist has
        nothing to preview."""
        with pytest.raises(CalibrationSliceError, match="cal/nope"):
            run_calibration(
                slice_=_slice(task_ids=["cal/nope"]),
                catalog=catalog,
                entry=model_entry,
                dry_run=True,
                run_task_fn=_stub({}),
            )

    def test_the_shipped_template_dry_runs_against_the_mock_model(self, model_entry) -> None:
        """The documented CI command in docs/calibration.md, executed.

        The template is written for `luna` and its citation is a placeholder, so
        both notes must appear -- and it must still produce a plan rather than an
        exception, or the doc's example is a lie.
        """
        catalog = TaskCatalog.from_directory(REPO_ROOT / "tasks")
        report = run_calibration(
            slice_=load_calibration_slice(SHIPPED_SLICE),
            catalog=catalog,
            entry=model_entry,
            dry_run=True,
            run_task_fn=_stub({}),
        )
        assert report.planned[0].sample_count == 12
        assert report.planned[0].cross_model is True
        assert report.planned[0].is_placeholder is True
        assert "CROSS-MODEL" in report.table()
        assert "TODO-PLACEHOLDER" in report.table()


class TestTheShippedTemplate:
    """``calibration/gsm8k-slice.yaml`` ships deliberately unfinished.

    Fabricating a plausible benchmark figure and URL would have made the
    directory look complete while making this platform's central claim false
    inside its own repository.  These tests pin the honest alternative: the file
    parses, and it cannot be used as evidence.
    """

    def test_it_parses(self) -> None:
        slice_ = load_calibration_slice(SHIPPED_SLICE)
        assert slice_.references

    def test_its_citation_is_still_a_placeholder(self) -> None:
        slice_ = load_calibration_slice(SHIPPED_SLICE)
        assert slice_.placeholder_labels == [r.label for r in slice_.references]

    def test_every_task_id_it_names_really_exists(self) -> None:
        """A template whose ids do not resolve teaches the wrong shape, and its
        --dry-run -- the documented CI path -- would fail."""
        catalog = TaskCatalog.from_directory(REPO_ROOT / "tasks")
        slice_ = load_calibration_slice(SHIPPED_SLICE)
        for reference in slice_.references:
            for task_id in reference.task_ids:
                assert task_id in catalog, task_id

    def test_it_contains_no_benchmark_item_text(self) -> None:
        """Dataset hygiene: a slice is a list of ids, never content.

        Length is a crude proxy and deliberately so -- the rule this guards is
        "nobody pasted a benchmark's questions in here", and a file that grew to
        item-corpus size is the thing worth failing on.
        """
        document = yaml.safe_load(SHIPPED_SLICE.read_text())
        for reference in document["references"]:
            assert set(reference) <= {
                "benchmark",
                "slice_id",
                "description",
                "model_key",
                "published_score",
                "published_source",
                "published_retrieved",
                "tolerance",
                "task_ids",
            }
            assert "input" not in reference and "samples" not in reference


# --------------------------------------------------------------------------
# The CLI
# --------------------------------------------------------------------------


@pytest.fixture
def cli_slice(tmp_path):
    """Writes a slice against the repo's real tasks and the `mock` registry key.

    Real files rather than fakes because the CLI's job IS the wiring: settings ->
    registry -> catalog -> slice.  ``mock`` declares no ``api_key_env``, so
    nothing here needs a key, and ``run_task`` is patched out, so nothing here
    makes a call.
    """

    def write(published_score: float, tolerance: float = 0.05) -> Path:
        path = tmp_path / "cli-slice.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "references": [
                        {
                            "benchmark": "gsm8k",
                            "slice_id": "cli",
                            "model_key": "mock",
                            "published_score": published_score,
                            "published_source": "https://example.org/paper",
                            "published_retrieved": "2026-01-15",
                            "tolerance": tolerance,
                            "task_ids": ["quantitative-quiz/l1-descriptive-key"],
                        }
                    ],
                }
            )
        )
        return path

    return write


def _patch_run_task(monkeypatch, score: float) -> None:
    """Make every sample score ``score``, without a client or a socket.

    Patches the module attribute rather than passing ``run_task_fn``: ``main``
    never passes that parameter, and a CLI test that could only work by
    threading a seam through the CLI would be testing a code path production
    does not have.
    """
    import ida_harness.calibration as calibration_module

    def fake_run_task(*, task, entry, run_id, **_kwargs) -> EvalLog:
        return _eval_log(task=task, entry=entry, scores=[score] * len(task.samples))

    monkeypatch.setattr(calibration_module, "run_task", fake_run_task)


def _argv(slice_path: Path, *extra: str) -> list[str]:
    return [
        "--slice",
        str(slice_path),
        "--model",
        "mock",
        "--tasks-dir",
        str(REPO_ROOT / "tasks"),
        "--models-file",
        str(REPO_ROOT / "models.yaml"),
        *extra,
    ]


class TestTheCli:
    def test_it_exits_zero_when_every_reference_agrees(
        self, monkeypatch, cli_slice, capsys
    ) -> None:
        _patch_run_task(monkeypatch, score=1.0)
        assert main(_argv(cli_slice(published_score=1.0))) == 0
        out = capsys.readouterr().out
        assert "WITHIN_TOLERANCE" in out
        assert "ok=True" in out

    def test_it_exits_non_zero_when_a_reference_disagrees(
        self, monkeypatch, cli_slice, capsys
    ) -> None:
        """A calibration failure that exits 0 is a calibration nobody notices."""
        _patch_run_task(monkeypatch, score=0.0)
        assert main(_argv(cli_slice(published_score=1.0))) == 1
        out = capsys.readouterr().out
        assert "OUTSIDE_TOLERANCE" in out
        assert "ok=False" in out

    def test_a_dry_run_exits_zero_and_says_so_on_every_line(
        self, monkeypatch, cli_slice, capsys
    ) -> None:
        def tripwire(**_kwargs) -> EvalLog:
            raise AssertionError("--dry-run called a model")

        import ida_harness.calibration as calibration_module

        monkeypatch.setattr(calibration_module, "run_task", tripwire)
        assert main(_argv(cli_slice(published_score=1.0), "--dry-run")) == 0
        assert "DRY RUN" in capsys.readouterr().out

    def test_an_unusable_slice_exits_two_rather_than_one(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        """2 is "the slice is broken", 1 is "the harness disagrees with the
        field".  A CI job has to tell those apart: one is a bug in this file, the
        other is a finding."""
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump({"version": 1, "references": []}))
        assert main(_argv(bad)) == 2
        assert "calibration:" in capsys.readouterr().err

    def test_a_refused_comparison_exits_two(self, monkeypatch, tmp_path, capsys) -> None:
        """Refusals are not findings either."""
        path = tmp_path / "mismatch.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "references": [
                        {
                            "benchmark": "gsm8k",
                            "slice_id": "cli",
                            "model_key": "some-other-key",
                            "published_score": 0.5,
                            "published_source": "https://example.org/paper",
                            "published_retrieved": "2026-01-15",
                            "task_ids": ["quantitative-quiz/l1-descriptive-key"],
                        }
                    ],
                }
            )
        )
        _patch_run_task(monkeypatch, score=1.0)
        assert main(_argv(path)) == 2
        assert "calibration refused:" in capsys.readouterr().err
