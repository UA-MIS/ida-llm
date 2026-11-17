"""``/admin/system`` and ``/admin/export``: what this deployment is, and a
backup of what it holds."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from ida_api.admin.deps import Admin, not_implemented
from ida_api.admin.schemas import SystemGuards, SystemInfo
from ida_api.deps import AppContext, get_context
from ida_core.configdb.reader import current_revision
from ida_core.db import session_scope

router = APIRouter(tags=["admin: system"])


@router.get("/system", response_model=SystemInfo)
def get_system(_: Admin, ctx: AppContext = Depends(get_context)) -> SystemInfo:
    """Read-only status: config source, revision, spend guards, KEK presence.

    Reports the KEK's active *id* only.  Nothing here is a secret, and nothing
    here is derived from one beyond "is it set" and "what is its label"."""
    settings = ctx.settings
    revision, revision_at = _current_revision(ctx)
    return SystemInfo(
        config_source=settings.config_source,
        revision=revision,
        revision_at=revision_at,
        guards=SystemGuards(
            sweep_max_runs=settings.sweep_max_runs,
            sweep_max_samples=settings.sweep_max_samples,
            admin_run_max_estimated_usd=settings.admin_run_max_estimated_usd,
            sweep_exclude_tags=sorted(settings.sweep_exclude_tag_set),
            public_hide_tags=sorted(settings.public_hide_tag_set),
        ),
        judge_model_key=settings.judge_model_key or None,
        kek_configured=bool(settings.credentials_kek.strip()),
        kek_active_id=settings.credentials_kek_active_id,
        admin_group_hint=settings.admin_groups.strip() or None,
        tasks_spec_gated=False,
    )


def _current_revision(ctx: AppContext):
    """``(revision, at)`` in db mode; ``(None, None)`` in yaml mode, where the
    config tables are not the source of truth."""
    if ctx.settings.config_source != "db":
        return None, None
    with session_scope(ctx.session_factory) as session:
        return current_revision(session)


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "the live config"}},
)
def export_config(
    _: Admin,
    include_private: bool = Query(False, description="Include private families (audited)."),
) -> Response:
    """A zip of the live config as YAML, for backup and for pulling admin edits
    back into a dev fixture.  Private families only on request, and audited."""
    raise not_implemented("GET /admin/export")
