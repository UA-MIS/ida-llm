"""``/admin/task-families``, ``/admin/tasks`` and ``/admin/material/upload``.

PR B1 registers the contract; the handlers land in B4.

⚠ ROUTE ORDER IS LOAD-BEARING.  Task ids contain slashes, so the task routes
use ``{task_id:path}``, and ``PUT /tasks/{task_id:path}`` would happily swallow
``PUT /tasks/fam/t/samples/s1`` as a task id.  The ``/samples`` routes are
therefore registered BEFORE the plain task routes, and ``/tasks/validate``
before everything."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from fastapi.responses import Response

from ida_api.admin.deps import Admin, IfMatch, not_implemented
from ida_api.admin.schemas import (
    AdminTask,
    AdminTaskSummary,
    SampleInput,
    TaskFamily,
    TaskFamilyInput,
    TaskFamilyUpdate,
    TaskValidateInput,
    TaskWriteInput,
    UploadResult,
    ValidateResult,
)

router = APIRouter(tags=["admin: material"])


# ── task families ───────────────────────────────────────────────────────────


@router.get("/task-families", response_model=list[TaskFamily])
def list_task_families(_: Admin) -> list[TaskFamily]:
    raise not_implemented("GET /admin/task-families")


@router.post("/task-families", response_model=TaskFamily, status_code=status.HTTP_201_CREATED)
def create_task_family(body: TaskFamilyInput, _: Admin) -> TaskFamily:
    raise not_implemented("POST /admin/task-families")


@router.put("/task-families/{key}", response_model=TaskFamily)
def update_task_family(key: str, body: TaskFamilyUpdate, _: Admin, version: IfMatch) -> TaskFamily:
    raise not_implemented("PUT /admin/task-families/{key}")


@router.delete(
    "/task-families/{key}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def archive_task_family(key: str, _: Admin, version: IfMatch) -> Response:
    """Archive. 409 while a class or a unit references it."""
    raise not_implemented("DELETE /admin/task-families/{key}")


# ── tasks ───────────────────────────────────────────────────────────────────


@router.get("/tasks", response_model=list[AdminTaskSummary])
def list_admin_tasks(
    _: Admin, family: str | None = Query(None, description="One family only.")
) -> list[AdminTaskSummary]:
    raise not_implemented("GET /admin/tasks")


@router.post("/tasks/validate", response_model=ValidateResult)
def validate_task_document(body: TaskValidateInput, _: Admin) -> ValidateResult:
    """Dry run, no write: the form editor calls it on blur and before save."""
    raise not_implemented("POST /admin/tasks/validate")


@router.post("/tasks", response_model=AdminTask, status_code=status.HTTP_201_CREATED)
def create_task(body: TaskWriteInput, _: Admin) -> AdminTask:
    raise not_implemented("POST /admin/tasks")


@router.post("/tasks/{task_id:path}/samples", response_model=AdminTask)
def add_sample(task_id: str, body: SampleInput, _: Admin, version: IfMatch) -> AdminTask:
    raise not_implemented("POST /admin/tasks/{task_id}/samples")


@router.put("/tasks/{task_id:path}/samples/{sample_id}", response_model=AdminTask)
def replace_sample(
    task_id: str, sample_id: str, body: SampleInput, _: Admin, version: IfMatch
) -> AdminTask:
    raise not_implemented("PUT /admin/tasks/{task_id}/samples/{sample_id}")


@router.delete("/tasks/{task_id:path}/samples/{sample_id}", response_model=AdminTask)
def delete_sample(task_id: str, sample_id: str, _: Admin, version: IfMatch) -> AdminTask:
    raise not_implemented("DELETE /admin/tasks/{task_id}/samples/{sample_id}")


@router.get("/tasks/{task_id:path}", response_model=AdminTask)
def get_admin_task(task_id: str, _: Admin) -> AdminTask:
    """UNREDACTED: prompts, targets, rubric."""
    raise not_implemented("GET /admin/tasks/{task_id}")


@router.put("/tasks/{task_id:path}", response_model=AdminTask)
def replace_task(task_id: str, body: TaskWriteInput, _: Admin, version: IfMatch) -> AdminTask:
    """The id is immutable; a rename is create + archive."""
    raise not_implemented("PUT /admin/tasks/{task_id}")


@router.delete(
    "/tasks/{task_id:path}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def archive_task(task_id: str, _: Admin, version: IfMatch) -> Response:
    raise not_implemented("DELETE /admin/tasks/{task_id}")


# ── upload ──────────────────────────────────────────────────────────────────


@router.post("/material/upload", response_model=UploadResult)
def upload_material(
    _: Admin,
    file: UploadFile = File(..., description=".yaml/.yml, at most IDA_ADMIN_UPLOAD_MAX_BYTES"),
    commit: bool = Form(False),
    mode: str = Form("create", pattern="^(create|replace)$"),
) -> UploadResult:
    """Preview (``commit=false``) or store a task YAML. Parsed with
    ``yaml.safe_load`` only; the raw bytes reach object storage only after
    validation passes AND ``commit=true``."""
    raise not_implemented("POST /admin/material/upload")
