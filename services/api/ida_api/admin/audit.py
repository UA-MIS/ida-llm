"""``/admin/audit``: the append-only log, and the sign-in event intake (design 5.5).

No route here (or anywhere) updates or deletes an audit row.  The log is the
trail that replaced git review for DB-authored configuration (design risk R2),
so it is only ever appended to."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from ida_api.admin.deps import Admin, admin_error
from ida_api.admin.schemas import AuditEntry, AuditList, AuthEventInput
from ida_api.admin.service import admin_write
from ida_api.deps import AppContext, get_context
from ida_core.configdb.tables import AuditLogRow
from ida_core.db import session_scope

router = APIRouter(tags=["admin: audit"])


def _entry(row: AuditLogRow) -> AuditEntry:
    return AuditEntry(
        id=row.id,
        at=row.at,
        actor_login=row.actor_login,
        actor_sub=row.actor_sub,
        via_subject=row.via_subject,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        before=row.before,
        after=row.after,
        config_revision=row.config_revision,
        request_id=row.request_id,
    )


@router.get("/audit", response_model=AuditList)
def list_audit(
    _: Admin,
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    actor: str | None = Query(None),
    action: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="The last id of the previous page."),
    ctx: AppContext = Depends(get_context),
) -> AuditList:
    """Newest first.  The cursor is the last row id seen (ids only grow)."""
    stmt = select(AuditLogRow).order_by(AuditLogRow.id.desc()).limit(limit + 1)
    for column, value in (
        (AuditLogRow.entity_type, entity_type),
        (AuditLogRow.entity_id, entity_id),
        (AuditLogRow.actor_login, actor),
        (AuditLogRow.action, action),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    if since is not None:
        stmt = stmt.where(AuditLogRow.at >= since)
    if until is not None:
        stmt = stmt.where(AuditLogRow.at < until)
    if cursor:
        if not cursor.isdigit():
            raise admin_error(422, "validation_failed", "malformed cursor")
        stmt = stmt.where(AuditLogRow.id < int(cursor))
    with session_scope(ctx.session_factory) as session:
        rows = list(session.scalars(stmt))
    page = rows[:limit]
    return AuditList(
        entries=[_entry(r) for r in page],
        next_cursor=str(page[-1].id) if len(rows) > limit else None,
    )


@router.post("/audit/events", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def record_auth_event(
    body: AuthEventInput, admin: Admin, ctx: AppContext = Depends(get_context)
) -> Response:
    """Sign-in, denied and sign-out events from the frontend's Auth.js.

    The ONLY record of a denied sign-in: a non-member never reaches any other
    route.  The row is attributed to the login in the event (the person who
    tried), via the console's token."""
    with admin_write(
        ctx,
        admin,
        action=body.action,
        entity_type="auth",
        entity_id=body.login,
        summary=body.action,
        bumps_revision=False,
    ) as w:
        w.after = {"login": body.login, "sub": body.sub, "groups_ok": body.groups_ok}
    return Response(status_code=status.HTTP_204_NO_CONTENT)
