"""``/admin/task-families``, ``/admin/tasks`` and ``/admin/material/upload``.

Benchmark material, authored in the console instead of a pull request.  The
rules are the CI gate's, run on every save (``ida_core.validation_suite``):
JSON schema -> ``TaskSpec`` (taxonomy consistency, the target-leaks-into-
metadata rule) -> ``check_task_tags`` (the ``slo:``/``use-mode:`` typo trap)
-> the id's family exists.  A document with any error is never stored.

Every stored version of every task is also written to ``task_revisions`` --
the D-1 reproducibility record now that git no longer holds DB-authored
material: any ``runs.task_content_sha`` resolves back to the exact text.

⚠ ROUTE ORDER IS LOAD-BEARING.  Task ids contain slashes, so the task routes
use ``{task_id:path}``, and ``PUT /tasks/{task_id:path}`` would happily swallow
``PUT /tasks/fam/t/samples/s1`` as a task id.  The ``/samples`` routes are
therefore registered BEFORE the plain task routes, and ``/tasks/validate``
before everything.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import yaml
from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy import func, select

from ida_api.admin.deps import Admin, IfMatch, admin_error, set_etag
from ida_api.admin.schemas import (
    AdminTask,
    AdminTaskSummary,
    SampleInput,
    TaskFamily,
    TaskFamilyInput,
    TaskFamilyUpdate,
    TaskValidateInput,
    TaskWriteInput,
    UnitRef,
    UploadDiff,
    UploadResult,
    ValidateResult,
)
from ida_api.admin.service import (
    SCOPE_TASKS,
    Write,
    admin_write,
    bump,
    conflict,
    expect_version,
    not_found,
    require_db_config,
    stamp_new,
    to_issue_models,
    validation_failed,
)
from ida_api.deps import AppContext, get_context
from ida_core.artifacts import admin_material_key
from ida_core.configdb.seed import normalise_document
from ida_core.configdb.tables import (
    ClassTaskFamilyRow,
    TaskFamilyRow,
    TaskRevisionRow,
    TaskRow,
    UnitFamilyRow,
    UnitRow,
)
from ida_core.contracts import TaskSpec
from ida_core.db import session_scope, utcnow
from ida_core.validation_suite import Issue, errors_of, validate_task

router = APIRouter(tags=["admin: material"])

TASKS_SPEC_GATED = False
"""Whether the public ``GET /tasks/{id}`` has stopped serving prompts to anyone
who can reach the API (PR B6).  Until it is, no family may be marked
``private`` -- the material would be one in-cluster request from public
(design risk R10).  ``GET /admin/system`` reports the same flag."""


# ─────────────────────────────────────────────────────────────── helpers ──


def _live_families(session) -> set[str]:
    return set(
        session.scalars(select(TaskFamilyRow.key).where(TaskFamilyRow.archived_at.is_(None)))
    )


def _check(
    ctx: AppContext, session, document: Any
) -> tuple[list[Issue], TaskSpec | None, dict | None]:
    """Validate a candidate document exactly as it would be stored."""
    if not isinstance(document, dict):
        return [Issue("", "a task document must be a mapping")], None, None
    stored = normalise_document(document)
    issues, spec = validate_task(
        stored, curriculum=ctx.config.snapshot().curriculum, families=_live_families(session)
    )
    return issues, spec, stored


def _summary(row: TaskRow) -> AdminTaskSummary:
    return AdminTaskSummary(
        id=row.id,
        family_key=row.family_key,
        title=row.title,
        kind=row.kind,
        sample_count=row.sample_count,
        content_sha=row.content_sha,
        source=row.source,
        archived_at=row.archived_at,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
        version=row.version,
    )


def _full(ctx: AppContext, session, row: TaskRow) -> AdminTask:
    issues, _, _ = _check(ctx, session, row.document)
    return AdminTask(
        **_summary(row).model_dump(),
        document=row.document,
        issues=to_issue_models([i for i in issues if i.severity == "warning"]),
    )


def _store(w: Write, admin, row: TaskRow, spec: TaskSpec, stored: dict, *, source: str) -> int:
    """Write the document onto ``row`` and append its ``task_revisions`` row.
    Returns the revision id (it goes into the audit summary)."""
    row.document = stored
    row.content_sha = spec.content_sha
    row.title = spec.title
    row.kind = spec.kind.value
    row.sample_count = len(spec.samples)
    row.source = source
    revision = TaskRevisionRow(
        task_id=spec.id, content_sha=spec.content_sha, document=stored, actor=admin.actor
    )
    w.session.add(revision)
    w.session.flush()
    return int(revision.id)


def _audit_form(row: TaskRow, revision_id: int | None) -> dict:
    """Tasks are audited as a summary plus the revision id -- the document
    itself lives in ``task_revisions``, not in the audit log."""
    return {
        "content_sha": row.content_sha,
        "sample_count": row.sample_count,
        "task_revision_id": revision_id,
    }


def _live_task(session, task_id: str) -> TaskRow:
    row = session.get(TaskRow, task_id)
    if row is None or row.archived_at is not None:
        raise not_found(f"task {task_id!r}")
    return row


def _sample_index(document: dict, sample_id: str) -> int:
    for index, sample in enumerate(document.get("samples") or []):
        if isinstance(sample, dict) and sample.get("id") == sample_id:
            return index
    raise not_found(f"sample {sample_id!r}")


# ─────────────────────────────────────────────────────────── task families ──


def _family_view(session, row: TaskFamilyRow) -> TaskFamily:
    counts = session.execute(
        select(func.count(), func.coalesce(func.sum(TaskRow.sample_count), 0)).where(
            TaskRow.family_key == row.key, TaskRow.archived_at.is_(None)
        )
    ).one()
    classes = list(
        session.scalars(
            select(ClassTaskFamilyRow.course)
            .where(ClassTaskFamilyRow.family_key == row.key)
            .order_by(ClassTaskFamilyRow.course)
        )
    )
    unit = session.execute(
        select(UnitRow.course, UnitRow.key)
        .join(UnitFamilyRow, UnitFamilyRow.unit_id == UnitRow.id)
        .where(UnitFamilyRow.family_key == row.key)
    ).first()
    return TaskFamily(
        key=row.key,
        title=row.title,
        description=row.description,
        provenance=row.provenance,
        task_count=int(counts[0]),
        sample_count=int(counts[1]),
        classes=classes,
        unit=UnitRef(course=unit[0], key=unit[1]) if unit else None,
        archived_at=row.archived_at,
        version=row.version,
    )


def _refuse_private(provenance: str) -> None:
    if provenance == "private" and not TASKS_SPEC_GATED:
        raise validation_failed(
            [
                Issue(
                    "provenance",
                    "private material cannot be added yet: the public task endpoint still "
                    "serves prompts in-cluster (it is gated in a later release)",
                )
            ]
        )


@router.get("/task-families", response_model=list[TaskFamily])
def list_task_families(_: Admin, ctx: AppContext = Depends(get_context)) -> list[TaskFamily]:
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        rows = session.scalars(select(TaskFamilyRow).order_by(TaskFamilyRow.key))
        return [_family_view(session, r) for r in rows]


@router.post("/task-families", response_model=TaskFamily, status_code=status.HTTP_201_CREATED)
def create_task_family(
    body: TaskFamilyInput, admin: Admin, response: Response, ctx: AppContext = Depends(get_context)
) -> TaskFamily:
    _refuse_private(body.provenance)
    with admin_write(
        ctx,
        admin,
        action="task_family.create",
        entity_type="task_family",
        entity_id=body.key,
        summary=f"create task family {body.key}",
    ) as w:
        if w.session.get(TaskFamilyRow, body.key) is not None:
            raise conflict(f"task family {body.key!r} already exists (or is archived)")
        row = stamp_new(
            TaskFamilyRow(
                key=body.key,
                title=body.title,
                description=body.description,
                provenance=body.provenance,
            ),
            admin,
        )
        w.session.add(row)
        w.session.flush()
        view = _family_view(w.session, row)
        w.after = view.model_dump(mode="json")
    set_etag(response, view.version)
    return view


@router.put("/task-families/{key}", response_model=TaskFamily)
def update_task_family(
    key: str,
    body: TaskFamilyUpdate,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> TaskFamily:
    """The key is immutable: task ids embed it."""
    _refuse_private(body.provenance)
    with admin_write(
        ctx,
        admin,
        action="task_family.update",
        entity_type="task_family",
        entity_id=key,
        summary=f"update task family {key}",
    ) as w:
        row = w.session.get(TaskFamilyRow, key)
        if row is None or row.archived_at is not None:
            raise not_found(f"task family {key!r}")
        before = _family_view(w.session, row)
        expect_version(row, version, before.model_dump(mode="json"))
        row.title, row.description, row.provenance = body.title, body.description, body.provenance
        bump(row, admin)
        view = _family_view(w.session, row)
        w.before, w.after = before.model_dump(mode="json"), view.model_dump(mode="json")
    set_etag(response, view.version)
    return view


@router.delete(
    "/task-families/{key}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def archive_task_family(
    key: str, admin: Admin, version: IfMatch, ctx: AppContext = Depends(get_context)
) -> Response:
    """Archive.  409 while a class or a unit references it, or while it still
    has live tasks (archive those first, so nothing disappears by surprise)."""
    with admin_write(
        ctx,
        admin,
        action="task_family.delete",
        entity_type="task_family",
        entity_id=key,
        summary=f"archive task family {key}",
    ) as w:
        row = w.session.get(TaskFamilyRow, key)
        if row is None or row.archived_at is not None:
            raise not_found(f"task family {key!r}")
        view = _family_view(w.session, row)
        expect_version(row, version, view.model_dump(mode="json"))
        if view.unit is not None:
            raise conflict(
                f"task family {key!r} is in unit {view.unit.key!r} of {view.unit.course}; "
                "remove it from the unit first"
            )
        if view.classes:
            raise conflict(
                f"task family {key!r} is claimed by {view.classes}; remove it there first"
            )
        if view.task_count:
            raise conflict(
                f"task family {key!r} still has {view.task_count} live task(s); archive them first"
            )
        row.archived_at = utcnow()
        bump(row, admin)
        w.before = view.model_dump(mode="json")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ──────────────────────────────────────────────────────────────── tasks ──


@router.get("/tasks", response_model=list[AdminTaskSummary])
def list_admin_tasks(
    _: Admin,
    family: str | None = Query(None, description="One family only."),
    ctx: AppContext = Depends(get_context),
) -> list[AdminTaskSummary]:
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        stmt = select(TaskRow).where(TaskRow.archived_at.is_(None)).order_by(TaskRow.id)
        if family is not None:
            stmt = stmt.where(TaskRow.family_key == family)
        return [_summary(r) for r in session.scalars(stmt)]


def _yaml_issue(exc: yaml.YAMLError) -> Issue:
    mark = getattr(exc, "problem_mark", None)
    where = f"line {mark.line + 1}, col {mark.column + 1}" if mark else "yaml"
    problem = getattr(exc, "problem", None) or str(exc)
    return Issue(where, f"could not parse YAML: {problem}")


def _validate_result(issues: list[Issue], spec: TaskSpec | None) -> ValidateResult:
    return ValidateResult(
        ok=spec is not None and not errors_of(issues),
        issues=to_issue_models(issues),
        content_sha=spec.content_sha if spec else None,
        sample_count=len(spec.samples) if spec else None,
    )


@router.post("/tasks/validate", response_model=ValidateResult)
def validate_task_document(
    body: TaskValidateInput, _: Admin, ctx: AppContext = Depends(get_context)
) -> ValidateResult:
    """Dry run, no write: the form editor calls it on blur and before save."""
    require_db_config(ctx)
    document: Any = body.document
    if body.yaml is not None:
        try:
            document = yaml.safe_load(body.yaml)
        except yaml.YAMLError as exc:
            return ValidateResult(ok=False, issues=to_issue_models([_yaml_issue(exc)]))
    with session_scope(ctx.session_factory) as session:
        issues, spec, _ = _check(ctx, session, document)
    return _validate_result(issues, spec)


@router.post("/tasks", response_model=AdminTask, status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskWriteInput, admin: Admin, response: Response, ctx: AppContext = Depends(get_context)
) -> AdminTask:
    """``document.id`` must start with an existing family key."""
    task_id = str(body.document.get("id", ""))
    with admin_write(
        ctx,
        admin,
        action="task.create",
        entity_type="task",
        entity_id=task_id or "?",
        summary=f"create task {task_id}",
        scopes={SCOPE_TASKS},
    ) as w:
        view = _create(ctx, w, admin, body.document, source="form")
    set_etag(response, view.version)
    return view


def _create(ctx: AppContext, w: Write, admin, document: dict, *, source: str, object_key=None):
    issues, spec, stored = _check(ctx, w.session, document)
    if spec is None:
        raise validation_failed(issues, "Task failed validation")
    if w.session.get(TaskRow, spec.id) is not None:
        raise conflict(f"task {spec.id!r} already exists (or is archived); edit it instead")
    row = stamp_new(
        TaskRow(id=spec.id, family_key=spec.id.split("/", 1)[0], upload_object_key=object_key),
        admin,
    )
    w.session.add(row)
    revision_id = _store(w, admin, row, spec, stored, source=source)
    w.entity_id = spec.id
    w.summary = f"create task {spec.id}"
    w.after = _audit_form(row, revision_id)
    return _full(ctx, w.session, row)


def _replace(ctx: AppContext, w: Write, admin, row: TaskRow, document: dict, *, source: str):
    if document.get("id") != row.id:
        raise validation_failed(
            [Issue("id", "the task id cannot change; create a new task and archive this one")]
        )
    issues, spec, stored = _check(ctx, w.session, document)
    if spec is None:
        raise validation_failed(issues, "Task failed validation")
    w.before = _audit_form(row, None)
    revision_id = _store(w, admin, row, spec, stored, source=source)
    bump(row, admin)
    w.after = _audit_form(row, revision_id)
    return _full(ctx, w.session, row)


def _task_write(ctx, admin, task_id: str, action: str, summary: str):
    return admin_write(
        ctx,
        admin,
        action=action,
        entity_type="task",
        entity_id=task_id,
        summary=summary,
        scopes={SCOPE_TASKS},
    )


@router.post("/tasks/{task_id:path}/samples", response_model=AdminTask)
def add_sample(
    task_id: str,
    body: SampleInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminTask:
    """Server-side sugar: append to ``document.samples``, re-validate the whole
    document."""
    with _task_write(ctx, admin, task_id, "task.update", f"add a sample to {task_id}") as w:
        row = _live_task(w.session, task_id)
        expect_version(row, version, _summary(row).model_dump(mode="json"))
        document = copy.deepcopy(row.document)
        sample_id = body.sample.get("id")
        if any(s.get("id") == sample_id for s in document.get("samples") or []):
            raise conflict(f"sample {sample_id!r} already exists in {task_id}")
        document.setdefault("samples", []).append(body.sample)
        view = _replace(ctx, w, admin, row, document, source="form")
    set_etag(response, view.version)
    return view


@router.put("/tasks/{task_id:path}/samples/{sample_id}", response_model=AdminTask)
def replace_sample(
    task_id: str,
    sample_id: str,
    body: SampleInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminTask:
    if body.sample.get("id", sample_id) != sample_id:
        raise validation_failed([Issue("sample.id", "the sample id cannot change")])
    with _task_write(
        ctx, admin, task_id, "task.update", f"edit sample {sample_id} of {task_id}"
    ) as w:
        row = _live_task(w.session, task_id)
        expect_version(row, version, _summary(row).model_dump(mode="json"))
        document = copy.deepcopy(row.document)
        document["samples"][_sample_index(document, sample_id)] = {**body.sample, "id": sample_id}
        view = _replace(ctx, w, admin, row, document, source="form")
    set_etag(response, view.version)
    return view


@router.delete("/tasks/{task_id:path}/samples/{sample_id}", response_model=AdminTask)
def delete_sample(
    task_id: str,
    sample_id: str,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminTask:
    with _task_write(
        ctx, admin, task_id, "task.update", f"delete sample {sample_id} of {task_id}"
    ) as w:
        row = _live_task(w.session, task_id)
        expect_version(row, version, _summary(row).model_dump(mode="json"))
        document = copy.deepcopy(row.document)
        del document["samples"][_sample_index(document, sample_id)]
        view = _replace(ctx, w, admin, row, document, source="form")
    set_etag(response, view.version)
    return view


@router.get("/tasks/{task_id:path}", response_model=AdminTask)
def get_admin_task(
    task_id: str, _: Admin, response: Response, ctx: AppContext = Depends(get_context)
) -> AdminTask:
    """UNREDACTED: prompts, targets, rubric.  Admin is authenticated."""
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        row = session.get(TaskRow, task_id)
        if row is None:
            raise not_found(f"task {task_id!r}")
        view = _full(ctx, session, row)
    set_etag(response, view.version)
    return view


@router.put("/tasks/{task_id:path}", response_model=AdminTask)
def replace_task(
    task_id: str,
    body: TaskWriteInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminTask:
    """The id is immutable; a rename is create + archive.  Writes a
    ``task_revisions`` row."""
    with _task_write(ctx, admin, task_id, "task.update", f"update task {task_id}") as w:
        row = _live_task(w.session, task_id)
        expect_version(row, version, _summary(row).model_dump(mode="json"))
        view = _replace(ctx, w, admin, row, body.document, source="form")
    set_etag(response, view.version)
    return view


@router.delete(
    "/tasks/{task_id:path}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def archive_task(
    task_id: str, admin: Admin, version: IfMatch, ctx: AppContext = Depends(get_context)
) -> Response:
    """Archive: the task leaves the catalog; historical runs stay resolvable
    through ``task_revisions``."""
    with _task_write(ctx, admin, task_id, "task.delete", f"archive task {task_id}") as w:
        row = _live_task(w.session, task_id)
        expect_version(row, version, _summary(row).model_dump(mode="json"))
        w.before = _audit_form(row, None)
        row.archived_at = utcnow()
        bump(row, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────── upload ──


def _diff(old: dict, new: dict) -> UploadDiff:
    def by_id(doc):
        return {s.get("id"): json.dumps(s, sort_keys=True) for s in doc.get("samples") or []}

    a, b = by_id(old), by_id(new)
    return UploadDiff(
        samples_added=len(set(b) - set(a)),
        samples_removed=len(set(a) - set(b)),
        samples_changed=sum(1 for k in set(a) & set(b) if a[k] != b[k]),
    )


@router.post("/material/upload", response_model=UploadResult)
def upload_material(
    admin: Admin,
    file: UploadFile = File(..., description=".yaml/.yml, at most IDA_ADMIN_UPLOAD_MAX_BYTES"),
    commit: bool = Form(False),
    mode: str = Form("create", pattern="^(create|replace)$"),
    ctx: AppContext = Depends(get_context),
) -> UploadResult:
    """Preview (``commit=false``) or store a task YAML.

    Parsed with ``yaml.safe_load`` only.  The raw bytes reach object storage
    only after validation passes AND ``commit=true`` -- a rejected upload is
    never persisted anywhere."""
    require_db_config(ctx)
    name = (file.filename or "").lower()
    if not name.endswith((".yaml", ".yml")):
        raise validation_failed([Issue("file", "upload a .yaml or .yml task file")])
    limit = ctx.settings.admin_upload_max_bytes
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise validation_failed([Issue("file", f"the file is larger than {limit} bytes")])
    try:
        document = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return UploadResult(ok=False, issues=to_issue_models([Issue("file", "not UTF-8 text")]))
    except yaml.YAMLError as exc:
        return UploadResult(ok=False, issues=to_issue_models([_yaml_issue(exc)]))

    with session_scope(ctx.session_factory) as session:
        issues, spec, stored = _check(ctx, session, document)
        existing = session.get(TaskRow, spec.id) if spec else None
        if spec is not None and mode == "create" and existing is not None:
            issues.append(Issue("id", f"task {spec.id!r} already exists; upload with mode=replace"))
        if spec is not None and mode == "replace" and (existing is None or existing.archived_at):
            issues.append(Issue("id", f"there is no live task {spec.id!r} to replace"))
        diff = _diff(existing.document, stored) if spec and existing is not None else None
    checked = _validate_result(issues, spec if not errors_of(issues) else None)
    result = UploadResult(**checked.model_dump(), diff=diff)
    if not result.ok or not commit:
        return result

    sha = hashlib.sha256(data).hexdigest()
    key = admin_material_key(sha, utcnow())
    put_bytes = getattr(ctx.artifact_store, "put_bytes", None)
    if put_bytes is None:  # pragma: no cover - both real stores implement it
        raise admin_error(500, "conflict", "this artifact store cannot hold raw uploads")
    put_bytes(key, data, "application/yaml")
    action = "task.create" if mode == "create" else "task.update"
    with _task_write(ctx, admin, spec.id, action, f"upload task {spec.id}") as w:
        if mode == "create":
            view = _create(ctx, w, admin, document, source="upload", object_key=key)
        else:
            row = _live_task(w.session, spec.id)
            row.upload_object_key = key
            view = _replace(ctx, w, admin, row, document, source="upload")
        w.after = {**(w.after or {}), "upload_object_key": key}
    result.task = AdminTaskSummary(**{k: getattr(view, k) for k in AdminTaskSummary.model_fields})
    result.committed = True
    return result
