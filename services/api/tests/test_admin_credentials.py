"""``/admin/credentials`` (AD-10, design 10.1).

THE TEST THAT MATTERS: a planted key never appears in any response body, any
log record, any audit row, or any stored column -- and yet a model that names
the credential resolves to it in the worker."""

from __future__ import annotations

import logging

import pytest
from _admin_helpers import HEADERS, admin_client, admin_context, if_match
from sqlalchemy import select

from ida_core.configdb.crypto import DbCredentialResolver, parse_kek
from ida_core.configdb.tables import AuditLogRow, ProviderCredentialRow
from ida_core.db import session_scope
from ida_core.registry import resolve_api_key

PLANTED = "sk-PLANTED-0123456789abcdef-not-real"
ROTATED = "sk-PLANTED-ROTATED-fedcba9876543210"


@pytest.fixture
def ctx(tmp_path):
    return admin_context(tmp_path)


@pytest.fixture
def client(ctx):
    return admin_client(ctx)


def _everything_stored(ctx) -> str:
    """Every audit row and every credential column, as one string to grep."""
    with session_scope(ctx.session_factory) as s:
        audit = [(r.action, r.before, r.after, r.entity_id) for r in s.scalars(select(AuditLogRow))]
        creds = [
            (r.name, r.provider, bytes(r.ciphertext), bytes(r.nonce), r.kek_id)
            for r in s.scalars(select(ProviderCredentialRow))
        ]
    return repr(audit) + repr(creds)


def test_the_key_never_leaks_anywhere_and_still_resolves(client, ctx, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    bodies = []
    r = client.post(
        "/admin/credentials",
        headers=HEADERS,
        json={"name": "acme-prod", "provider": "acme", "api_key": PLANTED},
    )
    assert r.status_code == 201, r.text
    bodies.append(r.text)
    assert r.json()["kek_id"] == "k1" and "api_key" not in r.json()

    model = {
        "key": "acme-small",
        "display_name": "Acme Small",
        "base_url": "https://api.acme.example/v1",
        "credential_ref": "acme-prod",
        "serving": {"model_id": "acme-small-1", "serving_stack": "openai_api"},
    }
    r = client.post("/admin/models", headers=HEADERS, json=model)
    assert r.status_code == 201, r.text
    assert r.json()["uses"] == "credential" and r.json()["key_present"] is True
    bodies.append(r.text)
    bodies.append(client.get("/admin/credentials", headers=HEADERS).text)
    bodies.append(client.get("/admin/models", headers=HEADERS).text)
    bodies.append(client.get("/models?include_disabled=true").text)

    r = client.put(
        "/admin/credentials/acme-prod/secret", headers=if_match(1), json={"api_key": ROTATED}
    )
    assert r.status_code == 200 and r.json()["rotated_at"]
    bodies.append(r.text)

    stored = _everything_stored(ctx)
    logs = "\n".join(rec.getMessage() for rec in caplog.records)
    for secret in (PLANTED, ROTATED):
        for body in bodies:
            assert secret not in body
        assert secret not in logs
        assert secret not in stored
        assert secret.encode() not in stored.encode()

    # ...and the worker path decrypts it.
    entry = ctx.registry.get("acme-small")
    resolver = DbCredentialResolver(ctx.session_factory, parse_kek(ctx.settings.credentials_kek))
    assert resolve_api_key(entry, credentials=resolver) == ROTATED


def test_audit_rows_are_metadata_only(client, ctx) -> None:
    client.post(
        "/admin/credentials",
        headers=HEADERS,
        json={"name": "x-1", "provider": "x", "api_key": PLANTED},
    )
    with session_scope(ctx.session_factory) as s:
        row = s.scalar(select(AuditLogRow).where(AuditLogRow.action == "credential.create"))
    assert row.after == {"name": "x-1", "provider": "x", "kek_id": "k1"}


def test_validation_errors_do_not_echo_the_key(client) -> None:
    r = client.post(
        "/admin/credentials",
        headers=HEADERS,
        json={"name": "BAD NAME", "provider": "x", "api_key": PLANTED},
    )
    assert r.status_code == 422
    assert PLANTED not in r.text


def test_no_kek_is_503_kek_missing(tmp_path) -> None:
    client = admin_client(admin_context(tmp_path, credentials_kek=""))
    r = client.post(
        "/admin/credentials",
        headers=HEADERS,
        json={"name": "a", "provider": "b", "api_key": PLANTED},
    )
    assert r.status_code == 503 and r.json()["detail"]["code"] == "kek_missing"


def test_a_malformed_kek_refuses_to_boot(tmp_path) -> None:
    from ida_core.configdb.crypto import KekConfigError

    with pytest.raises(KekConfigError):
        admin_client(admin_context(tmp_path, credentials_kek="k1:tooshort"))


def test_delete_409_while_in_use_then_204(client) -> None:
    client.post(
        "/admin/credentials",
        headers=HEADERS,
        json={"name": "c-1", "provider": "x", "api_key": PLANTED},
    )
    client.post(
        "/admin/models",
        headers=HEADERS,
        json={
            "key": "uses-c1",
            "display_name": "U",
            "base_url": "https://x.example/v1",
            "credential_ref": "c-1",
            "serving": {"model_id": "u", "serving_stack": "openai_api"},
        },
    )
    r = client.delete("/admin/credentials/c-1", headers=if_match(1))
    assert r.status_code == 409 and "uses-c1" in r.json()["detail"]["message"]
    assert client.delete("/admin/models/uses-c1", headers=if_match(1)).status_code == 204
    assert client.delete("/admin/credentials/c-1", headers=if_match(1)).status_code == 204
    assert client.get("/admin/credentials", headers=HEADERS).json() == []


def test_duplicate_name_is_409(client) -> None:
    body = {"name": "dup", "provider": "x", "api_key": PLANTED}
    assert client.post("/admin/credentials", headers=HEADERS, json=body).status_code == 201
    assert client.post("/admin/credentials", headers=HEADERS, json=body).status_code == 409


def test_api_key_env_and_credential_ref_together_are_refused(client) -> None:
    r = client.post(
        "/admin/models",
        headers=HEADERS,
        json={
            "key": "both",
            "display_name": "B",
            "base_url": "https://x.example/v1",
            "api_key_env": "X",
            "credential_ref": "c",
            "serving": {"model_id": "b", "serving_stack": "openai_api"},
        },
    )
    assert r.status_code == 422
