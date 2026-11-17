"""``/admin/system`` and ``/admin/export``: what this deployment is, and a
backup of what it holds."""

from __future__ import annotations

import io
import zipfile

import yaml
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select

from ida_api.admin.deps import Admin
from ida_api.admin.material import TASKS_SPEC_GATED
from ida_api.admin.schemas import SystemGuards, SystemInfo
from ida_api.admin.service import admin_write, require_db_config
from ida_api.deps import AppContext, get_context
from ida_core.configdb import reader
from ida_core.configdb.reader import current_revision
from ida_core.configdb.tables import TaskFamilyRow
from ida_core.db import session_scope
from ida_core.units import units_document

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
        tasks_spec_gated=TASKS_SPEC_GATED,
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
    admin: Admin,
    include_private: bool = Query(False, description="Include private families (audited)."),
    ctx: AppContext = Depends(get_context),
) -> Response:
    """A zip of the live config as YAML -- ``models.yaml``, ``tasks/<family>/
    <name>.yaml``, ``curriculum/{slo,majors,units}.yaml`` -- for backup and for
    pulling admin edits back into a dev fixture.

    ``private`` families are left out unless ``include_private=true``: that
    material must never reach the public repo by accident.  Every export is
    audited (``config.export``), with whether private material was included."""
    require_db_config(ctx)
    buffer = io.BytesIO()
    with session_scope(ctx.session_factory) as session:
        private = set(
            session.scalars(select(TaskFamilyRow.key).where(TaskFamilyRow.provenance == "private"))
        )
        tasks = [
            (task_id, doc)
            for task_id, doc in reader.task_documents(session)
            if include_private or task_id.split("/", 1)[0] not in private
        ]
        files = {
            "models.yaml": reader.models_document(session),
            "curriculum/slo.yaml": reader.slo_document(session),
            "curriculum/majors.yaml": reader.majors_document(session),
            "curriculum/units.yaml": units_document(reader.units(session)),
        }
        revision, _ = current_revision(session)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, doc in files.items():
            if doc is not None:
                archive.writestr(name, _yaml(doc))
        for task_id, doc in tasks:
            archive.writestr(f"tasks/{task_id}.yaml", _yaml(doc))
    with admin_write(
        ctx,
        admin,
        action="config.export",
        entity_type="config",
        entity_id=str(revision),
        summary="export",
        bumps_revision=False,
    ) as w:
        w.after = {
            "include_private": include_private,
            "tasks": len(tasks),
            "private_families_excluded": [] if include_private else sorted(private),
        }
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="ida-llm-config-r{revision}.zip"',
            "Cache-Control": "no-store",
        },
    )


def _yaml(document) -> str:
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)
