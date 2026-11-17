"""``/admin/majors``, ``/admin/classes``, ``/admin/units``, ``/admin/curriculum/slo``.

PR B1 registers the contract; the handlers land in B5."""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import Response

from ida_api.admin.deps import Admin, IfMatch, not_implemented
from ida_api.admin.schemas import (
    AdminClass,
    AdminMajor,
    AdminUnit,
    ClassInput,
    FamiliesInput,
    MajorInput,
    MajorsResponse,
    ReorderInput,
    SloDocument,
    SloInput,
    UnitInput,
)

router = APIRouter(tags=["admin: curriculum"])


# ── majors ──────────────────────────────────────────────────────────────────


@router.get("/majors", response_model=MajorsResponse)
def list_majors(_: Admin) -> MajorsResponse:
    """One call renders the whole Classes area: majors, classes, units."""
    raise not_implemented("GET /admin/majors")


@router.post("/majors", response_model=AdminMajor, status_code=status.HTTP_201_CREATED)
def create_major(body: MajorInput, _: Admin) -> AdminMajor:
    raise not_implemented("POST /admin/majors")


@router.post("/majors/reorder", response_model=list[AdminMajor])
def reorder_majors(body: ReorderInput, _: Admin) -> list[AdminMajor]:
    raise not_implemented("POST /admin/majors/reorder")


@router.put("/majors/{major_id}", response_model=AdminMajor)
def update_major(major_id: str, body: MajorInput, _: Admin, version: IfMatch) -> AdminMajor:
    raise not_implemented("PUT /admin/majors/{major_id}")


@router.delete(
    "/majors/{major_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_major(major_id: str, _: Admin, version: IfMatch) -> Response:
    """409 while it owns classes."""
    raise not_implemented("DELETE /admin/majors/{major_id}")


# ── classes ─────────────────────────────────────────────────────────────────


@router.post("/classes", response_model=AdminClass, status_code=status.HTTP_201_CREATED)
def create_class(body: ClassInput, _: Admin) -> AdminClass:
    raise not_implemented("POST /admin/classes")


@router.put("/classes/{course}", response_model=AdminClass)
def update_class(course: str, body: ClassInput, _: Admin, version: IfMatch) -> AdminClass:
    raise not_implemented("PUT /admin/classes/{course}")


@router.delete("/classes/{course}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_class(course: str, _: Admin, version: IfMatch) -> Response:
    raise not_implemented("DELETE /admin/classes/{course}")


@router.put("/classes/{course}/task-families", response_model=AdminClass)
def set_class_families(course: str, body: FamiliesInput, _: Admin, version: IfMatch) -> AdminClass:
    """409 ``conflict`` naming the unit if a removed family is still claimed."""
    raise not_implemented("PUT /admin/classes/{course}/task-families")


# ── units ───────────────────────────────────────────────────────────────────


@router.get("/classes/{course}/units", response_model=list[AdminUnit])
def list_units(course: str, _: Admin) -> list[AdminUnit]:
    raise not_implemented("GET /admin/classes/{course}/units")


@router.post(
    "/classes/{course}/units", response_model=AdminUnit, status_code=status.HTTP_201_CREATED
)
def create_unit(course: str, body: UnitInput, _: Admin) -> AdminUnit:
    raise not_implemented("POST /admin/classes/{course}/units")


@router.post("/classes/{course}/units/reorder", response_model=list[AdminUnit])
def reorder_units(course: str, body: ReorderInput, _: Admin) -> list[AdminUnit]:
    """Renumbers ``n`` 1..k in one transaction."""
    raise not_implemented("POST /admin/classes/{course}/units/reorder")


@router.put("/units/{unit_id}", response_model=AdminUnit)
def update_unit(unit_id: str, body: UnitInput, _: Admin, version: IfMatch) -> AdminUnit:
    raise not_implemented("PUT /admin/units/{unit_id}")


@router.put("/units/{unit_id}/families", response_model=AdminUnit)
def set_unit_families(unit_id: str, body: FamiliesInput, _: Admin, version: IfMatch) -> AdminUnit:
    raise not_implemented("PUT /admin/units/{unit_id}/families")


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_unit(unit_id: str, _: Admin, version: IfMatch) -> Response:
    raise not_implemented("DELETE /admin/units/{unit_id}")


# ── outcomes (slo.yaml) ─────────────────────────────────────────────────────


@router.get("/curriculum/slo", response_model=SloDocument)
def get_slo(_: Admin) -> SloDocument:
    raise not_implemented("GET /admin/curriculum/slo")


@router.put("/curriculum/slo", response_model=SloDocument)
def put_slo(body: SloInput, _: Admin, version: IfMatch) -> SloDocument:
    raise not_implemented("PUT /admin/curriculum/slo")
