"""``/admin/audit`` and ``/admin/export`` (design 5.2, 5.5)."""

from __future__ import annotations

import io
import zipfile

import pytest
import yaml
from _admin_helpers import ACTOR, HEADERS, admin_client, admin_context, if_match

from ida_core.configdb.tables import TaskFamilyRow
from ida_core.db import session_scope


@pytest.fixture
def ctx(tmp_path):
    return admin_context(tmp_path)


@pytest.fixture
def client(ctx):
    return admin_client(ctx)


def test_the_seed_and_every_write_are_listed_newest_first(client) -> None:
    client.patch("/admin/models/mock", headers=if_match(1), json={"hidden": True})
    entries = client.get("/admin/audit", headers=HEADERS).json()["entries"]
    assert entries[0]["action"] == "model.update" and entries[0]["actor_login"] == ACTOR
    assert entries[0]["request_id"]
    assert entries[-1]["action"] == "config.seed"
    only = client.get("/admin/audit?entity_type=model&entity_id=mock", headers=HEADERS).json()
    assert [e["action"] for e in only["entries"]] == ["model.update"]


def test_cursor_pages_through(client) -> None:
    for version in range(1, 4):
        client.patch(
            "/admin/models/mock", headers=if_match(version), json={"enabled": version % 2 == 0}
        )
    first = client.get("/admin/audit?limit=2", headers=HEADERS).json()
    second = client.get(
        f"/admin/audit?limit=2&cursor={first['next_cursor']}", headers=HEADERS
    ).json()
    assert len(first["entries"]) == 2 and len(second["entries"]) == 2
    assert first["entries"][-1]["id"] > second["entries"][0]["id"]
    assert client.get("/admin/audit?cursor=abc", headers=HEADERS).status_code == 422


def test_auth_events_including_denied_are_recorded(client) -> None:
    r = client.post(
        "/admin/audit/events",
        headers={**HEADERS, "X-IDA-Actor": "outsider"},
        json={"action": "auth.denied", "login": "outsider", "groups_ok": False},
    )
    assert r.status_code == 204
    [entry] = client.get("/admin/audit?action=auth.denied", headers=HEADERS).json()["entries"]
    assert entry["entity_id"] == "outsider" and entry["after"]["groups_ok"] is False
    assert entry["config_revision"] is None


def test_there_is_no_way_to_change_the_log(client) -> None:
    paths = client.app.openapi()["paths"]
    assert set(paths["/admin/audit"]) == {"get"}
    assert set(paths["/admin/audit/events"]) == {"post"}


def test_export_zips_the_live_config_and_is_audited(client, ctx) -> None:
    r = client.get("/admin/export", headers=HEADERS)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(archive.namelist())
    assert {
        "models.yaml",
        "curriculum/slo.yaml",
        "curriculum/majors.yaml",
        "curriculum/units.yaml",
    } <= names
    assert "tasks/demo/arithmetic-quiz-check.yaml" in names
    models = yaml.safe_load(archive.read("models.yaml"))
    assert models["models"][0]["key"] == "mock"
    [entry] = client.get("/admin/audit?action=config.export", headers=HEADERS).json()["entries"]
    assert entry["after"]["include_private"] is False


def test_export_leaves_private_families_out_unless_asked(client, ctx) -> None:
    with session_scope(ctx.session_factory) as s:
        s.get(TaskFamilyRow, "demo").provenance = "private"
    names = set(
        zipfile.ZipFile(io.BytesIO(client.get("/admin/export", headers=HEADERS).content)).namelist()
    )
    assert not any(n.startswith("tasks/demo/") for n in names)
    with_private = client.get("/admin/export?include_private=true", headers=HEADERS)
    names = set(zipfile.ZipFile(io.BytesIO(with_private.content)).namelist())
    assert any(n.startswith("tasks/demo/") for n in names)
    entries = client.get("/admin/audit?action=config.export", headers=HEADERS).json()["entries"]
    assert entries[0]["after"]["include_private"] is True
    assert entries[1]["after"]["private_families_excluded"] == ["demo"]
