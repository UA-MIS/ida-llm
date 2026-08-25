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
"""

from __future__ import annotations

import argparse
import logging
import sys
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

    @property
    def mean_score(self) -> float | None:
        return self.eval_log.mean_score

    def summary(self) -> str:
        return (
            f"run {self.run_id}: graded {len(self.graded)}, failed {len(self.failed)}, "
            f"skipped {len(self.skipped)}, judge cost ${self.judge_cost_usd:.6f}, "
            f"mean={self.mean_score}"
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
) -> RegradeReport:
    """Grade every ungraded subjective sample of a completed run.

    Exactly one of ``task`` or ``catalog`` must be given -- the task definition
    is not recoverable from the eval log (only its hash is), and grading needs
    the rubric.

    Only samples that are ``scorable=False`` **and** carry no ``error`` are
    touched.  An errored sample has no completion to grade; an already-scored one
    is left exactly as it was, so running this twice cannot quietly regrade a
    run under a different judge and overwrite the first verdict.

    ``dry_run`` does everything except write to the store -- including calling
    the judge, which costs money.  It answers "what would this change", not
    "what would this cost".
    """
    eval_log = load_eval_log(store, run_id)

    if task is None:
        if catalog is None:
            raise ValueError("regrade_run needs either task= or catalog=")
        task = catalog.get(eval_log.task_id)

    report = RegradeReport(run_id=run_id, eval_log=eval_log)

    if task.rubric is None:
        report.skipped.append(("*", f"task {task.id!r} has no rubric; nothing to judge against"))
        return report

    for record in eval_log.results:
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
        record.judge_serving_config = verdict.serving_config
        record.judge_usage = verdict.usage
        record.judge_cost_usd = verdict.cost_usd
        report.judge_cost_usd += verdict.cost_usd

        if verdict.score is None:
            # Left NOT scorable rather than marked errored: the sample itself is
            # fine and still gradable, and flipping it to `error` would make a
            # judge outage look like a broken run forever after.
            report.failed.append((record.sample_id, verdict.error or "judge produced no score"))
        else:
            record.score = verdict.score
            record.scorable = True
            report.graded.append(record.sample_id)

        if not dry_run:
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

    # The status is re-derived, not preserved: a run that was `succeeded` with
    # nothing scored is still `succeeded`, but if regrading turned samples into
    # errors the count has to move with them.
    eval_log.status = terminal_status(
        sample_count=len(eval_log.results), error_count=eval_log.error_count
    )

    if not dry_run and (report.graded or report.failed):
        store.put_json(eval_log_key(run_id), eval_log.model_dump(mode="json"))

    return report


def _skip_reason(record: ResultRecord) -> str | None:
    """Why this record is not a candidate for regrading, or ``None``."""
    if record.error is not None:
        return "the sample errored when it ran; there is no completion to grade"
    if record.score is not None:
        return (
            "already scored -- regrading would overwrite a verdict with one from a "
            "possibly different judge"
        )
    if record.scorable:
        return "not a subjective sample"
    if not record.transcript_uri:
        return "no archived transcript, so the completion is gone"
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
