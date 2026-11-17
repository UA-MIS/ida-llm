"""``/admin/credentials``: admin-entered provider keys, encrypted at rest.

PR B1 registers the contract; the handlers land in B3.  No response from this
module ever carries key material in any form."""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import Response

from ida_api.admin.deps import Admin, IfMatch, not_implemented
from ida_api.admin.schemas import Credential, CredentialInput, CredentialRotateInput

router = APIRouter(tags=["admin: credentials"])


@router.get("/credentials", response_model=list[Credential])
def list_credentials(_: Admin) -> list[Credential]:
    raise not_implemented("GET /admin/credentials")


@router.post("/credentials", response_model=Credential, status_code=status.HTTP_201_CREATED)
def create_credential(body: CredentialInput, _: Admin) -> Credential:
    """503 ``kek_missing`` when no key-encryption key is configured."""
    raise not_implemented("POST /admin/credentials")


@router.put("/credentials/{name}/secret", response_model=Credential)
def rotate_credential(
    name: str, body: CredentialRotateInput, _: Admin, version: IfMatch
) -> Credential:
    raise not_implemented("PUT /admin/credentials/{name}/secret")


@router.delete(
    "/credentials/{name}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_credential(name: str, _: Admin, version: IfMatch) -> Response:
    """409 while any non-archived model references it."""
    raise not_implemented("DELETE /admin/credentials/{name}")
