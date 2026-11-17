"""``/admin/audit``: the append-only log, and the sign-in event intake.

PR B1 registers the contract; the handlers land in B5."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, status
from fastapi.responses import Response

from ida_api.admin.deps import Admin, not_implemented
from ida_api.admin.schemas import AuditList, AuthEventInput

router = APIRouter(tags=["admin: audit"])


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
    cursor: str | None = Query(None),
) -> AuditList:
    raise not_implemented("GET /admin/audit")


@router.post("/audit/events", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def record_auth_event(body: AuthEventInput, _: Admin) -> Response:
    """Sign-in, denied and sign-out events from the frontend's Auth.js."""
    raise not_implemented("POST /admin/audit/events")
