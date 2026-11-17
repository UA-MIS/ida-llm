"""``/admin/runs`` and ``/admin/sweeps``: launch, estimate, watch, cancel (design 5.6).

SPEND GUARDS, IN THE ORDER THEY APPLY
-------------------------------------
1. **Hard caps** -- the sweeps' own ``IDA_SWEEP_MAX_RUNS`` /
   ``IDA_SWEEP_MAX_SAMPLES``, same values, same meaning.  Over either ->
   422 ``cap_exceeded``; there is no override from the console.
2. **Typed confirmation** -- when the HIGH estimate is over
   ``IDA_ADMIN_RUN_MAX_ESTIMATED_USD`` ($25), or any selected model carries a
   ``IDA_SWEEP_EXCLUDE_TAGS`` tag (``testing-only``: the $25-capped key), the
   launch must carry ``confirm_spend_usd >= est_usd_high`` or it is 409
   ``spend_confirmation_required``.  The console makes the admin type the
   figure.  A UI should make overspending harder than the CLI does, not easier.
3. The provider-side hard caps still apply beneath all of this.

The estimate is deliberately the HIGH figure: per pair, the mean tokens per
sample over that pair's last 5 succeeded runs (``history``), or -- with no
history -- prompt ~ characters / 4 and completion = the full ``max_tokens``
(``ceiling``).  Judge cost is added for subjective tasks when a judge is set.

CANCEL (AD-12).  A queued run is cancelled outright, conditioned on
``status='queued'`` so it cannot race a runner's claim; the runner later sees a
terminal row and acks the message.  A running run gets ``cancel_requested_at``;
the worker checks between samples, stops calling the provider, records what it
already spent, and lands the run on ``cancelled``.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select, update

from ida_api.admin.deps import Admin, admin_error
from ida_api.admin.schemas import (
    AdminEnqueueResponse,
    AdminRunDetail,
    AdminRunList,
    AdminRunRecord,
    EstimateCaps,
    EstimatePair,
    RunEstimate,
    RunLaunchInput,
    SweepDetail,
    SweepList,
    SweepSummary,
)
from ida_api.admin.service import admin_write, not_found
from ida_api.deps import AppContext, get_context
from ida_api.runs_service import enqueue, validate_targets
from ida_core import artifacts as artifact_paths
from ida_core.contracts import TERMINAL_RUN_STATUSES, RunStatus, TaskKind
from ida_core.db import RunRow, session_scope, utcnow
from ida_core.gitmeta import build_identity
from ida_core.repositories import (
    count_results_for_run,
    list_results_for_run,
    result_row_to_record,
    run_row_to_record,
)

router = APIRouter(tags=["admin: runs"])

HARNESS_VERSION = build_identity()
"""Stamped on the rows an admin launch enqueues -- resolved once at import, for
the reason ``ida_api.app.HARNESS_VERSION`` gives."""

MAX_ADMIN_PAGE = 200
HISTORY_RUNS = 5
"""How many of a pair's most recent succeeded runs the estimate averages."""
CHARS_PER_TOKEN = 4
JUDGE_COMPLETION_TOKENS = 512
"""Ceiling for one judge reply (one call per rubric criterion)."""


# ─────────────────────────────────────────────────────────────── helpers ──


def _admin_record(row: RunRow) -> AdminRunRecord:
    return AdminRunRecord(
        **run_row_to_record(row).model_dump(),
        launched_by=row.launched_by,
        config_revision=row.config_revision,
        cancel_requested_at=row.cancel_requested_at,
    )


def _encode_cursor(at: datetime, key: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([at.isoformat(), key]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        at, key = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(at), str(key)
    except Exception:
        raise admin_error(422, "validation_failed", "malformed cursor") from None


def _http_to_admin(exc: HTTPException):
    code = "not_found" if exc.status_code == 404 else "conflict"
    return admin_error(exc.status_code, code, str(exc.detail))


def _expand(ctx: AppContext, body: RunLaunchInput) -> list[str]:
    """``task_ids`` UNION every live task of ``family_keys``, in a stable order."""
    catalog = ctx.catalog
    task_ids: list[str] = []
    for family in body.family_keys:
        members = [s.id for s in catalog.all() if s.id.split("/", 1)[0] == family]
        if not members:
            raise admin_error(404, "not_found", f"no live tasks in family {family!r}")
        task_ids.extend(members)
    task_ids.extend(body.task_ids)
    return list(dict.fromkeys(task_ids))


def _history(session, task_id: str, model_key: str) -> tuple[float, float] | None:
    rows = session.execute(
        select(RunRow.prompt_tokens, RunRow.completion_tokens, RunRow.sample_count)
        .where(
            RunRow.task_id == task_id,
            RunRow.model_key == model_key,
            RunRow.status == RunStatus.SUCCEEDED.value,
            RunRow.sample_count > 0,
        )
        .order_by(RunRow.created_at.desc())
        .limit(HISTORY_RUNS)
    ).all()
    samples = sum(r[2] for r in rows)
    if not samples:
        return None
    return sum(r[0] for r in rows) / samples, sum(r[1] for r in rows) / samples


def _price(prompt: float, completion: float, cost) -> float:
    return (prompt * cost.input_usd_per_mtok + completion * cost.output_usd_per_mtok) / 1e6


def build_estimate(ctx: AppContext, body: RunLaunchInput) -> tuple[RunEstimate, list[str]]:
    """The estimate, plus the expanded task ids (so launch does not re-expand)."""
    task_ids = _expand(ctx, body)
    try:
        validate_targets(ctx, task_ids, body.model_keys)
    except HTTPException as exc:
        raise _http_to_admin(exc) from None
    settings = ctx.settings
    registry, catalog = ctx.registry, ctx.catalog
    judge = None
    if settings.judge_model_key:
        try:
            judge = registry.get(settings.judge_model_key)
        except KeyError:
            judge = None

    pairs: list[EstimatePair] = []
    warnings: list[str] = []
    includes_judge = False
    with session_scope(ctx.session_factory) as session:
        for task_id in task_ids:
            spec = catalog.get(task_id)
            n = len(spec.samples)
            for model_key in body.model_keys:
                entry = registry.get(model_key)
                sampling = body.sampling_override or entry.serving.sampling
                history = _history(session, task_id, model_key)
                if history is not None:
                    basis = "history"
                    prompt, completion = history[0] * n, history[1] * n
                else:
                    basis = "ceiling"
                    chars = sum(len(spec.system_prompt or "") + len(s.input) for s in spec.samples)
                    prompt = chars / CHARS_PER_TOKEN
                    completion = sampling.max_tokens * n
                usd = _price(prompt, completion, entry.cost)
                if spec.kind is TaskKind.SUBJECTIVE and judge is not None:
                    includes_judge = True
                    criteria = len(spec.rubric.criteria) if spec.rubric else 1
                    judge_prompt = (prompt + completion) * criteria
                    usd += _price(judge_prompt, JUDGE_COMPLETION_TOKENS * n * criteria, judge.cost)
                pairs.append(
                    EstimatePair(
                        task_id=task_id,
                        model_key=model_key,
                        samples=n,
                        est_usd_high=round(usd, 4),
                        basis=basis,
                    )
                )
    runs = len(pairs)
    samples = sum(p.samples for p in pairs)
    total = round(sum(p.est_usd_high for p in pairs), 4)
    caps = EstimateCaps(
        max_runs=settings.sweep_max_runs,
        max_samples=settings.sweep_max_samples,
        max_estimated_usd=settings.admin_run_max_estimated_usd,
    )
    if runs > caps.max_runs:
        warnings.append(f"{runs} runs is over the cap of {caps.max_runs}; this cannot launch")
    if samples > caps.max_samples:
        warnings.append(
            f"{samples} samples is over the cap of {caps.max_samples}; this cannot launch"
        )
    flagged = sorted(
        m
        for m in body.model_keys
        if settings.sweep_exclude_tag_set & {t.lower() for t in registry.get(m).tags}
    )
    if flagged:
        warnings.append(
            f"{flagged} are held back from sweeps (testing-only budget); confirm to spend"
        )
    if any(p.basis == "ceiling" for p in pairs):
        warnings.append(
            "some pairs have no history; their estimate assumes every reply uses max_tokens"
        )
    if includes_judge:
        warnings.append("includes an approximate judge cost for subjective tasks")
    estimate = RunEstimate(
        runs=runs,
        samples=samples,
        pairs=pairs,
        est_usd_high=total,
        includes_judge=includes_judge,
        warnings=warnings,
        caps=caps,
        needs_confirmation=total > caps.max_estimated_usd or bool(flagged),
    )
    return estimate, task_ids


# ──────────────────────────────────────────────────────────── launch ──


@router.post("/runs/estimate", response_model=RunEstimate)
def estimate_runs(
    body: RunLaunchInput, _: Admin, ctx: AppContext = Depends(get_context)
) -> RunEstimate:
    """No write.  The launcher calls it live (debounced)."""
    return build_estimate(ctx, body)[0]


@router.post("/runs", response_model=AdminEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def launch_runs(
    body: RunLaunchInput, admin: Admin, ctx: AppContext = Depends(get_context)
) -> AdminEnqueueResponse:
    """422 ``cap_exceeded`` over the sweep caps; 409
    ``spend_confirmation_required`` until ``confirm_spend_usd`` covers the
    estimate when it is over the ceiling or touches a testing-only model."""
    estimate, task_ids = build_estimate(ctx, body)
    if estimate.runs > estimate.caps.max_runs or estimate.samples > estimate.caps.max_samples:
        raise admin_error(
            422,
            "cap_exceeded",
            f"{estimate.runs} run(s) / {estimate.samples} sample(s) is over the cap of "
            f"{estimate.caps.max_runs} / {estimate.caps.max_samples}",
        )
    if estimate.needs_confirmation and (
        body.confirm_spend_usd is None or body.confirm_spend_usd < estimate.est_usd_high
    ):
        raise admin_error(
            409,
            "spend_confirmation_required",
            f"this launch needs typed confirmation of at least ${estimate.est_usd_high:.2f}",
            current=estimate.model_dump(mode="json"),
        )
    try:
        result = enqueue(
            ctx,
            task_ids=task_ids,
            model_keys=body.model_keys,
            label=body.label,
            sampling_override=body.sampling_override,
            harness_version=HARNESS_VERSION,
            principal_subject=admin.principal.subject,
            launched_by=admin.actor,
            config_revision=ctx.config.snapshot().revision,
        )
    except HTTPException as exc:
        raise _http_to_admin(exc) from None
    with admin_write(
        ctx,
        admin,
        action="run.launch",
        entity_type="sweep",
        entity_id=result.sweep_id,
        summary=f"launch {len(result.runs)} run(s)",
        bumps_revision=False,
    ) as w:
        w.after = {
            "runs": len(result.runs),
            "queued": result.queued,
            "models": body.model_keys,
            "est_usd_high": estimate.est_usd_high,
            "confirm_spend_usd": body.confirm_spend_usd,
        }
    return AdminEnqueueResponse(**result.model_dump(), estimate=estimate)


# ───────────────────────────────────────────────────────────────── reads ──


@router.get("/runs", response_model=AdminRunList)
def list_admin_runs(
    _: Admin,
    run_status: RunStatus | None = Query(None, alias="status"),
    sweep_id: str | None = Query(None),
    model_key: str | None = Query(None),
    task_id: str | None = Query(None),
    launched_by: str | None = Query(None),
    limit: int = Query(50, ge=1, le=MAX_ADMIN_PAGE),
    cursor: str | None = Query(None),
    ctx: AppContext = Depends(get_context),
) -> AdminRunList:
    """Newest first.  ``next_cursor`` is opaque; pass it back for the next page."""
    stmt = select(RunRow).order_by(RunRow.created_at.desc(), RunRow.id.desc()).limit(limit + 1)
    for column, value in (
        (RunRow.status, run_status.value if run_status else None),
        (RunRow.sweep_id, sweep_id),
        (RunRow.model_key, model_key),
        (RunRow.task_id, task_id),
        (RunRow.launched_by, launched_by),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    if cursor:
        at, key = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(RunRow.created_at < at, and_(RunRow.created_at == at, RunRow.id < key))
        )
    with session_scope(ctx.session_factory) as session:
        rows = list(session.scalars(stmt))
        page = rows[:limit]
        next_cursor = (
            _encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        )
        return AdminRunList(runs=[_admin_record(r) for r in page], next_cursor=next_cursor)


@router.get("/runs/{run_id}", response_model=AdminRunDetail)
def get_admin_run(run_id: str, _: Admin, ctx: AppContext = Depends(get_context)) -> AdminRunDetail:
    """UNREDACTED: explanations and errors included."""
    with session_scope(ctx.session_factory) as session:
        row = session.get(RunRow, run_id)
        if row is None:
            raise not_found(f"run {run_id!r}")
        results = list_results_for_run(session, run_id, limit=MAX_ADMIN_PAGE)
        return AdminRunDetail(
            run=_admin_record(row),
            results=[result_row_to_record(r) for r in results],
            results_total=count_results_for_run(session, run_id),
        )


@router.get("/runs/{run_id}/results/{sample_id}/transcript")
def get_admin_transcript(
    run_id: str, sample_id: str, _: Admin, ctx: AppContext = Depends(get_context)
) -> dict:
    """The archived transcript; the key comes from the path convention, never
    from a client-supplied URI."""
    try:
        key = artifact_paths.sample_key(run_id, sample_id)
    except ValueError as exc:
        raise admin_error(400, "validation_failed", str(exc)) from None
    try:
        return ctx.artifact_store.get_json(key)
    except KeyError:
        raise not_found(f"transcript for run {run_id!r} sample {sample_id!r}") from None


# ──────────────────────────────────────────────────────────────── cancel ──


def _cancel(session, row: RunRow, login: str) -> bool:
    """Cancel one run.  Returns True if this call changed anything."""
    if RunStatus(row.status) in TERMINAL_RUN_STATUSES:
        return False
    now = utcnow()
    if row.status == RunStatus.QUEUED.value:
        # Conditioned on still being queued: a runner may claim it this instant.
        result = session.execute(
            update(RunRow)
            .where(RunRow.id == row.id, RunRow.status == RunStatus.QUEUED.value)
            .values(
                status=RunStatus.CANCELLED.value,
                finished_at=now,
                error=f"cancelled by {login} before it started",
            )
        )
        if result.rowcount:
            session.refresh(row)
            return True
        session.refresh(row)  # claimed meanwhile -> fall through as running
    if row.status == RunStatus.RUNNING.value and row.cancel_requested_at is None:
        row.cancel_requested_at = now
        row.error = f"cancel requested by {login}"
        return True
    return False


@router.post("/runs/{run_id}/cancel", response_model=AdminRunRecord)
def cancel_run(run_id: str, admin: Admin, ctx: AppContext = Depends(get_context)) -> AdminRunRecord:
    """Idempotent: a terminal run is returned unchanged with 200."""
    with admin_write(
        ctx,
        admin,
        action="run.cancel",
        entity_type="run",
        entity_id=run_id,
        summary=f"cancel run {run_id}",
        bumps_revision=False,
    ) as w:
        row = w.session.get(RunRow, run_id)
        if row is None:
            raise not_found(f"run {run_id!r}")
        before = row.status
        changed = _cancel(w.session, row, admin.actor)
        w.session.flush()
        w.before = {"status": before}
        w.after = {
            "status": row.status,
            "changed": changed,
            "cancel_requested": row.cancel_requested_at is not None,
        }
        record = _admin_record(row)
    return record


# ──────────────────────────────────────────────────────────────── sweeps ──


def _summaries(session, sweep_ids: list[str]) -> list[SweepSummary]:
    if not sweep_ids:
        return []
    rows = session.execute(
        select(
            RunRow.sweep_id,
            RunRow.status,
            func.count(),
            func.coalesce(func.sum(RunRow.total_cost_usd), 0.0),
        )
        .where(RunRow.sweep_id.in_(sweep_ids))
        .group_by(RunRow.sweep_id, RunRow.status)
    ).all()
    meta = {
        r[0]: r
        for r in session.execute(
            select(
                RunRow.sweep_id,
                func.min(RunRow.created_at),
                func.max(RunRow.launched_by),
                func.max(RunRow.label),
            )
            .where(RunRow.sweep_id.in_(sweep_ids))
            .group_by(RunRow.sweep_id)
        ).all()
    }
    out = []
    for sweep_id in sweep_ids:
        mine = [r for r in rows if r[0] == sweep_id]
        out.append(
            SweepSummary(
                sweep_id=sweep_id,
                created_at=meta[sweep_id][1],
                launched_by=meta[sweep_id][2],
                label=meta[sweep_id][3],
                run_count=sum(r[2] for r in mine),
                by_status={RunStatus(r[1]): int(r[2]) for r in mine},
                total_cost_usd=float(sum(r[3] for r in mine)),
            )
        )
    return out


@router.get("/sweeps", response_model=SweepList)
def list_sweeps(
    _: Admin,
    limit: int = Query(50, ge=1, le=MAX_ADMIN_PAGE),
    cursor: str | None = Query(None),
    ctx: AppContext = Depends(get_context),
) -> SweepList:
    started = func.min(RunRow.created_at)
    stmt = (
        select(RunRow.sweep_id, started.label("started"))
        .where(RunRow.sweep_id.is_not(None))
        .group_by(RunRow.sweep_id)
        .order_by(started.desc(), RunRow.sweep_id.desc())
    )
    if cursor:
        at, key = _decode_cursor(cursor)
        stmt = stmt.having(or_(started < at, and_(started == at, RunRow.sweep_id < key)))
    with session_scope(ctx.session_factory) as session:
        rows = session.execute(stmt.limit(limit + 1)).all()
        page = rows[:limit]
        next_cursor = _encode_cursor(page[-1][1], page[-1][0]) if len(rows) > limit else None
        return SweepList(sweeps=_summaries(session, [r[0] for r in page]), next_cursor=next_cursor)


@router.get("/sweeps/{sweep_id}", response_model=SweepDetail)
def get_sweep(sweep_id: str, _: Admin, ctx: AppContext = Depends(get_context)) -> SweepDetail:
    with session_scope(ctx.session_factory) as session:
        rows = list(
            session.scalars(
                select(RunRow)
                .where(RunRow.sweep_id == sweep_id)
                .order_by(RunRow.created_at, RunRow.id)
            )
        )
        if not rows:
            raise not_found(f"sweep {sweep_id!r}")
        return SweepDetail(
            summary=_summaries(session, [sweep_id])[0], runs=[_admin_record(r) for r in rows]
        )


@router.post("/sweeps/{sweep_id}/cancel", response_model=SweepSummary)
def cancel_sweep(
    sweep_id: str, admin: Admin, ctx: AppContext = Depends(get_context)
) -> SweepSummary:
    """Cancels every non-terminal run of the sweep."""
    with admin_write(
        ctx,
        admin,
        action="sweep.cancel",
        entity_type="sweep",
        entity_id=sweep_id,
        summary=f"cancel sweep {sweep_id}",
        bumps_revision=False,
    ) as w:
        rows = list(w.session.scalars(select(RunRow).where(RunRow.sweep_id == sweep_id)))
        if not rows:
            raise not_found(f"sweep {sweep_id!r}")
        changed = sum(1 for r in rows if _cancel(w.session, r, admin.actor))
        w.session.flush()
        w.after = {"cancelled_or_requested": changed}
        summary = _summaries(w.session, [sweep_id])[0]
    return summary
