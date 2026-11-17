"""The admin API's shared plumbing: who is calling, on whose behalf, and how
errors look.

THE TRUST CHAIN (AD-4), IN ONE PARAGRAPH
----------------------------------------
The API has no ingress; only pods in the namespace can reach it, and only the
frontend pod holds an ``IDA_ADMIN_TOKENS`` bearer.  The bearer proves *the
console* is calling.  ``X-IDA-Actor`` names *who* is using the console -- the
GitHub login the frontend verified through Dex.  The API believes that header
**only** because the bearer is an admin token; on any other principal it is
never consulted, because no other principal reaches an ``/admin`` handler.

Everything here is a FastAPI dependency or a small helper, so each admin route
declares what it needs and the router-level :func:`require_admin` guarantees no
route can forget the gate (``test_admin_auth`` enumerates ``app.routes`` and
proves it for every route, including ones added later).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ida_api.admin.schemas import GITHUB_LOGIN_PATTERN, ErrorCode, Issue
from ida_api.auth import (
    Principal,
    _token_index,
    bearer_from_header,
    get_settings_dep,
    resolve_bearer,
)
from ida_core.config import Settings

log = logging.getLogger(__name__)

ADMIN_PREFIX = "/admin"

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
"""Methods that must name an actor.  POSTs that write nothing (``/runs/estimate``,
``/tasks/validate``) are included anyway: one rule the BFF always satisfies is
easier to audit than a list of exceptions."""

_GITHUB_LOGIN = re.compile(GITHUB_LOGIN_PATTERN)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MAX_ACTOR_SUB_LENGTH = 255


# ─────────────────────────────────────────────────────────── the envelope ──


def admin_error(
    status_code: int,
    code: ErrorCode,
    message: str,
    *,
    issues: list[Issue] | None = None,
    current: Any = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """An ``HTTPException`` whose body is the design's error envelope.

    FastAPI renders ``HTTPException(detail=<dict>)`` as ``{"detail": <dict>}``,
    which is exactly ``{"detail": {"code", "message", "issues"?, "current"?}}``
    -- so every admin error goes through here and the UI can switch on
    ``detail.code`` without guessing at shapes.

    ⚠ NEVER PUT A SECRET IN ``message``.  It is returned to the browser.
    """
    detail: dict[str, Any] = {"code": code, "message": message}
    if issues is not None:
        detail["issues"] = [i.model_dump() for i in issues]
    if current is not None:
        detail["current"] = jsonable_encoder(current)
    return HTTPException(status_code=status_code, detail=detail, headers=headers)


def not_implemented(what: str) -> HTTPException:
    """The contract route exists; its backend PR has not landed yet.

    Every route in the design's endpoint table is registered from PR B1 on, so
    the OpenAPI dump the frontend builds against is complete from day one and
    ``test_admin_auth`` gates every route the moment it exists.  The bodies
    arrive in B3/B4/B5; until then they answer 501 rather than 404, so "not
    built yet" cannot be mistaken for "wrong path"."""
    return admin_error(
        status.HTTP_501_NOT_IMPLEMENTED,
        "not_implemented",
        f"{what} is part of the admin API contract but is not implemented yet",
    )


async def admin_validation_error_handler(request: Request, exc: RequestValidationError):
    """Request-body/query validation failures, in the admin envelope.

    Installed app-wide but ACTS only under ``/admin``: every other path is
    handed to FastAPI's stock handler unchanged, so public 422 bodies stay
    byte-identical.  Under ``/admin`` the pydantic errors become ``Issue``\\s
    with dotted paths (``serving.model_id``) the console pins to form fields.
    """
    if not request.url.path.startswith(ADMIN_PREFIX + "/"):
        from fastapi.exception_handlers import request_validation_exception_handler

        return await request_validation_exception_handler(request, exc)
    issues = []
    for error in exc.errors():
        loc = [str(part) for part in error.get("loc", ()) if part not in ("body",)]
        issues.append(
            Issue(
                path=".".join(loc) or "body", message=str(error.get("msg", "invalid"))
            ).model_dump()
        )
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "validation_failed",
                "message": "Request failed validation",
                "issues": issues,
            }
        },
    )


# ───────────────────────────────────────────────────────────── the gate ──


@dataclass(frozen=True)
class AdminContext:
    """Who is acting, for every admin handler and every audit row."""

    principal: Principal
    """The admin-token principal. ``subject`` is the token's label
    (``admin-console``) and lands in ``audit_log.via_subject``."""

    actor_login: str | None
    """The GitHub login from ``X-IDA-Actor``. Always set on a mutation."""

    actor_sub: str | None
    """The Dex ``sub`` from ``X-IDA-Actor-Sub``, when sent."""

    request_id: str

    @property
    def actor(self) -> str:
        """The name to record: the person if known, else the token subject."""
        return self.actor_login or self.principal.subject


def require_admin(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    authorization: Annotated[str | None, Header(description="Bearer <admin token>")] = None,
    x_ida_actor: Annotated[
        str | None,
        Header(description="GitHub login of the person using the console. Required on writes."),
    ] = None,
    x_ida_actor_sub: Annotated[str | None, Header(description="Dex subject of the actor.")] = None,
    x_request_id: Annotated[str | None, Header()] = None,
) -> AdminContext:
    """The dependency on EVERY ``/admin`` route (attached at the router).

    In order, and the order is the contract:

    1. No admin token configured -> **503** ``admin_disabled``.  The console is
       dark in this environment; saying so is more useful than a 401 that
       sends someone hunting for a credential that does not exist.
    2. No bearer, a malformed header or an unknown token -> **401**.
    3. A valid RUN token -> **403**.  It is a real credential that does not
       carry ``admin``; a 401 would suggest it was not recognised at all.
       This holds in ``auth_mode=disabled`` too: the admin gate never hands
       anything to an anonymous or run-token caller (AD-5).
    4. A mutating method without a well-formed ``X-IDA-Actor`` -> **400**
       ``actor_required``.  Every write is attributed to a person.

    Constant-time comparison over the admin AND run token lists is
    :func:`ida_api.auth._principal_for_token` -- the same code path
    ``current_principal`` uses, so there is one place a bearer is judged.
    """
    try:
        configured = bool(_token_index(settings.admin_tokens))
    except Exception:
        configured = False  # validated at boot; belt and braces
    if not configured:
        raise admin_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "admin_disabled",
            "the admin API is not enabled on this deployment (IDA_ADMIN_TOKENS is unset)",
        )

    offered = bearer_from_header(authorization)
    if offered is None:
        raise admin_error(
            status.HTTP_401_UNAUTHORIZED,
            "unauthenticated",
            "expected an 'Authorization: Bearer <admin token>' header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = resolve_bearer(offered, settings)
    if principal is None:
        log.warning("admin: rejected an unrecognised bearer token")  # never the value
        raise admin_error(
            status.HTTP_401_UNAUTHORIZED,
            "unauthenticated",
            "unrecognised bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if "admin" not in principal.roles:
        log.warning("admin: refused non-admin principal %s", principal.subject)
        raise admin_error(status.HTTP_403_FORBIDDEN, "forbidden", "role 'admin' required")

    actor_login = x_ida_actor.strip() if x_ida_actor else None
    if actor_login is not None and not _GITHUB_LOGIN.match(actor_login):
        raise admin_error(
            status.HTTP_400_BAD_REQUEST,
            "actor_required",
            "X-IDA-Actor must be a GitHub login (letters, digits and '-', at most 39)",
        )
    if request.method in MUTATING_METHODS and not actor_login:
        raise admin_error(
            status.HTTP_400_BAD_REQUEST,
            "actor_required",
            "admin writes must name the person acting in X-IDA-Actor",
        )
    actor_sub = (x_ida_actor_sub or "").strip()[:MAX_ACTOR_SUB_LENGTH] or None
    request_id = (
        x_request_id.strip()
        if x_request_id and _REQUEST_ID.match(x_request_id.strip())
        else uuid.uuid4().hex
    )
    log.info(
        "admin %s %s actor=%s via=%s request=%s",
        request.method,
        request.url.path,
        actor_login or "-",
        principal.subject,
        request_id,
    )
    return AdminContext(
        principal=principal,
        actor_login=actor_login,
        actor_sub=actor_sub,
        request_id=request_id,
    )


Admin = Annotated[AdminContext, Depends(require_admin)]
"""What a handler declares to receive the :class:`AdminContext`.  FastAPI caches
the dependency per request, so the router-level gate and this run it once."""


# ──────────────────────────────────────────────────── optimistic concurrency ──


_IF_MATCH = re.compile(r'^\s*(?:W/)?"?(\d{1,18})"?\s*$')


def if_match_version(
    if_match: Annotated[
        str | None,
        Header(description='The resource version this edit was made against, e.g. "3".'),
    ] = None,
) -> int:
    """The version a write was made against, from ``If-Match``.

    Required on every PUT/PATCH/DELETE of a config row: two professors editing
    the same class must not silently overwrite each other.  Accepts ``3``,
    ``"3"`` and ``W/"3"`` because the ETag this API sends is ``"3"`` and a
    client echoing it verbatim is the common case.  Missing -> **428**.
    """
    if if_match is None or not if_match.strip():
        raise admin_error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "precondition_required",
            "this write needs an If-Match header carrying the version you loaded",
        )
    match = _IF_MATCH.match(if_match)
    if match is None:
        raise admin_error(
            status.HTTP_400_BAD_REQUEST,
            "validation_failed",
            "If-Match must be a resource version number",
            issues=[Issue(path="If-Match", message="expected a version number")],
        )
    return int(match.group(1))


IfMatch = Annotated[int, Depends(if_match_version)]


def check_version(*, expected: int, actual: int, current: Any) -> None:
    """409 ``version_conflict`` (with the current row) unless they agree."""
    if expected != actual:
        raise admin_error(
            status.HTTP_409_CONFLICT,
            "version_conflict",
            f"this record changed since you loaded it (you have version {expected}, "
            f"it is now {actual}); reload and re-apply your edit",
            current=current,
        )


def set_etag(response: Response, version: int) -> None:
    """``ETag: "<version>"`` -- what the client echoes back as ``If-Match``."""
    response.headers["ETag"] = f'"{version}"'
