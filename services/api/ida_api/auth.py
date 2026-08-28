"""Authentication seam.  **Real, and driven by one config flag.**

WHAT IS GATED, AND WHAT DELIBERATELY IS NOT
-------------------------------------------
This platform's product is a *public* benchmark: a results view nobody can read
is not a benchmark, and ``docs/sensitive-material.md`` § 1 says so in as many
words -- **do not gate the results UI**.  What costs money is *triggering* a
run, so that -- and only that -- is what requires a credential (D-49 § 6).

So both modes below resolve an anonymous caller to a real principal holding
``reader``.  Neither returns 401 for "no credential"; a missing credential is
the normal case for the public UI.  The difference between the modes is one
role:

``disabled``  anonymous holds ``reader`` **and** ``runner``.  The default, and
              correct for local dev, CI and the tracer bullet -- all of which
              point at the mock model and cannot reach a paid provider.
``token``     anonymous holds ``reader`` only.  ``runner`` requires a bearer
              token from ``IDA_AUTH_TOKENS``.  This is the deployed posture the
              moment the API is routed publicly.
other         501 at request time, loudly, because a half-implemented auth mode
              that silently allows traffic is the worst possible outcome.

D-5 STILL HOLDS: there is no auth *service*.  When platform SSO/OIDC lands it
validates its token here, in this file, and nowhere else -- every protected
route already depends on :func:`current_principal`, so that stays an edit to
this file plus a mode name, not a sweep through the route handlers.

WHY A STATIC BEARER TOKEN DOES NOT GRANT ``author``
---------------------------------------------------
A shared token in an env var is a weaker credential than the per-person SSO
identity A10 was written against, so a configured token grants ``reader`` and
``runner`` and stops there.  The answer key stays fail-shut until real SSO
lands, rather than becoming unlockable by whoever has the CI secret.
"""

from __future__ import annotations

import hmac
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from ida_core.config import Settings

log = logging.getLogger(__name__)

MIN_TOKEN_LENGTH = 16
"""Shortest token :func:`parse_auth_tokens` will accept.

A length floor, not a strength judgement -- it cannot tell a good token from a
bad one.  What it does catch is the misconfiguration that actually happens: a
placeholder like ``changeme`` or a truncated paste standing in for a credential
that gates spend.  Generate real ones with ``python -c "import secrets;
print(secrets.token_urlsafe(32))"``."""

_ENTRY_SEPARATOR = re.compile(r"[,\s]+")


class AuthConfigError(RuntimeError):
    """The auth configuration cannot be enforced as written.

    Raised at startup (:func:`validate_auth_config`, called from
    ``create_app``) so a pod that cannot enforce its own auth mode fails its
    readiness probe instead of serving while reporting Ready.

    ⚠ ITS MESSAGE GOES TO A POD LOG.  Nothing that constructs one may put a
    token value in it -- see :func:`parse_auth_tokens`.
    """


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

        Nobody holds ``author`` in either mode -- see the module docstring.  The
        anonymous principal holds ``runner`` only when ``auth_mode=disabled``.
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
"""``auth_mode=disabled``: everyone may spend.  Safe only because every context
that runs this way (local dev, CI, previews, the tracer bullet) is pointed at
the mock model by ``MOCK_MODEL_BASE_URL`` -- the other half of the interlock."""

ANONYMOUS_READER = Principal(
    subject="anonymous",
    display_name="Anonymous",
    is_anonymous=True,
    roles=frozenset({"reader"}),
)
"""``auth_mode=token``: the public benchmark reader.

⚠ THE ABSENCE OF ``runner`` HERE IS THE ENTIRE STORY.  If a future edit adds it
back "so the UI can trigger a run", the API is spending money for anyone who can
reach it, which is the exact gap ``docs/sensitive-material.md`` § 6 exists to
close.  ``TestAnonymousCannotSpend`` fails if it comes back."""

TOKEN_ROLES = frozenset({"reader", "runner"})
"""What a configured bearer token grants.  Deliberately not ``author``."""


def parse_auth_tokens(raw: str) -> dict[str, str]:
    """Parse ``IDA_AUTH_TOKENS`` into ``{token: subject}``.

    Format: ``subject:token`` entries separated by commas and/or whitespace.
    Split on the FIRST colon only -- the subject is a label we chose, the token
    is opaque and may contain anything.

    Keyed by token because that is the lookup direction at request time.  The
    subject is what lands in :attr:`Principal.subject` and therefore in the
    enqueue log line, so a run is attributable to whoever triggered it.

    STRICT, AND EVERY REJECTION IS DELIBERATE.  A malformed entry silently
    dropped would leave a deployment enforcing an auth mode with fewer valid
    credentials than its operator believes -- which surfaces as a mysterious 401
    for one person rather than as the configuration error it is.

    ⚠ NO MESSAGE RAISED FROM HERE MAY CONTAIN A TOKEN VALUE.  These errors are
    logged by the failing pod; quoting the offending value would move the secret
    from an env var into the log aggregator.  Entries are identified by position
    and by subject instead.
    """
    tokens: dict[str, str] = {}
    subjects: set[str] = set()
    for position, entry in enumerate(_ENTRY_SEPARATOR.split(raw.strip()), start=1):
        if not entry:
            continue
        subject, separator, token = entry.partition(":")
        if not separator:
            raise AuthConfigError(
                f"auth_tokens entry {position} has no ':'; expected 'subject:token'. "
                "An unattributable token is refused: the subject is what names who "
                "spent the money in the enqueue log."
            )
        subject = subject.strip()
        token = token.strip()
        if not subject:
            raise AuthConfigError(f"auth_tokens entry {position} has an empty subject")
        if len(token) < MIN_TOKEN_LENGTH:
            raise AuthConfigError(
                f"auth_tokens entry {position} (subject {subject!r}) has a token shorter "
                f"than {MIN_TOKEN_LENGTH} characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if token in tokens:
            raise AuthConfigError(
                f"auth_tokens entry {position} (subject {subject!r}) reuses the token "
                f"already assigned to subject {tokens[token]!r}. One token per subject, "
                "or attribution is a guess."
            )
        if subject in subjects:
            raise AuthConfigError(
                f"auth_tokens entry {position} repeats subject {subject!r}. Two "
                "credentials for one subject make revocation ambiguous."
            )
        tokens[token] = subject
        subjects.add(subject)
    return tokens


@lru_cache(maxsize=4)
def _token_index(raw: str) -> tuple[tuple[str, str], ...]:
    """:func:`parse_auth_tokens`, memoised, as an ordered tuple of ``(token, subject)``.

    Parsing per request would be wasteful on the one path that must stay cheap,
    and the input is process configuration -- there are at most a couple of
    distinct values in a process's life (production has one; tests have a few).

    A tuple rather than the dict because the lookup below is a constant-time
    comparison over every entry, not a hash lookup.
    """
    return tuple(parse_auth_tokens(raw).items())


def _principal_for_token(offered: str, raw_tokens: str) -> Principal | None:
    """The principal for ``offered``, or ``None`` if no configured token matches.

    ⚠ COMPARED WITH :func:`hmac.compare_digest`, NOT ``==`` AND NOT A DICT
    LOOKUP.  Both of those short-circuit on the first differing byte, which
    leaks how much of a guessed token was correct to anyone who can time the
    endpoint.  Every configured entry is compared; the loop does not exit early
    on a mismatch.

    ⚠ AND COMPARED AS **BYTES**.  ``compare_digest`` raises ``TypeError`` on a
    ``str`` containing any non-ASCII character -- so comparing the raw strings
    turns ``Authorization: Bearer ünicode`` into an unhandled 500 on the auth
    path, which from outside is indistinguishable from a route that never
    checked.  Encoding first makes a junk credential an ordinary 401.
    """
    offered_bytes = offered.encode("utf-8")
    matched: Principal | None = None
    for token, subject in _token_index(raw_tokens):
        if hmac.compare_digest(offered_bytes, token.encode("utf-8")):
            matched = Principal(
                subject=subject,
                display_name=subject,
                is_anonymous=False,
                roles=TOKEN_ROLES,
            )
    return matched


def _unauthorized(detail: str) -> HTTPException:
    """401 with the challenge RFC 7235 requires.

    ⚠ ``detail`` NEVER INCLUDES WHAT WAS OFFERED.  Echoing a rejected credential
    puts it in the client's console, in proxy logs and in anyone's screenshot.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def validate_auth_config(settings: Settings) -> None:
    """Refuse to build an app that cannot enforce its own auth mode.

    Called from ``create_app``, so the failure is a crash at boot: the readiness
    probe never passes, the rollout halts and the previous replicas keep serving.
    The alternative -- discovering it on the first ``POST /runs`` -- means a
    service that reports Ready while the control it was deployed for is absent.

    Two checks, and the second one runs in *every* mode on purpose:

    1. ``auth_mode=token`` with no usable token is a contradiction.  It is not
       "auth on with nobody allowed"; it is a deployment that was meant to have
       credentials and does not.
    2. Whatever is in ``auth_tokens`` must parse, even while ``disabled``, so a
       typo is found now rather than on the day someone flips the flag.
    """
    tokens = parse_auth_tokens(settings.auth_tokens)
    if settings.auth_mode == "token" and not tokens:
        raise AuthConfigError(
            "auth_mode='token' but auth_tokens is empty: this process cannot enforce "
            "the auth mode it was configured with. Set IDA_AUTH_TOKENS to one or more "
            "'subject:token' pairs, or set IDA_AUTH_MODE=disabled deliberately."
        )
    if settings.auth_mode == "token":
        log.info(
            "auth_mode=token: %d credential(s) configured; anonymous keeps 'reader' only",
            len(tokens),
        )


def get_settings_dep(request: Request) -> Settings:
    """Settings, resolved once at startup and stashed on ``app.state``."""
    return request.app.state.settings


def current_principal(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    authorization: Annotated[
        str | None,
        Header(
            description=(
                "Bearer token. Only needed to enqueue runs, and only when the "
                "deployment sets auth_mode=token; reading is anonymous."
            )
        ),
    ] = None,
) -> Principal:
    """The dependency every principal-aware route uses.

    Resolution, in order:

    * ``auth_mode=disabled`` -> :data:`ANONYMOUS`, and any ``Authorization``
      header is ignored.  There is nothing to validate it against, and 401-ing a
      developer over a stale header in their shell history helps nobody.
    * ``auth_mode=token``, no header -> :data:`ANONYMOUS_READER`.  The public
      reader.  **Not** a 401: the results view is meant to work uncredentialed.
    * ``auth_mode=token``, a header that is not a recognised bearer token -> 401.
      A wrong credential is an error, distinct from having none; degrading it to
      anonymous would surface as a puzzling 403 about a role.
    * anything else -> 501, loudly.
    """
    if settings.auth_mode == "disabled":
        return ANONYMOUS

    if settings.auth_mode == "token":
        if authorization is None:
            return ANONYMOUS_READER
        scheme, separator, offered = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not offered.strip():
            raise _unauthorized("expected an 'Authorization: Bearer <token>' header")
        try:
            principal = _principal_for_token(offered.strip(), settings.auth_tokens)
        except AuthConfigError:
            # Unreachable when the app was built through create_app, which
            # validates first. Kept because the alternative to a 503 here is a
            # 500 -- and a 500 on the auth path is indistinguishable, from the
            # outside, from a route that never checked.
            log.exception("auth_tokens is unparseable; refusing to authenticate anyone")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="authentication is misconfigured on this deployment",
            ) from None
        if principal is None:
            log.warning("rejected an unrecognised bearer token")  # never log the value
            raise _unauthorized("unrecognised bearer token")
        return principal

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            f"auth_mode={settings.auth_mode!r} is not implemented. "
            "Supported modes are 'disabled' and 'token'; platform SSO/OIDC "
            "integration lands in a later phase; see ida_api.auth."
        ),
    )
