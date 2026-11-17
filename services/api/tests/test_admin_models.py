"""``/admin/models`` and ``/admin/model-families`` (design 5.2, 10.1)."""

from __future__ import annotations

import pytest
from _admin_helpers import ACTOR, HEADERS, admin_client, admin_context, if_match
from fastapi.testclient import TestClient
from sqlalchemy import select

from ida_core.configdb.tables import AuditLogRow, ConfigRevisionRow
from ida_core.db import session_scope


@pytest.fixture
def ctx(tmp_path):
    return admin_context(tmp_path)


@pytest.fixture
def client(ctx) -> TestClient:
    return admin_client(ctx)


NEW_MODEL = {
    "key": "acme-small",
    "display_name": "Acme Small",
    "family_key": None,
    "display_order": None,
    "base_url": "https://api.acme.example/v1",
    "base_url_env": None,
    "api_key_env": "ACME_API_KEY",
    "credential_ref": None,
    "enabled": True,
    "hidden": False,
    "timeout_s": 60,
    "max_retries": 2,
    "tags": ["paid"],
    "serving": {"model_id": "acme-small-1", "serving_stack": "openai_api"},
    "cost": {"input_usd_per_mtok": 0.5, "output_usd_per_mtok": 1.5},
}


def _revision(ctx) -> int:
    with session_scope(ctx.session_factory) as s:
        return max(s.scalars(select(ConfigRevisionRow.id)))


def _audit(ctx, action: str) -> list[AuditLogRow]:
    with session_scope(ctx.session_factory) as s:
        return list(s.scalars(select(AuditLogRow).where(AuditLogRow.action == action)))


def test_lists_every_model_with_key_presence_never_the_key(client, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-appear-0000")
    response = client.get("/admin/models", headers=HEADERS)
    assert response.status_code == 200
    models = {m["key"]: m for m in response.json()}
    assert models["mock"]["uses"] == "none" and models["mock"]["key_present"] is True
    assert "sk-should-never-appear-0000" not in response.text
    assert all(m["version"] == 1 for m in models.values())


def test_create_bumps_the_revision_audits_and_appears_publicly(client, ctx) -> None:
    before = _revision(ctx)
    response = client.post("/admin/models", headers=HEADERS, json=NEW_MODEL)
    assert response.status_code == 201, response.text
    assert response.headers["ETag"] == '"1"'
    assert response.json()["uses"] == "env"
    assert _revision(ctx) == before + 1
    [row] = _audit(ctx, "model.create")
    assert row.actor_login == ACTOR and row.via_subject == "admin-console"
    assert row.config_revision == before + 1
    assert row.after["key"] == "acme-small"
    public = client.get("/models").json()
    assert "acme-small" in [m["key"] for m in public]


def test_a_duplicate_or_archived_key_is_refused(client) -> None:
    assert client.post("/admin/models", headers=HEADERS, json=NEW_MODEL).status_code == 201
    dup = client.post("/admin/models", headers=HEADERS, json=NEW_MODEL)
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "conflict"
    assert client.delete("/admin/models/acme-small", headers=if_match(1)).status_code == 204
    reused = client.post("/admin/models", headers=HEADERS, json=NEW_MODEL)
    assert reused.status_code == 409
    assert "never be reused" in reused.json()["detail"]["message"]
    assert "acme-small" not in [m["key"] for m in client.get("/models").json()]
    archived = client.get("/admin/models?include_archived=true", headers=HEADERS).json()
    assert any(m["key"] == "acme-small" and m["archived_at"] for m in archived)


def test_put_replaces_and_if_match_conflicts(client) -> None:
    client.post("/admin/models", headers=HEADERS, json=NEW_MODEL)
    edited = {**NEW_MODEL, "display_name": "Acme Small v2"}
    ok = client.put("/admin/models/acme-small", headers=if_match(1), json=edited)
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = client.put("/admin/models/acme-small", headers=if_match(1), json=edited)
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "version_conflict" and detail["current"]["version"] == 2
    renamed = client.put(
        "/admin/models/acme-small", headers=if_match(2), json={**edited, "key": "x"}
    )
    assert renamed.status_code == 422


def test_patch_hides_and_disables(client) -> None:
    current = client.get("/admin/models/mock", headers=HEADERS).json()
    r = client.patch(
        "/admin/models/mock", headers=if_match(current["version"]), json={"hidden": True}
    )
    assert r.status_code == 200 and r.json()["hidden"] is True
    assert "mock" not in [m["key"] for m in client.get("/models").json()]
    r = client.patch(
        "/admin/models/mock", headers=if_match(r.json()["version"]), json={"enabled": False}
    )
    assert r.json()["enabled"] is False


def test_an_invalid_registry_is_refused_with_issues(client) -> None:
    bad = {**NEW_MODEL, "base_url": None, "base_url_env": None}
    r = client.post("/admin/models", headers=HEADERS, json=bad)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "validation_failed"
    assert r.json()["detail"]["issues"]


def test_unknown_family_or_credential_is_a_field_issue(client) -> None:
    r = client.post("/admin/models", headers=HEADERS, json={**NEW_MODEL, "family_key": "nope"})
    assert r.status_code == 422 and r.json()["detail"]["issues"][0]["path"] == "family_key"
    r = client.post(
        "/admin/models",
        headers=HEADERS,
        json={**NEW_MODEL, "api_key_env": None, "credential_ref": "nope"},
    )
    assert r.json()["detail"]["issues"][0]["path"] == "credential_ref"


def test_reorder_rewrites_display_order(client) -> None:
    r = client.post("/admin/models/reorder", headers=HEADERS, json={"order": ["luna", "mock"]})
    assert r.status_code == 200
    by_key = {m["key"]: m for m in r.json()}
    assert by_key["luna"]["display_order"] == 10 and by_key["mock"]["display_order"] == 20
    assert (
        client.post("/admin/models/reorder", headers=HEADERS, json={"order": ["nope"]}).status_code
        == 422
    )


def test_family_crud_and_delete_409_while_it_has_members(client) -> None:
    families = {f["key"]: f for f in client.get("/admin/model-families", headers=HEADERS).json()}
    assert "claude-opus" in families and families["claude-opus"]["member_keys"]
    r = client.delete("/admin/model-families/claude-opus", headers=if_match(1))
    assert r.status_code == 409
    created = client.post(
        "/admin/model-families", headers=HEADERS, json={"key": "acme", "display_name": "Acme"}
    )
    assert created.status_code == 201
    assert (
        client.post(
            "/admin/model-families", headers=HEADERS, json={"key": "acme", "display_name": "Acme"}
        ).status_code
        == 409
    )
    renamed = client.put(
        "/admin/model-families/acme", headers=if_match(1), json={"display_name": "ACME"}
    )
    assert renamed.json()["display_name"] == "ACME"
    assert client.delete("/admin/model-families/acme", headers=if_match(2)).status_code == 204


def test_a_family_rename_reaches_the_public_registry(client) -> None:
    family = next(
        f
        for f in client.get("/admin/model-families", headers=HEADERS).json()
        if f["key"] == "claude-opus"
    )
    client.put(
        "/admin/model-families/claude-opus",
        headers=if_match(family["version"]),
        json={"display_name": "Opus!"},
    )
    public = {m["key"]: m for m in client.get("/models").json()}
    member = family["member_keys"][0]
    assert public[member]["family_display_name"] == "Opus!"


def test_yaml_mode_refuses_config_routes(tmp_path) -> None:
    ctx = admin_context(tmp_path, config_source="yaml")
    client = admin_client(ctx)
    r = client.get("/admin/models", headers=HEADERS)
    assert r.status_code == 409 and "IDA_CONFIG_SOURCE" in r.json()["detail"]["message"]


def test_connection_test_is_rate_limited_and_audited(client, ctx, monkeypatch) -> None:
    from ida_api.admin import models as admin_models

    calls = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

        def complete(self, messages, sampling):
            calls.append(sampling.max_tokens)

    monkeypatch.setattr(admin_models, "build_client", lambda entry, api_key=None: FakeClient())
    admin_models._last_test.clear()
    r = client.post("/admin/models/mock/test", headers=HEADERS)
    assert r.status_code == 200 and r.json()["ok"] is True and calls == [1]
    again = client.post("/admin/models/mock/test", headers=HEADERS)
    assert again.status_code == 429 and again.json()["detail"]["code"] == "rate_limited"
    assert len(_audit(ctx, "model.test")) == 1


def test_a_failing_connection_test_scrubs_the_key(client, monkeypatch) -> None:
    from ida_api.admin import models as admin_models

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-SCRUB-ME-000000000")

    def boom(entry, api_key=None):
        raise RuntimeError(f"401 for key {api_key}")

    monkeypatch.setattr(admin_models, "build_client", boom)
    admin_models._last_test.clear()
    key = next(
        m["key"]
        for m in client.get("/admin/models", headers=HEADERS).json()
        if m["api_key_env"] == "ANTHROPIC_API_KEY"
    )
    r = client.post(f"/admin/models/{key}/test", headers=HEADERS)
    assert r.json()["ok"] is False
    assert "sk-SCRUB-ME" not in r.text and "***" in r.json()["error"]
