"""Grade a run that finished **before** there was a judge to grade it.

The promise this redeems
------------------------
Subjective runs executed without a judge record ``scorable=False``,
``score=None`` -- and archive their transcripts anyway.  ``tasks/SCHEMA.md`` and
:mod:`ida_harness.runner` both state, in so many words, that such a run is
gradable later.  This module is the "later": it reads a completed run's eval log
and sample transcripts out of object storage, grades each unscored subjective
sample with a judge, and writes the grades back into the archived eval log.

No model under test is ever called again.  The completion being graded is the
one that was originally produced and archived, so a retroactive grade is a grade
of the same run -- not of a fresh, differently-sampled answer that happens to
share a run id.

The comparability gate
----------------------
A run is refused if the task's definition has changed since it executed:
:attr:`~ida_core.contracts.ResultRecord.task_content_sha` recorded what was in
effect, and grading yesterday's completion against today's edited rubric would
produce a number that is comparable to nothing -- neither to the run's own
siblings nor to results graded before the edit.  The refusal names both hashes,
and ``--allow-task-drift`` exists for the operator who genuinely wants it and
will say so out loud.

Persistence
-----------
This writes to **object storage**, which is where the run's artifacts live.
Updating the Postgres ``results`` rows is deliberately left to the caller: the
records come back from :func:`regrade_run` ready to persist, and the service
that owns those rows (the API, and behind it the runner) owns that write.  Doing
it from here would mean the harness reaching into a database it otherwise never
touches.  See the module's ``NOTE`` in ``docs/llm-judge.md``.

That contract is why ``dry_run`` leaves the records **untouched** rather than
merely skipping the writes: "ready to persist" and "these grades were never
archived" cannot both be true of the same object.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Collection
from dataclasses import dataclass, field

from ida_core.artifacts import ArtifactStore, eval_log_key, judge_key, parse_uri, sample_key
from ida_core.contracts import EvalLog, ResultRecord, SampleTranscript, TaskSpec, terminal_status
from ida_harness.judge import LLMJudge
from ida_harness.tasks import TaskCatalog

log = logging.getLogger(__name__)


@dataclass
class RegradeReport:
    """What a regrade actually did.  Every sample lands in exactly one bucket."""

    run_id: str
    eval_log: EvalLog
    graded: list[str] = field(default_factory=list)
    """Sample ids that now carry a score they did not have before."""

    failed: list[tuple[str, str]] = field(default_factory=list)
    """``(sample_id, reason)`` -- the judge ran and could not produce a grade."""

    skipped: list[tuple[str, str]] = field(default_factory=list)
    """``(sample_id, reason)`` -- nothing was asked of the judge, and why."""

    judge_cost_usd: float = 0.0
    """Money this regrade spent, at the judge's rates.  Includes failed samples."""

    dry_run: bool = False
    """True when nothing was written and the records were left untouched.

    On the report rather than only in the caller's memory, because
    :attr:`eval_log` is otherwise indistinguishable from a real one -- and the
    difference is whether persisting it would be a lie.
    """

    @property
    def mean_score(self) -> float | None:
        return self.eval_log.mean_score

    def summary(self) -> str:
        suffix = " [DRY RUN -- nothing written, records unchanged]" if self.dry_run else ""
        return (
            f"run {self.run_id}: graded {len(self.graded)}, failed {len(self.failed)}, "
            f"skipped {len(self.skipped)}, judge cost ${self.judge_cost_usd:.6f}, "
            f"mean={self.mean_score}{suffix}"
        )


def load_eval_log(store: ArtifactStore, run_id: str) -> EvalLog:
    """Read a run's archived eval log.  ``KeyError`` if the run has no artifacts."""
    return EvalLog.model_validate(store.get_json(eval_log_key(run_id)))


def _load_transcript(store: ArtifactStore, record: ResultRecord) -> SampleTranscript:
    """The archived completion for one result.

    Prefers the recorded ``transcript_uri`` over reconstructing the key, because
    the URI is what the record actually claims as its evidence; falling straight
    to the convention would silently read a *different* object if the two ever
    disagreed.
    """
    if record.transcript_uri:
        _bucket, key = parse_uri(record.transcript_uri)
    else:
        key = sample_key(record.run_id, record.sample_id, record.repeat_index)
    return SampleTranscript.model_validate(store.get_json(key))


def regrade_run(
    *,
    run_id: str,
    store: ArtifactStore,
    judge: LLMJudge,
    task: TaskSpec | None = None,
    catalog: TaskCatalog | None = None,
    allow_task_drift: bool = False,
    dry_run: bool = False,
    only_result_ids: Collection[str] | None = None,
) -> RegradeReport:
    """Grade every ungraded subjective sample of a completed run.

    Exactly one of ``task`` or ``catalog`` must be given -- the task definition
    is not recoverable from the eval log (only its hash is), and grading needs
    the rubric.

    Only samples that are ``scorable=False`` **and** carry no ``error`` are
    touched.  An errored sample has no completion to grade; an already-scored one
    is left exactly as it was, so running this twice cannot quietly regrade a
    run under a different judge and overwrite the first verdict.

    ``only_result_ids`` restricts grading to the results whose ``id`` appears in
    it; everything else in the run is skipped untouched.  **This is what makes a
    per-result bound survive a per-run call.**  A caller that nominated three of
    a run's twenty samples -- because the other seventeen are graded, ungradable,
    or have exhausted ``judge_attempts`` -- would otherwise have its bound
    silently widened back to the whole run by the very call meant to honour it,
    and the exhausted samples would be re-billed on every firing.  ``None`` means
    the whole run, which is what the CLI wants.

    ``dry_run`` calls the judge -- and is charged for it -- but changes nothing:
    it writes no object, and it leaves the returned records exactly as it found
    them, so a caller acting on this function's "ready to persist" contract
    cannot write grades that were never archived.  ``graded``/``failed`` still
    report what *would* have changed, and :attr:`RegradeReport.dry_run` says so.
    It answers "what would this change", **not** "what would this cost".
    """
    eval_log = load_eval_log(store, run_id)

    if task is None:
        if catalog is None:
            raise ValueError("regrade_run needs either task= or catalog=")
        task = catalog.get(eval_log.task_id)

    report = RegradeReport(run_id=run_id, eval_log=eval_log, dry_run=dry_run)

    if task.rubric is None:
        report.skipped.append(("*", f"task {task.id!r} has no rubric; nothing to judge against"))
        return report

    for record in eval_log.results:
        if only_result_ids is not None and record.id not in only_result_ids:
            # Not nominated. Recorded as a skip rather than passed over in
            # silence so the report still accounts for every sample in the run
            # -- a caller reconciling "twenty results, three graded" against a
            # report listing three needs the other seventeen to be somewhere.
            report.skipped.append((record.sample_id, "not nominated by the caller"))
            continue

        reason = _skip_reason(record)
        if reason is not None:
            report.skipped.append((record.sample_id, reason))
            continue

        drift = _task_drift(record, task)
        if drift is not None and not allow_task_drift:
            report.skipped.append((record.sample_id, drift))
            continue

        sample = next((s for s in task.samples if s.id == record.sample_id), None)
        if sample is None:
            report.skipped.append(
                (
                    record.sample_id,
                    f"task {task.id!r} no longer has a sample with this id, so there is "
                    "nothing to grade it against",
                )
            )
            continue

        try:
            transcript = _load_transcript(store, record)
        except (KeyError, ValueError) as exc:
            report.skipped.append(
                (record.sample_id, f"transcript unreadable ({type(exc).__name__}: {exc})")
            )
            continue

        verdict = judge.grade(
            task=task,
            sample=sample,
            completion=transcript.completion,
            run_id=run_id,
        )
        report.judge_cost_usd += verdict.cost_usd

        if verdict.score is None:
            report.failed.append((record.sample_id, verdict.error or "judge produced no score"))
        else:
            report.graded.append(record.sample_id)

        if dry_run:
            # A DRY RUN CHANGES NOTHING, INCLUDING THE RECORDS IT HANDS BACK.
            # `regrade_run` documents its results as "ready to persist"; a caller
            # who believes that and persists after a dry run would write grades
            # this function deliberately did not archive, and the store and the
            # database would disagree about a run with nothing to say which is
            # right. The judge was still called and still charged -- see
            # `report.judge_cost_usd` and `report.dry_run`.
            continue

        record.judge_serving_config = verdict.serving_config
        record.judge_usage = verdict.usage
        record.judge_cost_usd = verdict.cost_usd
        # One more attempt on this sample, whatever the verdict. This is the
        # only thing that terminates a retry loop against a judge that stays
        # down: `judge_cost_usd` on the line above was just OVERWRITTEN with
        # this attempt's spend, so earlier attempts' costs are gone and no sum
        # over them is recoverable after the fact.
        #
        # Below the `dry_run` guard, so a dry run does NOT count an attempt.
        # That is deliberate and it is the consistent reading of the guard's own
        # rule -- a dry run changes nothing, including the records it hands back
        # -- but note the asymmetry it creates: a dry run DOES call the judge and
        # IS billed (`report.judge_cost_usd` says so), so repeated dry runs spend
        # money without ever moving toward the bound. `--dry-run` answers "what
        # would this change", not "what would this cost"; a scheduled caller must
        # not use it as a free probe.
        record.judge_attempts += 1

        if verdict.score is None:
            # Left NOT scorable rather than newly marked errored: the sample
            # itself is fine and still gradable, and inventing an `error` here
            # would make a judge outage look like a broken run forever after.
            # A record that ALREADY carried a judge error keeps one -- refreshed
            # to this attempt's -- so the run still reports the outage, and
            # `is_judge_failure` still recognises it as retryable.
            if record.error is not None:
                record.error = verdict.error
        else:
            record.score = verdict.score
            record.scorable = True
            # The grade succeeded. A leftover judge error from the failed
            # attempt would keep this run reporting `partial` forever and would
            # contradict the score sitting next to it.
            record.error = None

        try:
            record.judge_transcript_uri = store.put_json(
                judge_key(run_id, record.sample_id, record.repeat_index),
                verdict.transcript.model_dump(mode="json"),
            )
        except Exception as exc:  # pragma: no cover - storage outage
            log.exception(
                "run %s sample %s: judge transcript archival failed", run_id, record.sample_id
            )
            record.archive_error = (
                f"judge: {type(exc).__name__}: {exc}"
                if not record.archive_error
                else f"{record.archive_error}; judge: {type(exc).__name__}: {exc}"
            )

    if dry_run:
        return report

    # The status is re-derived, not preserved: a run that was `succeeded` with
    # nothing scored is still `succeeded`, but a run that was `partial` because
    # its judge failed becomes `succeeded` once the retry grades it, and the
    # count has to move with the errors it cleared.
    eval_log.status = terminal_status(
        sample_count=len(eval_log.results), error_count=eval_log.error_count
    )

    if report.graded or report.failed:
        store.put_json(eval_log_key(run_id), eval_log.model_dump(mode="json"))

    return report


# --------------------------------------------------------------------------
# The four-way partition: what state is an ungraded sample actually in?
# --------------------------------------------------------------------------
#
# Every ResultRecord is in exactly one of these, and a caller that needs to pick
# work -- a regrade, or a nightly calibration sweep -- has to tell them apart.
# `scorable` alone CANNOT: it answers "was a judge configured when this ran",
# which is a different question from "does this still need grading".
#
# The SQL equivalents are in `docs/llm-judge.md` and pinned by
# `TestTheRowLevelPredicateContract`, because the sweep selects in SQL and these
# two definitions drifting apart is what a nightly bill is made of.


def is_ungradable(record: ResultRecord) -> bool:
    """No completion exists, so no judge can ever grade this.

    The model call died before anything was archived.  Nominating this costs no
    judge money -- :func:`regrade_run` skips it before calling -- but it is
    permanent, so a sweep that keeps selecting it is doing nothing forever.
    """
    return not record.transcript_uri


def is_never_judged(record: ResultRecord) -> bool:
    """A completion nobody has tried to grade yet.  **The nomination class.**

    Note what is NOT used: ``scorable``.  A run with a judge configured records
    ``scorable=True`` even for a sample whose grading then failed, and a run
    without one records ``scorable=False`` even for a sample whose model call
    died.  Neither answers this question.
    """
    return (
        record.score is None
        and bool(record.transcript_uri)
        and not record.judge_transcript_uri
        and record.judge_usage.prompt_tokens == 0
    )


def is_judge_failure(record: ResultRecord) -> bool:
    """True when the COMPLETION is sound and only the GRADE failed.

    The two paths that can produce an ungraded subjective sample record it
    differently, and the difference is not cosmetic:

    ``run_task`` with a judge   ``scorable=True``, ``score=None``,
                                ``error="criterion 'x': ..."`` -- because a run
                                whose grading failed must not report itself
                                ``succeeded``; ``error_count`` is what makes
                                :func:`~ida_core.contracts.terminal_status` call
                                it ``partial``.
    ``run_task`` with no judge  ``scorable=False``, ``score=None``,
                                ``error=None`` -- nothing failed; nothing was
                                attempted.

    Read through ``error`` alone the first shape is indistinguishable from a
    sample whose model call died, so it was skipped as ungradable -- making a
    judge outage **permanently** unrecoverable, which is the exact outcome this
    module was written to prevent.

    The distinction is structural, not a string match: a judge failure has an
    archived ``transcript_uri`` (the completion was bought, scored or not) and
    **evidence that a judge was actually asked** -- tokens it consumed, or the
    transcript of what it said.  A dead *candidate* call has neither: it never
    reaches the judge and never produces a transcript.

    ⚠ ``judge_serving_config is not None`` is the obvious test and is a **trap
    at the SQL layer**, so it is deliberately not used here either -- see
    :func:`is_never_judged` and the predicate contract in ``docs/llm-judge.md``.
    Keeping the Python and SQL definitions on the same columns is the only way
    they stay in agreement.

    **This is the retry class, and a caller that retries it must bound itself.**
    A judge that is down stays down; a sweep that re-nominates this every night
    and a grader that fails every night is a standoff that spends money forever.
    ``judge_cost_usd`` is the LAST attempt's spend, not a running total, so it
    cannot be used as an attempt counter.
    """
    return (
        record.score is None
        and bool(record.transcript_uri)
        and (bool(record.judge_transcript_uri) or record.judge_usage.prompt_tokens > 0)
    )


def _skip_reason(record: ResultRecord) -> str | None:
    """Why this record is not a candidate for regrading, or ``None``."""
    if record.score is not None:
        return (
            "already scored -- regrading would overwrite a verdict with one from a "
            "possibly different judge"
        )
    if is_ungradable(record):
        # Checked before `error`, because it is the reason a failed model call is
        # ungradable: there is no completion, not merely a flag saying so.
        return "no archived transcript, so the completion is gone"
    if is_judge_failure(record) or is_never_judged(record):
        # Either nobody has tried, or the judge tried and could not. Both are
        # gradable now; the second is the one a caller must bound its retries on.
        if record.error is not None and not is_judge_failure(record):
            return "the sample errored when it ran, and the failure was not the judge's"
        return None
    if record.error is not None:
        return "the sample errored when it ran, and the failure was not the judge's"
    if record.scorable:
        return "not a subjective sample"
    return None


def _task_drift(record: ResultRecord, task: TaskSpec) -> str | None:
    """Refusal text when the task has changed since the run, else ``None``."""
    recorded = record.task_content_sha
    current = task.content_sha or None
    if recorded and current and recorded != current:
        return (
            f"task {task.id!r} has changed since this run: recorded content_sha "
            f"{recorded[:12]}..., current {current[:12]}.... Grading an old completion "
            "against an edited rubric produces a number comparable to nothing. Pass "
            "--allow-task-drift if that is genuinely what you want."
        )
    return None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ida_harness.regrade",
        description=(
            "Grade a completed run's subjective samples with an LLM judge, using the "
            "completions already archived in object storage. Calls the JUDGE model and "
            "spends money at its rates; never re-calls the model under test."
        ),
    )
    parser.add_argument("run_id", help="the run to grade, e.g. run_01J...")
    parser.add_argument(
        "--judge-model",
        default=None,
        help="models.yaml key of the judge (default: the IDA_JUDGE_MODEL_KEY setting)",
    )
    parser.add_argument(
        "--allow-task-drift",
        action="store_true",
        help="grade even though the task definition changed since the run (see above)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="call the judge but write nothing back to object storage",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """``python -m ida_harness.regrade <run_id>``.

    Assembled from :class:`ida_core.config.Settings` exactly as the runner
    service is, so it reads the same registry, the same tasks and the same
    bucket the run was written to.  Imports are local because this is the one
    place in the harness that depends on deployment configuration; importing
    :mod:`ida_harness.regrade` for :func:`regrade_run` must not drag settings in.
    """
    from ida_core.artifacts import LocalArtifactStore, S3ArtifactStore
    from ida_core.config import get_settings
    from ida_core.registry import load_registry
    from ida_harness.judge import build_judge

    args = _build_parser().parse_args(argv)
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")

    if settings.artifact_backend == "local":
        store: ArtifactStore = LocalArtifactStore(
            settings.artifact_local_root, bucket=settings.s3_bucket
        )
    else:
        store = S3ArtifactStore.from_settings(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )

    registry = load_registry(settings.resolved_models_file())
    catalog = TaskCatalog.from_directory(settings.resolved_tasks_dir())
    judge_key_name = args.judge_model or settings.judge_model_key

    with build_judge(registry, judge_key_name) as judge:
        report = regrade_run(
            run_id=args.run_id,
            store=store,
            judge=judge,
            catalog=catalog,
            allow_task_drift=args.allow_task_drift,
            dry_run=args.dry_run,
        )

    print(report.summary())
    for sample_id, reason in report.failed:
        print(f"  failed  {sample_id}: {reason}")
    for sample_id, reason in report.skipped:
        print(f"  skipped {sample_id}: {reason}")
    if args.dry_run:
        print("  (dry run: nothing was written back)")

    # Non-zero when the judge ran and could not grade: a scheduled regrade that
    # silently exits 0 having graded nothing is how a broken judge goes unnoticed.
    return 1 if report.failed else 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
