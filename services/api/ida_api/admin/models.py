"""``/admin/models`` and ``/admin/model-families`` (design 5.2).

A model row is rebuilt into a ``ModelEntry`` through the same JSON schema and
pydantic model ``models.yaml`` goes through, and every write re-validates the
WHOLE post-write registry (unique keys, key-source exclusivity, an endpoint to
send to) before it commits -- so the console can never save a registry the CI
gate would reject.

Deleting a model ARCHIVES it (AD-15): it leaves the registry and its key is
never reused, because ``runs.model_key`` is history and a reused key would
quietly attach old scores to a new model.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select

from ida_api.admin.deps import Admin, IfMatch, admin_error, set_etag
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
from ida_api.admin.service import (
    SCOPE_MODELS,
    admin_write,
    bump,
    conflict,
    expect_version,
    not_found,
    require_db_config,
    stamp_new,
    validation_failed,
)
from ida_api.deps import AppContext, get_context
from ida_core.configdb.crypto import DbCredentialResolver, parse_kek
from ida_core.configdb.tables import ModelFamilyRow, ModelRow, ProviderCredentialRow
from ida_core.contracts import ChatMessage, CostRates, SamplingParams, ServingConfig
from ida_core.db import session_scope, utcnow
from ida_core.validation_suite import Issue
from ida_harness.factory import build_client

log = logging.getLogger(__name__)

router = APIRouter(tags=["admin: models"])

TEST_INTERVAL_S = 10.0
"""``POST /models/{key}/test`` at most once per this many seconds per model: it
spends (a trivial amount) on paid models, and a double-click is not two tests."""
_last_test: dict[str, float] = {}
_test_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────── helpers ──


def _to_admin_model(row: ModelRow, credential_names: set[str], kek_configured: bool) -> AdminModel:
    if row.api_key_env:
        uses, present = "env", bool(os.environ.get(row.api_key_env))
    elif row.credential_ref:
        uses, present = "credential", kek_configured and row.credential_ref in credential_names
    else:
        uses, present = "none", True
    return AdminModel.model_construct(
        key=row.key,
        display_name=row.display_name,
        family_key=row.family_key,
        display_order=row.display_order,
        base_url=row.base_url,
        base_url_env=row.base_url_env,
        api_key_env=row.api_key_env,
        credential_ref=row.credential_ref,
        enabled=bool(row.enabled),
        hidden=bool(row.hidden),
        timeout_s=float(row.timeout_s),
        max_retries=int(row.max_retries),
        tags=list(row.tags or []),
        serving=ServingConfig.model_validate(row.serving),
        cost=CostRates(
            input_usd_per_mtok=float(row.cost_input_usd_per_mtok or 0.0),
            output_usd_per_mtok=float(row.cost_output_usd_per_mtok or 0.0),
        ),
        uses=uses,
        key_present=present,
        archived_at=row.archived_at,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
        version=row.version,
    )


def _context_for(session, ctx: AppContext):
    names = set(session.scalars(select(ProviderCredentialRow.name)))
    return names, bool(ctx.settings.credentials_kek.strip())


def _model_view(session, ctx: AppContext, row: ModelRow) -> AdminModel:
    names, kek = _context_for(session, ctx)
    return _to_admin_model(row, names, kek)


def _snapshot(model: AdminModel) -> dict:
    """The audit form of a model: everything but the volatile presence bit."""
    return model.model_dump(mode="json", exclude={"key_present"})


def _check_refs(session, body: AdminModelInput | AdminModelPatch) -> None:
    issues: list[Issue] = []
    family = getattr(body, "family_key", None)
    if family is not None and session.get(ModelFamilyRow, family) is None:
        issues.append(Issue("family_key", f"no model family {family!r}"))
    credential = getattr(body, "credential_ref", None)
    if (
        credential is not None
        and session.scalar(
            select(ProviderCredentialRow.id).where(ProviderCredentialRow.name == credential)
        )
        is None
    ):
        issues.append(Issue("credential_ref", f"no stored credential {credential!r}"))
    if issues:
        raise validation_failed(issues)


def _apply(row: ModelRow, body: AdminModelInput) -> None:
    serving = body.serving.model_dump(mode="json")
    serving["registry_key"] = body.key
    row.display_name = body.display_name
    row.family_key = body.family_key
    row.display_order = body.display_order
    row.base_url = body.base_url
    row.base_url_env = body.base_url_env
    row.api_key_env = body.api_key_env
    row.credential_ref = body.credential_ref
    row.enabled = body.enabled
    row.hidden = body.hidden
    row.timeout_s = body.timeout_s
    row.max_retries = body.max_retries
    row.tags = list(body.tags)
    row.serving = serving
    row.cost_input_usd_per_mtok = body.cost.input_usd_per_mtok
    row.cost_output_usd_per_mtok = body.cost.output_usd_per_mtok


def _live_row(session, key: str) -> ModelRow:
    row = session.get(ModelRow, key)
    if row is None or row.archived_at is not None:
        raise not_found(f"model {key!r}")
    return row


# ──────────────────────────────────────────────────────── model families ──


def _family_view(session, row: ModelFamilyRow) -> ModelFamily:
    members = list(
        session.scalars(
            select(ModelRow.key)
            .where(ModelRow.family_key == row.key, ModelRow.archived_at.is_(None))
            .order_by(ModelRow.display_order.is_(None), ModelRow.display_order, ModelRow.key)
        )
    )
    return ModelFamily(
        key=row.key, display_name=row.display_name, member_keys=members, version=row.version
    )


@router.get("/model-families", response_model=list[ModelFamily])
def list_model_families(_: Admin, ctx: AppContext = Depends(get_context)) -> list[ModelFamily]:
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        rows = session.scalars(select(ModelFamilyRow).order_by(ModelFamilyRow.key))
        return [_family_view(session, r) for r in rows]


@router.post("/model-families", response_model=ModelFamily, status_code=status.HTTP_201_CREATED)
def create_model_family(
    body: ModelFamilyCreate,
    admin: Admin,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> ModelFamily:
    with admin_write(
        ctx,
        admin,
        action="model_family.create",
        entity_type="model_family",
        entity_id=body.key,
        summary=f"create model family {body.key}",
    ) as w:
        if w.session.get(ModelFamilyRow, body.key) is not None:
            raise conflict(f"model family {body.key!r} already exists")
        row = stamp_new(ModelFamilyRow(key=body.key, display_name=body.display_name), admin)
        w.session.add(row)
        w.session.flush()
        view = _family_view(w.session, row)
        w.after = view.model_dump(mode="json")
    set_etag(response, view.version)
    return view


@router.put("/model-families/{key}", response_model=ModelFamily)
def update_model_family(
    key: str,
    body: ModelFamilyUpdate,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> ModelFamily:
    with admin_write(
        ctx,
        admin,
        action="model_family.update",
        entity_type="model_family",
        entity_id=key,
        summary=f"update model family {key}",
        scopes={SCOPE_MODELS},
    ) as w:
        row = w.session.get(ModelFamilyRow, key)
        if row is None:
            raise not_found(f"model family {key!r}")
        before = _family_view(w.session, row)
        expect_version(row, version, before.model_dump(mode="json"))
        row.display_name = body.display_name
        bump(row, admin)
        view = _family_view(w.session, row)
        w.before, w.after = before.model_dump(mode="json"), view.model_dump(mode="json")
    set_etag(response, view.version)
    return view


@router.delete(
    "/model-families/{key}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_model_family(
    key: str, admin: Admin, version: IfMatch, ctx: AppContext = Depends(get_context)
) -> Response:
    """409 while any non-archived model is a member.  Archived members are
    detached (their history keeps the key; the family name is gone)."""
    with admin_write(
        ctx,
        admin,
        action="model_family.delete",
        entity_type="model_family",
        entity_id=key,
        summary=f"delete model family {key}",
        scopes={SCOPE_MODELS},
    ) as w:
        row = w.session.get(ModelFamilyRow, key)
        if row is None:
            raise not_found(f"model family {key!r}")
        view = _family_view(w.session, row)
        expect_version(row, version, view.model_dump(mode="json"))
        if view.member_keys:
            raise conflict(
                f"model family {key!r} still has members {view.member_keys}; move or archive "
                "them first"
            )
        for archived in w.session.scalars(select(ModelRow).where(ModelRow.family_key == key)):
            archived.family_key = None
        w.session.flush()
        w.session.delete(row)
        w.before = view.model_dump(mode="json")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ──────────────────────────────────────────────────────────────── models ──


@router.get("/models", response_model=list[AdminModel])
def list_admin_models(
    _: Admin,
    include_archived: bool = Query(False, description="Include archived models."),
    ctx: AppContext = Depends(get_context),
) -> list[AdminModel]:
    """Every model, disabled/hidden/testing-only included, in registry order,
    with whether its key is present (never the key)."""
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        stmt = select(ModelRow).order_by(ModelRow.position, ModelRow.key)
        if not include_archived:
            stmt = stmt.where(ModelRow.archived_at.is_(None))
        names, kek = _context_for(session, ctx)
        return [_to_admin_model(r, names, kek) for r in session.scalars(stmt)]


@router.post("/models", response_model=AdminModel, status_code=status.HTTP_201_CREATED)
def create_model(
    body: AdminModelInput, admin: Admin, response: Response, ctx: AppContext = Depends(get_context)
) -> AdminModel:
    """The key can never be an archived key (AD-15)."""
    with admin_write(
        ctx,
        admin,
        action="model.create",
        entity_type="model",
        entity_id=body.key,
        summary=f"create model {body.key}",
        scopes={SCOPE_MODELS},
    ) as w:
        existing = w.session.get(ModelRow, body.key)
        if existing is not None:
            raise conflict(
                f"model key {body.key!r} is archived and can never be reused: its runs are history"
                if existing.archived_at is not None
                else f"model {body.key!r} already exists"
            )
        _check_refs(w.session, body)
        position = (w.session.scalar(select(func.max(ModelRow.position))) or 0) + 10
        row = stamp_new(ModelRow(key=body.key, position=position), admin)
        _apply(row, body)
        w.session.add(row)
        w.session.flush()
        view = _model_view(w.session, ctx, row)
        w.after = _snapshot(view)
    set_etag(response, view.version)
    return view


@router.post("/models/reorder", response_model=list[AdminModel])
def reorder_models(
    body: ReorderInput, admin: Admin, ctx: AppContext = Depends(get_context)
) -> list[AdminModel]:
    """Rewrites ``display_order`` as 10, 20, 30 ... for the listed models, in the
    listed order, in one revision.  Models not listed keep their order."""
    if len(set(body.order)) != len(body.order):
        raise validation_failed([Issue("order", "a model is listed twice")])
    with admin_write(
        ctx,
        admin,
        action="model.reorder",
        entity_type="model",
        entity_id="*",
        summary=f"reorder {len(body.order)} model(s)",
        scopes={SCOPE_MODELS},
    ) as w:
        rows = []
        for index, key in enumerate(body.order):
            row = w.session.get(ModelRow, key)
            if row is None or row.archived_at is not None:
                raise validation_failed([Issue(f"order[{index}]", f"no live model {key!r}")])
            rows.append(row)
        w.before = {r.key: r.display_order for r in rows}
        for position, row in enumerate(rows, start=1):
            if row.display_order != position * 10:
                row.display_order = position * 10
                bump(row, admin)
        w.after = {r.key: r.display_order for r in rows}
    with session_scope(ctx.session_factory) as session:
        names, kek = _context_for(session, ctx)
        stmt = (
            select(ModelRow)
            .where(ModelRow.archived_at.is_(None))
            .order_by(ModelRow.position, ModelRow.key)
        )
        return [_to_admin_model(r, names, kek) for r in session.scalars(stmt)]


@router.get("/models/{key}", response_model=AdminModel)
def get_admin_model(
    key: str, _: Admin, response: Response, ctx: AppContext = Depends(get_context)
) -> AdminModel:
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        row = session.get(ModelRow, key)
        if row is None:
            raise not_found(f"model {key!r}")
        view = _model_view(session, ctx, row)
    set_etag(response, view.version)
    return view


@router.put("/models/{key}", response_model=AdminModel)
def replace_model(
    key: str,
    body: AdminModelInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminModel:
    """Full replace.  The key is immutable (a rename is create + archive)."""
    if body.key != key:
        raise validation_failed([Issue("key", "the key cannot change; create a new model")])
    with admin_write(
        ctx,
        admin,
        action="model.update",
        entity_type="model",
        entity_id=key,
        summary=f"update model {key}",
        scopes={SCOPE_MODELS},
    ) as w:
        row = _live_row(w.session, key)
        before = _model_view(w.session, ctx, row)
        expect_version(row, version, before.model_dump(mode="json"))
        _check_refs(w.session, body)
        _apply(row, body)
        bump(row, admin)
        w.session.flush()
        view = _model_view(w.session, ctx, row)
        w.before, w.after = _snapshot(before), _snapshot(view)
    set_etag(response, view.version)
    return view


@router.patch("/models/{key}", response_model=AdminModel)
def patch_model(
    key: str,
    body: AdminModelPatch,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminModel:
    """Quick toggles: only the fields the body names change; an explicit
    ``null`` clears ``family_key``/``display_order``."""
    changes = body.model_dump(include=body.model_fields_set)
    for flag in ("enabled", "hidden"):
        if flag in changes and changes[flag] is None:
            raise validation_failed([Issue(flag, "must be true or false")])
    with admin_write(
        ctx,
        admin,
        action="model.update",
        entity_type="model",
        entity_id=key,
        summary=f"update model {key}: {', '.join(sorted(changes)) or 'nothing'}",
        scopes={SCOPE_MODELS},
    ) as w:
        row = _live_row(w.session, key)
        before = _model_view(w.session, ctx, row)
        expect_version(row, version, before.model_dump(mode="json"))
        _check_refs(w.session, body)
        for field_name, value in changes.items():
            setattr(row, field_name, value)
        bump(row, admin)
        w.session.flush()
        view = _model_view(w.session, ctx, row)
        w.before, w.after = _snapshot(before), _snapshot(view)
    set_etag(response, view.version)
    return view


@router.delete("/models/{key}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def archive_model(
    key: str, admin: Admin, version: IfMatch, ctx: AppContext = Depends(get_context)
) -> Response:
    """Soft delete (AD-15): the key leaves the registry and is never reused."""
    with admin_write(
        ctx,
        admin,
        action="model.delete",
        entity_type="model",
        entity_id=key,
        summary=f"archive model {key}",
        scopes={SCOPE_MODELS},
    ) as w:
        row = _live_row(w.session, key)
        before = _model_view(w.session, ctx, row)
        expect_version(row, version, before.model_dump(mode="json"))
        row.archived_at = utcnow()
        bump(row, admin)
        w.before = _snapshot(before)
        w.after = {"archived_at": row.archived_at.isoformat()}
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/models/{key}/test", response_model=ModelTestResult)
def test_model(key: str, admin: Admin, ctx: AppContext = Depends(get_context)) -> ModelTestResult:
    """One 1-token request through the real client, with the resolved key.

    Spends a trivial amount on paid models (the console says so), so it is
    rate-limited per model and audited.  The error text is truncated and
    scrubbed of the key before it is returned."""
    require_db_config(ctx)
    try:
        entry = ctx.registry.get(key)
    except KeyError:
        raise not_found(f"live model {key!r}") from None
    now = time.monotonic()
    with _test_lock:
        last = _last_test.get(key)
        if last is not None and now - last < TEST_INTERVAL_S:
            raise admin_error(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate_limited",
                f"model {key!r} was tested {now - last:.0f}s ago; wait {TEST_INTERVAL_S:.0f}s "
                "between tests",
            )
        _last_test[key] = now

    resolver = DbCredentialResolver(ctx.session_factory, parse_kek(ctx.settings.credentials_kek))
    started = time.perf_counter()
    secret: str | None = None
    try:
        from ida_core.registry import resolve_api_key

        secret = resolve_api_key(entry, credentials=resolver)
        with build_client(entry, api_key=secret) as client:
            client.complete(
                [ChatMessage(role="user", content="Reply with OK.")],
                SamplingParams(max_tokens=1),
            )
        result = ModelTestResult(ok=True, latency_ms=(time.perf_counter() - started) * 1000)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if secret:
            message = message.replace(secret, "***")
        result = ModelTestResult(
            ok=False, latency_ms=(time.perf_counter() - started) * 1000, error=message[:300]
        )
    finally:
        secret = None
    with admin_write(
        ctx,
        admin,
        action="model.test",
        entity_type="model",
        entity_id=key,
        summary=f"test model {key}",
        bumps_revision=False,
    ) as w:
        w.after = {"ok": result.ok, "latency_ms": round(result.latency_ms, 1)}
    log.info("admin %s tested model %s: ok=%s", admin.actor, key, result.ok)
    return result
