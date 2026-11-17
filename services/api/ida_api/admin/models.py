"""``/admin/models`` and ``/admin/model-families``.

PR B1 registers the contract; the handlers land in B3."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from fastapi.responses import Response

from ida_api.admin.deps import Admin, IfMatch, not_implemented
from ida_api.admin.schemas import (
    AdminModel,
    AdminModelInput,
    AdminModelPatch,
    ModelFamily,
    ModelFamilyCreate,
    ModelFamilyUpdate,
    ModelTestResult,
    ReorderInput,
)

router = APIRouter(tags=["admin: models"])


# ── model families ──────────────────────────────────────────────────────────


@router.get("/model-families", response_model=list[ModelFamily])
def list_model_families(_: Admin) -> list[ModelFamily]:
    raise not_implemented("GET /admin/model-families")


@router.post("/model-families", response_model=ModelFamily, status_code=status.HTTP_201_CREATED)
def create_model_family(body: ModelFamilyCreate, _: Admin) -> ModelFamily:
    raise not_implemented("POST /admin/model-families")


@router.put("/model-families/{key}", response_model=ModelFamily)
def update_model_family(
    key: str, body: ModelFamilyUpdate, _: Admin, version: IfMatch
) -> ModelFamily:
    raise not_implemented("PUT /admin/model-families/{key}")


@router.delete(
    "/model-families/{key}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_model_family(key: str, _: Admin, version: IfMatch) -> Response:
    """409 while any non-archived model is a member."""
    raise not_implemented("DELETE /admin/model-families/{key}")


# ── models ──────────────────────────────────────────────────────────────────


@router.get("/models", response_model=list[AdminModel])
def list_admin_models(
    _: Admin, include_archived: bool = Query(False, description="Include archived models.")
) -> list[AdminModel]:
    """Every model, disabled/hidden/testing-only included, with key presence."""
    raise not_implemented("GET /admin/models")


@router.post("/models", response_model=AdminModel, status_code=status.HTTP_201_CREATED)
def create_model(body: AdminModelInput, _: Admin) -> AdminModel:
    """The key can never be an archived key (AD-15)."""
    raise not_implemented("POST /admin/models")


@router.post("/models/reorder", response_model=list[AdminModel])
def reorder_models(body: ReorderInput, _: Admin) -> list[AdminModel]:
    """Rewrites ``display_order`` as 10, 20, 30 ... in one revision."""
    raise not_implemented("POST /admin/models/reorder")


@router.get("/models/{key}", response_model=AdminModel)
def get_admin_model(key: str, _: Admin) -> AdminModel:
    raise not_implemented("GET /admin/models/{key}")


@router.put("/models/{key}", response_model=AdminModel)
def replace_model(key: str, body: AdminModelInput, _: Admin, version: IfMatch) -> AdminModel:
    raise not_implemented("PUT /admin/models/{key}")


@router.patch("/models/{key}", response_model=AdminModel)
def patch_model(key: str, body: AdminModelPatch, _: Admin, version: IfMatch) -> AdminModel:
    raise not_implemented("PATCH /admin/models/{key}")


@router.delete("/models/{key}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def archive_model(key: str, _: Admin, version: IfMatch) -> Response:
    """Soft delete (AD-15): the key leaves the registry and is never reused."""
    raise not_implemented("DELETE /admin/models/{key}")


@router.post("/models/{key}/test", response_model=ModelTestResult)
def test_model(key: str, _: Admin) -> ModelTestResult:
    """One 1-token request through the real client. Spends a trivial amount on
    paid models. Rate-limited to 1 per 10 s per model."""
    raise not_implemented("POST /admin/models/{key}/test")
