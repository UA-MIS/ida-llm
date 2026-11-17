"""``/admin/credentials``: admin-entered provider keys, encrypted at rest (AD-10).

⚠ NO RESPONSE, LOG LINE OR AUDIT ROW FROM THIS MODULE EVER CARRIES KEY MATERIAL.
The key arrives once, as a ``SecretStr`` (so a repr or traceback shows
``**********``), is encrypted under the active KEK, and the reference is
dropped.  Responses are metadata only; audit rows are ``{name, provider,
kek_id}``.  ``test_admin_credentials`` plants a key and greps every response,
log record, audit row and stored column for it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select

from ida_api.admin.deps import Admin, IfMatch, admin_error, set_etag
from ida_api.admin.schemas import Credential, CredentialInput, CredentialRotateInput
from ida_api.admin.service import (
    SCOPE_MODELS,
    admin_write,
    bump,
    conflict,
    expect_version,
    not_found,
    require_db_config,
    stamp_new,
)
from ida_api.deps import AppContext, get_context
from ida_core.configdb.crypto import KeyRing, encrypt, parse_kek
from ida_core.configdb.tables import ModelRow, ProviderCredentialRow
from ida_core.db import session_scope, utcnow
from ida_core.ids import new_id

router = APIRouter(tags=["admin: credentials"])


def _ring(ctx: AppContext) -> KeyRing:
    ring = parse_kek(ctx.settings.credentials_kek)
    if ring is None:
        raise admin_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "kek_missing",
            "no key-encryption key is configured (IDA_CREDENTIALS_KEK is unset), so a "
            "provider key cannot be stored",
        )
    return ring


def _view(session, row: ProviderCredentialRow) -> Credential:
    used_by = list(
        session.scalars(
            select(ModelRow.key)
            .where(ModelRow.credential_ref == row.name, ModelRow.archived_at.is_(None))
            .order_by(ModelRow.key)
        )
    )
    return Credential(
        name=row.name,
        provider=row.provider,
        kek_id=row.kek_id,
        created_at=row.created_at,
        created_by=row.created_by,
        rotated_at=row.rotated_at,
        last_used_at=row.last_used_at,
        used_by_models=used_by,
        version=row.version,
    )


def _audit_form(row: ProviderCredentialRow) -> dict:
    """What an audit row may say about a credential: metadata, never material."""
    return {"name": row.name, "provider": row.provider, "kek_id": row.kek_id}


def _by_name(session, name: str) -> ProviderCredentialRow:
    row = session.scalar(select(ProviderCredentialRow).where(ProviderCredentialRow.name == name))
    if row is None:
        raise not_found(f"credential {name!r}")
    return row


@router.get("/credentials", response_model=list[Credential])
def list_credentials(_: Admin, ctx: AppContext = Depends(get_context)) -> list[Credential]:
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        rows = session.scalars(select(ProviderCredentialRow).order_by(ProviderCredentialRow.name))
        return [_view(session, r) for r in rows]


@router.post("/credentials", response_model=Credential, status_code=status.HTTP_201_CREATED)
def create_credential(
    body: CredentialInput, admin: Admin, response: Response, ctx: AppContext = Depends(get_context)
) -> Credential:
    """503 ``kek_missing`` when no key-encryption key is configured."""
    require_db_config(ctx)
    ring = _ring(ctx)
    with admin_write(
        ctx,
        admin,
        action="credential.create",
        entity_type="credential",
        entity_id=body.name,
        summary=f"add provider credential {body.name}",
    ) as w:
        if w.session.scalar(
            select(ProviderCredentialRow.id).where(ProviderCredentialRow.name == body.name)
        ):
            raise conflict(f"credential {body.name!r} already exists; rotate it instead")
        credential_id = new_id("cred")
        ciphertext, nonce, kid = encrypt(
            ring,
            credential_id=credential_id,
            name=body.name,
            plaintext=body.api_key.get_secret_value(),
        )
        row = stamp_new(
            ProviderCredentialRow(
                id=credential_id,
                name=body.name,
                provider=body.provider,
                ciphertext=ciphertext,
                nonce=nonce,
                kek_id=kid,
            ),
            admin,
        )
        w.session.add(row)
        w.session.flush()
        view = _view(w.session, row)
        w.after = _audit_form(row)
    set_etag(response, view.version)
    return view


@router.put("/credentials/{name}/secret", response_model=Credential)
def rotate_credential(
    name: str,
    body: CredentialRotateInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> Credential:
    """Replace the key.  Every process's in-memory copy is keyed by row
    version, so the next job decrypts the new one -- no restart."""
    require_db_config(ctx)
    ring = _ring(ctx)
    with admin_write(
        ctx,
        admin,
        action="credential.rotate",
        entity_type="credential",
        entity_id=name,
        summary=f"rotate provider credential {name}",
    ) as w:
        row = _by_name(w.session, name)
        expect_version(row, version, _view(w.session, row).model_dump(mode="json"))
        w.before = _audit_form(row)
        row.ciphertext, row.nonce, row.kek_id = encrypt(
            ring, credential_id=row.id, name=row.name, plaintext=body.api_key.get_secret_value()
        )
        row.rotated_at = utcnow()
        bump(row, admin)
        w.session.flush()
        view = _view(w.session, row)
        w.after = _audit_form(row)
    set_etag(response, view.version)
    return view


@router.delete(
    "/credentials/{name}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_credential(
    name: str, admin: Admin, version: IfMatch, ctx: AppContext = Depends(get_context)
) -> Response:
    """409 while any non-archived model references it.  Archived models that
    named it are detached."""
    with admin_write(
        ctx,
        admin,
        action="credential.delete",
        entity_type="credential",
        entity_id=name,
        summary=f"delete provider credential {name}",
        scopes={SCOPE_MODELS},
    ) as w:
        row = _by_name(w.session, name)
        view = _view(w.session, row)
        expect_version(row, version, view.model_dump(mode="json"))
        if view.used_by_models:
            raise conflict(
                f"credential {name!r} is used by {view.used_by_models}; point them elsewhere first"
            )
        for archived in w.session.scalars(select(ModelRow).where(ModelRow.credential_ref == name)):
            archived.credential_ref = None
        w.session.flush()
        w.before = _audit_form(row)
        w.session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
