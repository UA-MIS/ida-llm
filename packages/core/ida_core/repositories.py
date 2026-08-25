"""Persistence layer: the *only* code that maps contracts <-> rows.

Both the API and the runner import these functions.  Keeping the mapping in one
place is what makes "the serving config is copied by value onto every result"
(D-1) a property of the system rather than a convention two services each
remember to honour.
"""

from __future__ import annotations

from sqlalchemy import func, select
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
        task_content_sha=row.task_content_sha,
        score=score,
        scorable=row.scorable,
        cached=row.cached,
        usage=TokenUsage(
            prompt_tokens=row.prompt_tokens, completion_tokens=row.completion_tokens
        ),
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


def list_results_for_run(session: Session, run_id: str) -> list[ResultRow]:
    """All results for a run, in stable ``sample_id`` order."""
    stmt = (
        select(ResultRow)
        .where(ResultRow.run_id == run_id)
        .order_by(ResultRow.sample_id.asc(), ResultRow.repeat_index.asc())
    )
    return list(session.scalars(stmt))
