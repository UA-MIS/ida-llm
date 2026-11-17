"""The admin gate: **admin routes reject everyone who is not the console.**

WHAT THIS FILE IS DEFENDING (AD-4, AD-5 in the admin-console design).
``/admin/*`` writes models, provider keys and benchmark material, and launches
paid runs. It is reachable only from inside the namespace, and only the
frontend pod holds an ``IDA_ADMIN_TOKENS`` bearer. These tests pin the four
ways that could quietly stop being true:

* a route added later without the gate -- every route is ENUMERATED from
  ``app.routes``, so a new one is covered the moment it exists;
* the run token (the CI secret) being promoted to admin;
* ``auth_mode=disabled`` -- which hands anonymous callers ``runner`` -- being
  read as "anonymous may administer" too;
* a write that is not attributed to a person.
"""

from __future__ import annotations

import hmac
import json
import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from ida_api import auth as auth_module
from ida_api.admin import (
    admin_router,
    audit,
    credentials,
    curriculum,
    dump_openapi,
    material,
    models,
    runs,
    system,
)
from ida_api.admin.deps import require_admin
from ida_api.app import create_app
from ida_api.auth import (
    ADMIN_ROLES,
    ANONYMOUS,
    ANONYMOUS_READER,
    AuthConfigError,
    validate_auth_config,
)
from ida_api.deps import AppContext
from ida_core.config import Settings, repo_root

# Obviously-fake fixtures, long enough to clear MIN_TOKEN_LENGTH.
ADMIN_TOKEN = "admin-token-not-a-real-secret-01"  # noqa: S105 - fixture, and it says so
RUN_TOKEN = "run-token-not-a-real-secret-0001"  # noqa: S105 - ditto
UNKNOWN_TOKEN = "nobody-token-not-a-real-secret-1"  # noqa: S105 - ditto

ACTOR = {"X-IDA-Actor": "octo-prof"}

ADMIN_MODULES = (system, models, credentials, material, curriculum, runs, audit)

_PATH_PARAM = re.compile(r"\{([^}:]+)(?::path)?\}")


def _admin_routes(app) -> list[tuple[str, str]]:
    """Every ``(method, concrete path)`` under ``/admin``, from the live app.

    Read from the app's OWN OpenAPI document rather than a hand-kept list, so a
    route someone adds next month is in this test without anyone remembering to
    put it here. (``app.routes`` is not walkable for this: FastAPI 0.141 keeps
    included routers as lazy ``_IncludedRouter`` nodes.) That every admin route
    IS in the schema is pinned by ``test_every_admin_route_is_in_the_schema``.

    Path parameters get placeholder values -- a slashed one for ``task_id``,
    which is a ``:path`` parameter because task ids are ``<family>/<name>``."""
    found = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/admin/"):
            continue
        concrete = path.replace("{task_id}", "fam/task")
        concrete = _PATH_PARAM.sub("x", concrete)
        for method in sorted(operations):
            found.append((method.upper(), concrete))
    return found


def _app(context: AppContext, *, mode: str, admin: str, run: str = "") -> TestClient:
    context.settings.auth_mode = mode
    context.settings.admin_tokens = admin
    context.settings.auth_tokens = run
    return TestClient(create_app(context))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_on(context: AppContext) -> TestClient:
    """The deployed posture: token mode, a run token and an admin token."""
    return _app(context, mode="token", admin=f"admin-console:{ADMIN_TOKEN}", run=f"ci:{RUN_TOKEN}")


@pytest.fixture
def admin_on_disabled(context: AppContext) -> TestClient:
    """Dev's posture: auth disabled (anonymous may spend), admin token set."""
    return _app(
        context, mode="disabled", admin=f"admin-console:{ADMIN_TOKEN}", run=f"ci:{RUN_TOKEN}"
    )


def test_there_are_admin_routes_to_enumerate(admin_on: TestClient) -> None:
    """Guards the enumeration itself: an empty list would make every test
    below pass vacuously."""
    routes = _admin_routes(admin_on.app)
    assert len(routes) >= 40
    assert ("GET", "/admin/system") in routes
    assert ("PUT", "/admin/tasks/fam/task/samples/x") in routes


def test_every_admin_route_is_in_the_schema_and_behind_the_router_gate() -> None:
    """Structural twin of the behavioural tests below.

    The gate is a ROUTER-level dependency of ``admin_router``, and every admin
    module's routes are included in it and visible in the OpenAPI schema --
    so the schema-driven enumeration below cannot miss one."""
    assert require_admin in {d.dependency for d in admin_router.dependencies}
    spec_ops = {
        (m.upper(), p) for p, ops in dump_openapi.build_spec()["paths"].items() for m in ops
    }
    module_ops = set()
    for module in ADMIN_MODULES:
        for route in module.router.routes:
            assert isinstance(route, APIRoute), route
            assert route.include_in_schema, route.path
            path = "/admin" + route.path.replace(":path}", "}")
            module_ops |= {(m, path) for m in route.methods - {"HEAD", "OPTIONS"}}
    assert module_ops == spec_ops


class TestEveryAdminRouteRejectsNonAdmins:
    """Each test walks EVERY admin route."""

    @staticmethod
    def _assert_all(client: TestClient, headers: dict, expected: int, code: str) -> None:
        wrong = []
        for method, path in _admin_routes(client.app):
            response = client.request(method, path, headers=headers)
            body = response.json() if response.content else {}
            got_code = (body.get("detail") or {}).get("code") if isinstance(body, dict) else None
            if response.status_code != expected or got_code != code:
                wrong.append((method, path, response.status_code, got_code))
        assert not wrong, wrong

    def test_no_bearer_is_401(self, admin_on: TestClient) -> None:
        self._assert_all(admin_on, ACTOR, 401, "unauthenticated")

    def test_unknown_bearer_is_401(self, admin_on: TestClient) -> None:
        self._assert_all(admin_on, {**bearer(UNKNOWN_TOKEN), **ACTOR}, 401, "unauthenticated")

    def test_malformed_authorization_is_401(self, admin_on: TestClient) -> None:
        self._assert_all(
            admin_on, {"Authorization": f"Basic {ADMIN_TOKEN}", **ACTOR}, 401, "unauthenticated"
        )

    def test_non_ascii_bearer_is_401_not_500(self, admin_on: TestClient) -> None:
        response = admin_on.get(
            "/admin/system", headers={"Authorization": "Bearer ünicode-xxxxxxxxxxxx".encode()}
        )
        assert response.status_code == 401

    def test_a_valid_run_token_is_403(self, admin_on: TestClient) -> None:
        """The CI run secret is a real credential that does not carry admin."""
        self._assert_all(admin_on, {**bearer(RUN_TOKEN), **ACTOR}, 403, "forbidden")

    def test_a_valid_run_token_is_403_in_disabled_mode_too(
        self, admin_on_disabled: TestClient
    ) -> None:
        self._assert_all(admin_on_disabled, {**bearer(RUN_TOKEN), **ACTOR}, 403, "forbidden")

    def test_anonymous_in_disabled_mode_is_401(self, admin_on_disabled: TestClient) -> None:
        """AD-5: ``disabled`` gives anonymous ``runner``, and NEVER ``admin``."""
        self._assert_all(admin_on_disabled, ACTOR, 401, "unauthenticated")

    def test_no_admin_tokens_configured_is_503_even_with_a_run_token(
        self, context: AppContext
    ) -> None:
        client = _app(context, mode="token", admin="", run=f"ci:{RUN_TOKEN}")
        self._assert_all(client, {**bearer(RUN_TOKEN), **ACTOR}, 503, "admin_disabled")
        self._assert_all(client, ACTOR, 503, "admin_disabled")

    def test_the_default_settings_leave_admin_dark(self, client: TestClient) -> None:
        """The shipped default: no IDA_ADMIN_TOKENS -> every route 503."""
        self._assert_all(client, ACTOR, 503, "admin_disabled")


class TestMutationsNeedAnActor:
    def test_every_write_without_x_ida_actor_is_400(self, admin_on: TestClient) -> None:
        wrong = []
        for method, path in _admin_routes(admin_on.app):
            if method == "GET":
                continue
            response = admin_on.request(method, path, headers=bearer(ADMIN_TOKEN))
            if response.status_code != 400 or response.json()["detail"]["code"] != "actor_required":
                wrong.append((method, path, response.status_code))
        assert not wrong, wrong

    @pytest.mark.parametrize("actor", ["", "has space", "x" * 40, "semi;colon", "ünï".encode()])
    def test_a_malformed_actor_is_refused(self, admin_on: TestClient, actor) -> None:
        response = admin_on.post(
            "/admin/audit/events",
            headers={**bearer(ADMIN_TOKEN), "X-IDA-Actor": actor},
            json={"action": "auth.sign_in", "login": "octo-prof", "groups_ok": True},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "actor_required"

    def test_a_get_does_not_need_an_actor(self, admin_on: TestClient) -> None:
        assert admin_on.get("/admin/system", headers=bearer(ADMIN_TOKEN)).status_code == 200

    def test_with_bearer_and_actor_every_route_gets_past_the_gate(
        self, admin_on: TestClient
    ) -> None:
        """Nothing answers 401/403/503/400-actor once properly credentialed."""
        for method, path in _admin_routes(admin_on.app):
            response = admin_on.request(method, path, headers={**bearer(ADMIN_TOKEN), **ACTOR})
            assert response.status_code not in (401, 403, 503), (method, path)
            if response.status_code == 400:
                assert response.json()["detail"]["code"] != "actor_required", (method, path)


class TestAdminTokenInEveryMode:
    def test_admin_token_works_in_token_mode(self, admin_on: TestClient) -> None:
        response = admin_on.get("/admin/system", headers=bearer(ADMIN_TOKEN))
        assert response.status_code == 200
        assert response.json()["config_source"] == "yaml"

    def test_admin_token_works_in_disabled_mode(self, admin_on_disabled: TestClient) -> None:
        assert (
            admin_on_disabled.get("/admin/system", headers=bearer(ADMIN_TOKEN)).status_code == 200
        )

    def test_admin_principal_may_read_targets_on_the_public_route(
        self, admin_on: TestClient
    ) -> None:
        """``author`` comes with admin: the console shows gold answers."""
        response = admin_on.get(
            "/tasks/demo/arithmetic-quiz-check?include_targets=true", headers=bearer(ADMIN_TOKEN)
        )
        assert response.status_code == 200
        assert response.json()["targets_redacted"] is False

    def test_run_token_still_cannot_read_targets(self, admin_on: TestClient) -> None:
        response = admin_on.get(
            "/tasks/demo/arithmetic-quiz-check?include_targets=true", headers=bearer(RUN_TOKEN)
        )
        assert response.status_code == 403

    def test_disabled_mode_still_ignores_a_non_admin_header_on_public_routes(
        self, admin_on_disabled: TestClient
    ) -> None:
        """Unchanged behaviour: a stale header in a dev's shell is not a 401."""
        response = admin_on_disabled.get("/models", headers=bearer(UNKNOWN_TOKEN))
        assert response.status_code == 200


class TestAnonymousNeverAdmin:
    """Extends ``TestAnonymousCannotSpend``: the anonymous principals never
    gain ``admin`` (or ``author``) in either mode."""

    @pytest.mark.parametrize("principal", [ANONYMOUS, ANONYMOUS_READER], ids=["disabled", "token"])
    def test_anonymous_holds_neither_admin_nor_author(self, principal) -> None:
        assert "admin" not in principal.roles
        assert "author" not in principal.roles

    def test_admin_roles_are_exactly_these(self) -> None:
        assert frozenset({"reader", "runner", "author", "admin"}) == ADMIN_ROLES


class TestConstantTimeAndConfig:
    def test_every_entry_in_both_lists_is_compared_with_no_early_exit(
        self, context: AppContext, monkeypatch
    ) -> None:
        """One shared code path compares the offered bearer against EVERY admin
        and run token, matched or not -- timing must not reveal which list a
        token is in, or how much of it was right."""
        context.settings.admin_tokens = f"a1:{ADMIN_TOKEN},a2:{'b' * 20}"
        context.settings.auth_tokens = f"ci:{RUN_TOKEN},p:{'c' * 20},q:{'d' * 20}"
        calls: list[bytes] = []
        real = hmac.compare_digest

        def counting(a, b):
            calls.append(b)
            return real(a, b)

        monkeypatch.setattr(auth_module.hmac, "compare_digest", counting)
        for offered in (ADMIN_TOKEN, RUN_TOKEN, UNKNOWN_TOKEN):
            calls.clear()
            auth_module._principal_for_token(offered, context.settings)
            assert len(calls) == 5, offered
            assert all(isinstance(c, bytes) for c in calls)

    def test_admin_tokens_parse_strictly_at_startup_without_quoting_them(self) -> None:
        settings = Settings(admin_tokens="admin-console:tooSmol")
        with pytest.raises(AuthConfigError) as excinfo:
            validate_auth_config(settings)
        assert "IDA_ADMIN_TOKENS" in str(excinfo.value)
        assert "tooSmol" not in str(excinfo.value)

    def test_a_token_in_both_lists_is_refused_without_quoting_it(self) -> None:
        settings = Settings(
            auth_tokens=f"ci:{ADMIN_TOKEN}", admin_tokens=f"admin-console:{ADMIN_TOKEN}"
        )
        with pytest.raises(AuthConfigError) as excinfo:
            validate_auth_config(settings)
        assert ADMIN_TOKEN not in str(excinfo.value)

    def test_create_app_refuses_a_bad_admin_token(self, context: AppContext) -> None:
        context.settings.admin_tokens = "no-colon-here-at-all-xxxxx"
        with pytest.raises(AuthConfigError):
            create_app(context)


class TestErrorEnvelope:
    def test_body_validation_errors_use_the_admin_envelope(self, admin_on: TestClient) -> None:
        response = admin_on.post(
            "/admin/audit/events",
            headers={**bearer(ADMIN_TOKEN), **ACTOR},
            json={"action": "auth.bogus", "login": "octo-prof", "groups_ok": True},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "validation_failed"
        assert detail["issues"][0]["path"] == "action"
        assert detail["issues"][0]["severity"] == "error"

    def test_public_validation_errors_keep_fastapis_shape(self, admin_on: TestClient) -> None:
        """Public 422 bodies are unchanged: a list under ``detail``."""
        response = admin_on.get("/runs?limit=0")
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_writes_without_if_match_are_428(self, admin_on: TestClient) -> None:
        response = admin_on.delete("/admin/models/mock", headers={**bearer(ADMIN_TOKEN), **ACTOR})
        assert response.status_code == 428
        assert response.json()["detail"]["code"] == "precondition_required"

    @pytest.mark.parametrize("value", ["3", '"3"', 'W/"3"'])
    def test_if_match_accepts_the_etag_forms(self, admin_on: TestClient, value: str) -> None:
        response = admin_on.delete(
            "/admin/models/mock", headers={**bearer(ADMIN_TOKEN), **ACTOR, "If-Match": value}
        )
        assert response.status_code == 501  # past the gate; body lands in B3

    def test_system_reports_the_kek_id_and_never_the_key(self, context: AppContext) -> None:
        key = "k1:" + "A" * 43 + "="
        context.settings.credentials_kek = key
        client = _app(context, mode="disabled", admin=f"admin-console:{ADMIN_TOKEN}")
        response = client.get("/admin/system", headers=bearer(ADMIN_TOKEN))
        body = response.json()
        assert body["kek_configured"] is True
        assert body["kek_active_id"] == "k1"
        assert "A" * 43 not in response.text


class TestAdminContract:
    def test_the_committed_openapi_dump_is_current(self) -> None:
        """``docs/admin-api.openapi.json`` is what the frontend builds against.
        Regenerate with ``python -m ida_api.admin.dump_openapi``."""
        committed = (repo_root() / dump_openapi.OUTPUT).read_text()
        assert committed == dump_openapi.render()

    def test_the_dump_holds_only_admin_paths(self) -> None:
        spec = json.loads(dump_openapi.render())
        assert spec["paths"]
        assert all(p.startswith("/admin/") for p in spec["paths"])

    def test_credential_inputs_are_write_only_in_the_contract(self) -> None:
        spec = json.loads(dump_openapi.render())
        props = spec["components"]["schemas"]["CredentialInput"]["properties"]
        assert props["api_key"]["writeOnly"] is True
        assert "api_key" not in spec["components"]["schemas"]["Credential"]["properties"]
