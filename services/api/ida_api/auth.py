"""Authentication seam.  **A placeholder, on purpose (D-5).**

There is no auth service in this architecture.  When the platform's SSO/OIDC
lands, the API will validate the platform-issued token here and nowhere else --
every protected route already depends on :func:`current_principal`, so wiring
real auth is an edit to *this file* and a config flag, not a sweep through the
route handlers.

Until then ``auth_mode="disabled"`` yields an anonymous principal.  This is
explicit and visible rather than "no auth code anywhere", so that shipping to a
public ingress without changing it is an obvious mistake rather than an
invisible one.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from ida_core.config import Settings


@dataclass(frozen=True)
class Principal:
    """Who is making the request."""

    subject: str
    display_name: str
    is_anonymous: bool
    roles: frozenset[str] = frozenset()

    def require_role(self, role: str) -> None:
        """Raise 403 unless the principal holds ``role``.

        Roles in use today:

        ``reader``  read runs, results and redacted task specs
        ``runner``  enqueue runs (spends money)
        ``author``  read unredacted task specs, i.e. the gold answers

        The anonymous principal deliberately holds ``reader`` and ``runner`` but
        **not** ``author``: the skeleton has no auth, so anything gated on
        ``author`` is effectively closed until SSO lands. That is the correct
        default for the answer key (A10) -- fail shut, not open.
        """
        if role not in self.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"role {role!r} required"
            )


ANONYMOUS = Principal(
    subject="anonymous",
    display_name="Anonymous (auth disabled)",
    is_anonymous=True,
    roles=frozenset({"reader", "runner"}),
)


def get_settings_dep(request: Request) -> Settings:
    """Settings, resolved once at startup and stashed on ``app.state``."""
    return request.app.state.settings


def current_principal(settings: Settings = Depends(get_settings_dep)) -> Principal:
    """The dependency every protected route uses.

    ``auth_mode``:

    ``disabled``  -> :data:`ANONYMOUS` (the skeleton's only supported mode)
    anything else -> 501, loudly, because a half-implemented auth mode that
                     silently allows traffic is the worst possible outcome.
    """
    if settings.auth_mode == "disabled":
        return ANONYMOUS
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            f"auth_mode={settings.auth_mode!r} is not implemented. "
            "Platform SSO/OIDC integration lands in a later phase; see ida_api.auth."
        ),
    )
