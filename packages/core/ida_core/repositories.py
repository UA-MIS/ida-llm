"""Persistence layer: the *only* code that maps contracts <-> rows.

Both the API and the runner import these functions.  Keeping the mapping in one
place is what makes "the serving config is copied by value onto every result"
(D-1) a property of the system rather than a convention two services each
remember to honour.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy import or_ as sa_or
from sqlalchemy.orm import Session

from ida_core.contracts import (
    CriterionScore,
    ResultRecord,
    RunRecord,
    RunStatus,
    Score,
    ScorerKind,
    ServingConfig,
    TokenUsage,
)
from ida_core.db import ResultRow, RunRow, utcnow

log = logging.getLogger(__name__)

# ----------------------------------------------------------------- runs ----


def run_row_to_record(row: RunRow) -> RunRecord:
    """Row -> contract.  Total: every column has a home in the contract."""
    return RunRecord(
        id=row.id,
        status=RunStatus(row.status),
        task_id=row.task_id,
        model_key=row.model_key,
        label=row.label,
        sweep_id=row.sweep_id,
        task_git_sha=row.task_git_sha,
        task_content_sha=row.task_content_sha,
        harness_version=row.harness_version,
        serving_config=(
            ServingConfig.model_validate(row.serving_config) if row.serving_config else None
        ),
        sample_count=row.sample_count,
        scored_count=row.scored_count,
        error_count=row.error_count,
        mean_score=row.mean_score,
        total_usage=TokenUsage(
            prompt_tokens=row.prompt_tokens, completion_tokens=row.completion_tokens
        ),
        total_cost_usd=row.total_cost_usd,
        error=row.error,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def create_run(session: Session, record: RunRecord) -> RunRow:
    """Insert a fresh (usually ``queued``) run.  The caller owns the id."""
    row = RunRow(
        id=record.id,
        status=record.status.value,
        task_id=record.task_id,
        model_key=record.model_key,
        label=record.label,
        sweep_id=record.sweep_id,
        task_git_sha=record.task_git_sha,
        task_content_sha=record.task_content_sha,
        harness_version=record.harness_version,
        serving_config=(
            record.serving_config.model_dump(mode="json") if record.serving_config else None
        ),
        sample_count=record.sample_count,
        scored_count=record.scored_count,
        error_count=record.error_count,
        mean_score=record.mean_score,
        prompt_tokens=record.total_usage.prompt_tokens,
        completion_tokens=record.total_usage.completion_tokens,
        total_cost_usd=record.total_cost_usd,
        error=record.error,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )
    session.add(row)
    return row


def get_run(session: Session, run_id: str) -> RunRow | None:
    return session.get(RunRow, run_id)


def list_runs(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    status: RunStatus | None = None,
    task_id: str | None = None,
    model_key: str | None = None,
    sweep_id: str | None = None,
) -> list[RunRow]:
    """Newest-first page of runs, optionally filtered.

    ``limit`` is clamped by the caller (the API caps it at 200) -- this function
    trusts its arguments.
    """
    stmt = select(RunRow).order_by(RunRow.created_at.desc(), RunRow.id.desc())
    if status is not None:
        stmt = stmt.where(RunRow.status == status.value)
    if task_id is not None:
        stmt = stmt.where(RunRow.task_id == task_id)
    if model_key is not None:
        stmt = stmt.where(RunRow.model_key == model_key)
    if sweep_id is not None:
        stmt = stmt.where(RunRow.sweep_id == sweep_id)
    return list(session.scalars(stmt.limit(limit).offset(offset)))


def count_runs(
    session: Session,
    *,
    status: RunStatus | None = None,
    task_id: str | None = None,
    model_key: str | None = None,
    sweep_id: str | None = None,
) -> int:
    """Total rows matching the same filters :func:`list_runs` accepts (A11).

    Returned alongside the page so a UI can render "page 3 of 12" and know when
    it has reached the end, instead of probing with an extra request that comes
    back short.
    """
    stmt = select(func.count()).select_from(RunRow)
    if status is not None:
        stmt = stmt.where(RunRow.status == status.value)
    if task_id is not None:
        stmt = stmt.where(RunRow.task_id == task_id)
    if model_key is not None:
        stmt = stmt.where(RunRow.model_key == model_key)
    if sweep_id is not None:
        stmt = stmt.where(RunRow.sweep_id == sweep_id)
    return int(session.scalar(stmt) or 0)


def mark_run_running(session: Session, run_id: str, serving_config: ServingConfig) -> RunRow:
    """Claim a run.  Records the resolved serving config (D-1) at claim time."""
    row = session.get(RunRow, run_id)
    if row is None:
        raise KeyError(run_id)
    row.status = RunStatus.RUNNING.value
    row.started_at = utcnow()
    row.serving_config = serving_config.model_dump(mode="json")
    return row


def requeue_run(session: Session, run_id: str) -> RunRow | None:
    """Put a claimed-but-unfinished run back to ``queued``.

    Called when a dead runner's claim is recovered.  A recovered run left
    ``running`` is precisely the bug this pass exists to fix: the message is on
    the queue again, so the row must say "waiting", not "in progress".

    Returns ``None`` for a run that is missing or already terminal -- both are
    normal races (the runner may have finished and acked between the heartbeat
    lapsing and this call), not errors.
    """
    row = session.get(RunRow, run_id)
    if row is None or row.status not in (RunStatus.RUNNING.value, RunStatus.QUEUED.value):
        return None
    row.status = RunStatus.QUEUED.value
    row.started_at = None
    row.error = None
    return row


def fail_run(session: Session, run_id: str, error: str) -> RunRow | None:
    """Close out a run as ``failed`` with a readable reason, rollup untouched.

    The reaper's terminal write.  Deliberately narrower than :func:`finish_run`,
    which needs a whole :class:`RunRecord`: the reaper has no results to report,
    only the honest statement that nobody is going to finish this run.  Leaves
    ``sample_count``/``error_count`` as they are rather than inventing zeros
    that would read as "measured, and it was empty".

    Returns ``None`` if the run is missing or already terminal; a run that
    finished while the reaper was deciding must not be overwritten.
    """
    row = session.get(RunRow, run_id)
    if row is None or row.status not in (RunStatus.RUNNING.value, RunStatus.QUEUED.value):
        return None
    row.status = RunStatus.FAILED.value
    row.error = error
    row.finished_at = utcnow()
    return row


def list_stale_running_runs(
    session: Session, *, started_before: datetime, limit: int = 200
) -> list[RunRow]:
    """Runs stuck ``running`` since before ``started_before``, oldest first.

    ``started_at IS NULL`` is included: a row marked ``running`` without a start
    time is a partially-applied claim, which is stuck in exactly the same way.

    Bounded by ``limit`` so one reaper pass cannot turn into an unbounded
    transaction; the next pass picks up the rest.  Callers that bound their work
    should say so in a log line rather than let it look like "that was all".
    """
    stmt = (
        select(RunRow)
        .where(RunRow.status == RunStatus.RUNNING.value)
        .where(sa_or(RunRow.started_at.is_(None), RunRow.started_at < started_before))
        .order_by(RunRow.started_at.asc().nulls_first(), RunRow.created_at.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def finish_run(session: Session, record: RunRecord) -> RunRow:
    """Write the terminal state + rollup of a finished run."""
    row = session.get(RunRow, record.id)
    if row is None:
        raise KeyError(record.id)
    row.status = record.status.value
    row.sample_count = record.sample_count
    row.scored_count = record.scored_count
    row.error_count = record.error_count
    row.mean_score = record.mean_score
    row.task_content_sha = record.task_content_sha or row.task_content_sha
    # ⚠ THE BUILD THAT EXECUTED IT, NOT THE ONE THAT ENQUEUED IT.
    #
    # This line was MISSING, and its absence was invisible: the worker computes
    # `record.harness_version` from the eval log and this function silently
    # dropped it, so the value that survived was whatever the api or the sweep
    # stamped at ENQUEUE time. For a field documented as "the version that
    # executed the run" that is the wrong build by construction whenever the two
    # differ -- which is exactly what a rolling deploy does: pods on the old
    # image enqueue, pods on the new image execute, and every row credits the
    # code that merely queued the work.
    #
    # It read as correct because the two builds usually ARE the same, so the
    # dropped write and a working write produce identical rows on a quiet
    # cluster. `services/runner/tests/test_worker.py::
    # TestExecutedRunsRecordTheBuildThatRanThem` is what makes the difference
    # observable.
    #
    # `or row.harness_version` guards a blank rather than letting it erase a good
    # value -- the same idiom as `task_content_sha` above, and the column is NOT
    # NULL.
    row.harness_version = record.harness_version or row.harness_version
    row.prompt_tokens = record.total_usage.prompt_tokens
    row.completion_tokens = record.total_usage.completion_tokens
    row.total_cost_usd = record.total_cost_usd
    row.error = record.error
    row.started_at = record.started_at or row.started_at
    row.finished_at = record.finished_at or utcnow()
    if record.serving_config is not None:
        row.serving_config = record.serving_config.model_dump(mode="json")
    return row


# -------------------------------------------------------------- results ----


def result_row_to_record(row: ResultRow) -> ResultRecord:
    """Row -> contract, reassembling the flattened score columns."""
    score = None
    if row.scorer is not None and row.score_value is not None:
        score = Score(
            scorer=ScorerKind(row.scorer),
            value=row.score_value,
            # `passed` is nullable now (B6): None means "this scorer makes no
            # pass/fail claim", which bool() would silently flatten to False.
            passed=row.passed,
            explanation=row.score_explanation or "",
            criteria=[CriterionScore.model_validate(c) for c in (row.score_criteria or [])],
            details=row.score_details or {},
        )
    return ResultRecord(
        id=row.id,
        run_id=row.run_id,
        task_id=row.task_id,
        sample_id=row.sample_id,
        repeat_index=row.repeat_index,
        model_key=row.model_key,
        serving_config=ServingConfig.model_validate(row.serving_config),
        judge_serving_config=(
            ServingConfig.model_validate(row.judge_serving_config)
            if row.judge_serving_config
            else None
        ),
        judge_usage=TokenUsage(
            prompt_tokens=row.judge_prompt_tokens,
            completion_tokens=row.judge_completion_tokens,
        ),
        judge_cost_usd=row.judge_cost_usd,
        judge_attempts=row.judge_attempts,
        judge_transcript_uri=row.judge_transcript_uri,
        task_content_sha=row.task_content_sha,
        score=score,
        scorable=row.scorable,
        cached=row.cached,
        usage=TokenUsage(prompt_tokens=row.prompt_tokens, completion_tokens=row.completion_tokens),
        cost_usd=row.cost_usd,
        latency_ms=row.latency_ms,
        transcript_uri=row.transcript_uri,
        archive_error=row.archive_error,
        error=row.error,
        created_at=row.created_at,
    )


def insert_results(session: Session, records: list[ResultRecord]) -> list[ResultRow]:
    """Bulk-insert scored samples.

    The score is *flattened* into columns (``scorer``, ``score_value``,
    ``passed``) rather than stored as JSON, because those are the columns the
    recommender will aggregate over.  Everything non-aggregable stays in
    ``score_details``.
    """
    rows = [
        ResultRow(
            id=record.id,
            run_id=record.run_id,
            task_id=record.task_id,
            sample_id=record.sample_id,
            repeat_index=record.repeat_index,
            model_key=record.model_key,
            serving_config=record.serving_config.model_dump(mode="json"),
            judge_serving_config=(
                record.judge_serving_config.model_dump(mode="json")
                if record.judge_serving_config
                else None
            ),
            judge_prompt_tokens=record.judge_usage.prompt_tokens,
            judge_completion_tokens=record.judge_usage.completion_tokens,
            judge_cost_usd=record.judge_cost_usd,
            judge_attempts=record.judge_attempts,
            judge_transcript_uri=record.judge_transcript_uri,
            task_content_sha=record.task_content_sha,
            scorer=record.score.scorer.value if record.score else None,
            score_value=record.score.value if record.score else None,
            passed=record.score.passed if record.score else None,
            score_explanation=record.score.explanation if record.score else None,
            score_criteria=(
                [c.model_dump(mode="json") for c in record.score.criteria]
                if record.score and record.score.criteria
                else None
            ),
            score_details=record.score.details if record.score else None,
            scorable=record.scorable,
            cached=record.cached,
            prompt_tokens=record.usage.prompt_tokens,
            completion_tokens=record.usage.completion_tokens,
            cost_usd=record.cost_usd,
            latency_ms=record.latency_ms,
            transcript_uri=record.transcript_uri,
            archive_error=record.archive_error,
            error=record.error,
            created_at=record.created_at,
        )
        for record in records
    ]
    session.add_all(rows)
    return rows


def list_results_for_run(
    session: Session,
    run_id: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[ResultRow]:
    """Results for a run, in stable ``(sample_id, repeat_index)`` order.

    ``limit=None`` -- the default -- returns every row, which is what the runner
    and the tests want. The API passes an explicit page so that one run cannot
    produce an unbounded response: a sweep with repeats over a large task is one
    row per (sample, repetition), and nothing else caps that.

    The ordering is total and deterministic, which is what makes paging over it
    correct: a page boundary that fell inside a group of equal sort keys could
    otherwise repeat or skip a row between requests.
    """
    stmt = (
        select(ResultRow)
        .where(ResultRow.run_id == run_id)
        .order_by(ResultRow.sample_id.asc(), ResultRow.repeat_index.asc())
    )
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


# ---------------------------------------------------------------- sweeps ----
# Read-only helpers the scheduled sweeps (ida_runner.sweeps) plan against. They
# live here, not in the runner, because they are contracts <-> rows mapping and
# this module is the only place that is allowed to be.


def existing_run_keys(
    session: Session,
    *,
    statuses: Sequence[RunStatus],
    model_keys: Sequence[str] | None = None,
    created_after: datetime | None = None,
) -> set[tuple[str, str, str | None]]:
    """``(task_id, model_key, task_content_sha)`` for every run in ``statuses``.

    The dedupe index a sweep plans against.  ``task_content_sha`` is part of the
    key on purpose (B8): editing a task changes its content sha, which makes the
    old measurement stale and the pair legitimately re-runnable.  Comparing on
    ``(task_id, model_key)`` alone would mean a task could be rewritten and never
    re-measured, and the dashboard would keep showing the previous version's
    numbers under the new task's name.

    ``None`` shas are returned as-is rather than dropped.  A row whose sha is
    NULL predates content hashing; it will simply never match a candidate (whose
    sha is non-NULL), so such a pair is re-run once and thereafter deduped
    normally.  Silently treating NULL as "matches anything" would suppress the
    re-measurement that backfills it.

    ``created_after`` bounds the query to recent rows.  Callers use it for the
    ``queued``/``running`` half of the index, and the bound is LOAD-BEARING: an
    unbounded "is it in flight?" question answered from a row alone treats a run
    that nothing will ever process as one that is about to be, which suppresses
    the pair for good.  See the note above :func:`fail_run` in the sweep's
    enqueue path for the failure this exists to stop.

    A single ``SELECT DISTINCT`` rather than a query per candidate: a sweep asks
    this once and then does set membership in Python, so planning is one round
    trip regardless of how far the registry x catalog cross product grows.
    """
    if not statuses:
        return set()
    stmt = select(RunRow.task_id, RunRow.model_key, RunRow.task_content_sha).where(
        RunRow.status.in_([s.value for s in statuses])
    )
    if model_keys is not None:
        if not model_keys:
            return set()
        stmt = stmt.where(RunRow.model_key.in_(list(model_keys)))
    if created_after is not None:
        stmt = stmt.where(RunRow.created_at >= created_after)
    return {
        (task_id, model_key, sha) for task_id, model_key, sha in session.execute(stmt.distinct())
    }


def models_with_any_run(
    session: Session,
    *,
    statuses: Sequence[RunStatus],
) -> set[str]:
    """Model keys that have at least one run in ``statuses``.

    What ``ida-sweep model-sweep`` diffs the registry against: a model absent
    from this set has never been measured (or never successfully), which is the
    definition of "new" that sweep acts on.  Deliberately not "has a run for
    every current task" -- that is the nightly rebenchmark's job, and conflating
    the two would make the cheap targeted sweep re-enqueue the whole suite.
    """
    if not statuses:
        return set()
    stmt = select(RunRow.model_key).where(RunRow.status.in_([s.value for s in statuses])).distinct()
    return set(session.scalars(stmt))


def list_ungraded_subjective_results(
    session: Session, *, limit: int = 500, max_judge_attempts: int = 3
) -> list[ResultRow]:
    """Samples a judge could still usefully grade, oldest first.

    This is the SQL half of the four-way partition documented in
    ``docs/llm-judge.md`` and implemented in Python by
    :func:`ida_harness.regrade.is_never_judged` / ``is_judge_failure`` /
    ``is_ungradable``.  The two definitions select the same rows on purpose: the
    sweep picks candidates in SQL and the grader decides what it will actually
    grade in Python, and when those disagree the failure is not a crash but a
    **standoff** -- nominated nightly, declined nightly, visible only as a bill.

    The predicate is three clauses, and each one excludes a different class::

        score_value IS NULL           excludes *graded*      -- already done
        transcript_uri IS NOT NULL    excludes *ungradable*  -- no completion exists,
                                                                so no judge can ever
                                                                succeed on it
        judge_attempts < N            excludes *exhausted*   -- tried enough times

    What is left is exactly *never judged* (``judge_attempts = 0``) plus the
    still-affordable part of *judge failed*.

    ⚠ ``scorable`` IS NOT IN THE PREDICATE, AND ITS ABSENCE IS THE FIX.  It
    records whether a judge was *configured when the sample ran*, which is a
    different question from whether the sample still needs grading, and using it
    was wrong in **both** directions at once:

    * it **over-selected** -- ``scorable = FALSE`` also matches a sample whose
      model call died and which therefore has no completion to grade, nominated
      forever and able to succeed never;
    * it **under-selected** -- a sample whose *online* grading failed is written
      ``scorable = TRUE`` (the run must not report itself ``succeeded``), so it
      was never re-nominated.  Silent, permanent non-retry, and it arrived the
      moment the runner service was wired to a judge.  That is this change.

    ⚠ ``judge_serving_config IS NULL`` IS A TRAP AND IS DELIBERATELY UNUSED.
    SQLAlchemy's ``JSON`` column stores Python ``None`` as the JSON literal
    ``'null'``, not SQL ``NULL``, so that clause matches nothing, ever -- while
    the ORM reads the same row back as ``None``.  Python and SQL disagree about
    the identical row and neither complains.  The columns above are genuinely
    nullable or numeric, which is why they are the ones used.  Pinned by
    ``TestTheRowLevelPredicateContract``.

    ``max_judge_attempts`` is the money-pump bound.  The *judge failed* class is
    retryable by design -- that is what stops a judge outage making a sample
    permanently ungradable -- so an unbounded retrier is a standing charge
    against a judge that stays down.  The caller passes
    ``IDA_SWEEP_JUDGE_MAX_ATTEMPTS``; the default here matches
    :attr:`ida_core.config.Settings.sweep_judge_max_attempts` so a direct caller
    is bounded even if it forgets to ask.  ``0`` disables nomination entirely,
    which is a coherent way to park the sweep without editing the CronJob.

    Oldest first so a bounded pass makes progress through the backlog instead of
    re-examining the same head of it.  Bounded by ``limit`` for the same reason
    :func:`list_stale_running_runs` is: one pass must not become an unbounded
    transaction.  A caller that hits the bound should say so in its log line
    rather than let a truncated pass read as "that was all".

    ⚠ SUBJECTIVE-NESS IS NOT DECIDABLE HERE.  ``results`` stores ``task_id``, not
    task *kind*, so no SQL predicate can tell a subjective sample from a
    verifiable one whose score is missing for some other reason.  The caller
    filters on kind against the task catalog -- see
    ``ida_runner.sweeps.run_judge_calibration`` -- which is cheap because a
    grader skips a task with no rubric before spending anything.  The name is
    kept for continuity with the sweep and the docs that cite it.
    """
    stmt = (
        select(ResultRow)
        .where(ResultRow.score_value.is_(None))
        .where(ResultRow.transcript_uri.is_not(None))
        .where(ResultRow.judge_attempts < max_judge_attempts)
        .order_by(ResultRow.created_at.asc(), ResultRow.id.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def persist_regraded_results(session: Session, records: list[ResultRecord]) -> int:
    """Write grades produced by a retroactive regrade back onto their rows.

    Returns how many rows were updated.

    ``ida_harness.regrade.regrade_run`` returns records "ready to persist" and
    writes only to object storage, because the harness has no database.  The
    service that owns ``results`` has to do the write, and that is this package.
    Until it did, a regrade updated the archived eval log while the UI kept
    showing the original blank -- and, more sharply, ``judge_attempts`` never
    moved, so the bound in :func:`list_ungraded_subjective_results` could never
    engage and the money pump it exists to stop stayed open.

    Only the judge-owned columns are written.  The candidate model's usage,
    cost, latency and transcript describe a call that happened during the
    original run and did not happen again; rewriting them from a record that
    merely carried them along would silently restate the run's own history.  For
    the same reason a row that has vanished is skipped rather than re-inserted:
    a regrade grades what a run produced, and it is not a path by which a
    deleted result may come back.
    """
    updated = 0
    for record in records:
        row = session.get(ResultRow, record.id)
        if row is None:
            # The run was deleted between nomination and write-back. Nothing to
            # update, and inventing the row would resurrect deleted evidence.
            log.warning("result %s vanished before regrade write-back; skipped", record.id)
            continue
        row.judge_serving_config = (
            record.judge_serving_config.model_dump(mode="json")
            if record.judge_serving_config
            else None
        )
        row.judge_prompt_tokens = record.judge_usage.prompt_tokens
        row.judge_completion_tokens = record.judge_usage.completion_tokens
        row.judge_cost_usd = record.judge_cost_usd
        row.judge_attempts = record.judge_attempts
        row.judge_transcript_uri = record.judge_transcript_uri
        row.scorer = record.score.scorer.value if record.score else None
        row.score_value = record.score.value if record.score else None
        row.passed = record.score.passed if record.score else None
        row.score_explanation = record.score.explanation if record.score else None
        row.score_criteria = (
            [c.model_dump(mode="json") for c in record.score.criteria]
            if record.score and record.score.criteria
            else None
        )
        row.score_details = record.score.details if record.score else None
        row.scorable = record.scorable
        # `error` moves with the grade: regrade_run clears it when a retry
        # succeeds (so the run stops reporting `partial` forever) and refreshes
        # it when a retry fails. Leaving the old string behind would contradict
        # the score now sitting next to it.
        row.error = record.error
        row.archive_error = record.archive_error
        updated += 1
    return updated


def count_results_for_run(session: Session, run_id: str) -> int:
    """How many results the run has, ignoring pagination.

    Returned alongside the page for the same reason :func:`count_runs` is (A11):
    without it a client cannot tell a genuinely empty run from a page past the
    end, and the UI classifies those two very differently -- an empty result set
    reads as "all errored".
    """
    stmt = select(func.count()).select_from(ResultRow).where(ResultRow.run_id == run_id)
    return int(session.scalar(stmt) or 0)
