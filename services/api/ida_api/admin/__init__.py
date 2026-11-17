"""The admin API: everything under ``/admin``.

Mounted by :func:`ida_api.app.create_app`.  :data:`admin_router` carries
:func:`~ida_api.admin.deps.require_admin` as a ROUTER-LEVEL dependency, so a
route added to any module below is gated whether or not its author remembered
-- and ``test_admin_auth`` enumerates ``app.routes`` to prove it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ida_api.admin import audit, credentials, curriculum, material, models, runs, system
from ida_api.admin.deps import require_admin
from ida_api.admin.schemas import AdminErrorResponse

_ERRORS = {
    code: {"model": AdminErrorResponse} for code in (400, 401, 403, 404, 409, 422, 428, 501, 503)
}

admin_router = APIRouter(dependencies=[Depends(require_admin)], responses=_ERRORS)
for _module in (system, models, credentials, material, curriculum, runs, audit):
    admin_router.include_router(_module.router)

__all__ = ["admin_router"]
