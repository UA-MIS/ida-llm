"""``/admin/runs`` and ``/admin/sweeps``: launch, estimate, watch, cancel.

PR B1 registers the contract; the handlers land in B5."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from ida_api.admin.deps import Admin, not_implemented
from ida_api.admin.schemas import (
    AdminEnqueueResponse,
    AdminRunDetail,
    AdminRunList,
    AdminRunRecord,
    RunEstimate,
    RunLaunchInput,
    SweepDetail,
    SweepList,
    SweepSummary,
)
from ida_core.contracts import RunStatus

router = APIRouter(tags=["admin: runs"])

MAX_ADMIN_PAGE = 200


@router.post("/runs/estimate", response_model=RunEstimate)
def estimate_runs(body: RunLaunchInput, _: Admin) -> RunEstimate:
    """No write. The launcher calls it live (debounced)."""
    raise not_implemented("POST /admin/runs/estimate")


@router.post("/runs", response_model=AdminEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def launch_runs(body: RunLaunchInput, _: Admin) -> AdminEnqueueResponse:
    """422 ``cap_exceeded`` over the sweep caps; 409
    ``spend_confirmation_required`` until ``confirm_spend_usd`` covers the
    estimate when it is over the ceiling or touches a testing-only model."""
    raise not_implemented("POST /admin/runs")


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
) -> AdminRunList:
    raise not_implemented("GET /admin/runs")


@router.get("/runs/{run_id}", response_model=AdminRunDetail)
def get_admin_run(run_id: str, _: Admin) -> AdminRunDetail:
    """UNREDACTED: explanations and errors included."""
    raise not_implemented("GET /admin/runs/{run_id}")


@router.get("/runs/{run_id}/results/{sample_id}/transcript")
def get_admin_transcript(run_id: str, sample_id: str, _: Admin) -> dict:
    raise not_implemented("GET /admin/runs/{run_id}/results/{sample_id}/transcript")


@router.post("/runs/{run_id}/cancel", response_model=AdminRunRecord)
def cancel_run(run_id: str, _: Admin) -> AdminRunRecord:
    """Idempotent: a terminal run is returned unchanged with 200."""
    raise not_implemented("POST /admin/runs/{run_id}/cancel")


@router.get("/sweeps", response_model=SweepList)
def list_sweeps(
    _: Admin,
    limit: int = Query(50, ge=1, le=MAX_ADMIN_PAGE),
    cursor: str | None = Query(None),
) -> SweepList:
    raise not_implemented("GET /admin/sweeps")


@router.get("/sweeps/{sweep_id}", response_model=SweepDetail)
def get_sweep(sweep_id: str, _: Admin) -> SweepDetail:
    raise not_implemented("GET /admin/sweeps/{sweep_id}")


@router.post("/sweeps/{sweep_id}/cancel", response_model=SweepSummary)
def cancel_sweep(sweep_id: str, _: Admin) -> SweepSummary:
    raise not_implemented("POST /admin/sweeps/{sweep_id}/cancel")
