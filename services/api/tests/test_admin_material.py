"""``/admin/task-families``, ``/admin/tasks`` and uploads (design 5.2, 5.4, 10.1)."""

from __future__ import annotations

import copy

import pytest
import yaml
from _admin_helpers import HEADERS, admin_client, admin_context, if_match
from sqlalchemy import select

from ida_core.config import repo_root
from ida_core.configdb.tables import AuditLogRow, TaskRevisionRow, TaskRow
from ida_core.contracts import content_sha_of
from ida_core.db import session_scope

DEMO = "demo/arithmetic-quiz-check"


@pytest.fixture
def ctx(tmp_path):
    return admin_context(tmp_path)


@pytest.fixture
def client(ctx):
    return admin_client(ctx)


def _demo_doc() -> dict:
    return yaml.safe_load(
        (repo_root() / "tasks" / "demo" / "arithmetic-quiz-check.yaml").read_text()
    )


def _new_doc(task_id: str = "demo/new-quiz") -> dict:
    doc = _demo_doc()
    doc["id"] = task_id
    doc["title"] = "A new quiz"
    return doc


def _family(client, key="acme-quiz") -> None:
    r = client.post(
        "/admin/task-families",
        headers=HEADERS,
        json={"key": key, "title": "Acme quiz", "description": "Shown publicly"},
    )
    assert r.status_code == 201, r.text


def _revisions(ctx, task_id: str) -> list[TaskRevisionRow]:
    with session_scope(ctx.session_factory) as s:
        return list(s.scalars(select(TaskRevisionRow).where(TaskRevisionRow.task_id == task_id)))


def test_families_list_counts_classes_and_units(client) -> None:
    families = {f["key"]: f for f in client.get("/admin/task-families", headers=HEADERS).json()}
    mis = families["mis200-is-concepts"]
    assert mis["task_count"] >= 1 and mis["sample_count"] >= 1
    assert mis["classes"] == ["MIS 200"]
    assert mis["unit"] == {"course": "MIS 200", "key": "information-systems-business-models"}


def test_private_provenance_is_refused_until_the_spec_is_gated(client) -> None:
    r = client.post(
        "/admin/task-families",
        headers=HEADERS,
        json={"key": "secret-exam", "title": "S", "provenance": "private"},
    )
    assert r.status_code == 422 and r.json()["detail"]["issues"][0]["path"] == "provenance"
    assert client.get("/admin/system", headers=HEADERS).json()["tasks_spec_gated"] is False


def test_get_task_is_unredacted(client) -> None:
    body = client.get(f"/admin/tasks/{DEMO}", headers=HEADERS).json()
    assert body["document"]["samples"][0]["target"] == "42"
    assert body["source"] == "yaml_seed" and body["issues"] == []


def test_create_task_in_a_new_family_and_serve_it_publicly(client, ctx) -> None:
    _family(client)
    doc = _new_doc("acme-quiz/q1")
    r = client.post("/admin/tasks", headers=HEADERS, json={"document": doc})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content_sha"] == content_sha_of(doc) and body["source"] == "form"
    assert len(_revisions(ctx, "acme-quiz/q1")) == 1
    public = client.get("/tasks/acme-quiz/q1").json()
    assert public["targets_redacted"] is True
    assert "acme-quiz/q1" in [t["id"] for t in client.get("/tasks").json()]


def test_an_unknown_family_is_refused(client) -> None:
    r = client.post("/admin/tasks", headers=HEADERS, json={"document": _new_doc("nope/q1")})
    assert r.status_code == 422
    assert any(i["path"] == "id" for i in r.json()["detail"]["issues"])


def test_an_slo_typo_is_422_with_a_path(client) -> None:
    doc = yaml.safe_load(
        next((repo_root() / "tasks" / "mis200-is-concepts").glob("*.yaml")).read_text()
    )
    doc["tags"] = ["slo:SL09" if t.startswith("slo:") else t for t in doc["tags"]]
    current = client.get(f"/admin/tasks/{doc['id']}", headers=HEADERS).json()
    r = client.put(
        f"/admin/tasks/{doc['id']}", headers=if_match(current["version"]), json={"document": doc}
    )
    assert r.status_code == 422
    assert any(i["path"] == "tags" for i in r.json()["detail"]["issues"])


def test_the_metadata_leak_rule_is_422(client) -> None:
    doc = _demo_doc()
    doc["samples"][0]["metadata"]["hint"] = "the answer is 42"
    r = client.put(f"/admin/tasks/{DEMO}", headers=if_match(1), json={"document": doc})
    assert r.status_code == 422


def test_update_writes_a_revision_and_audits_summary_only(client, ctx) -> None:
    doc = _demo_doc()
    doc["title"] = "Edited arithmetic"
    r = client.put(f"/admin/tasks/{DEMO}", headers=if_match(1), json={"document": doc})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert len(_revisions(ctx, DEMO)) == 2
    with session_scope(ctx.session_factory) as s:
        audit = s.scalar(select(AuditLogRow).where(AuditLogRow.action == "task.update"))
    assert set(audit.after) == {"content_sha", "sample_count", "task_revision_id"}
    assert client.get(f"/tasks/{DEMO}").json()["title"] == "Edited arithmetic"
    renamed = client.put(f"/admin/tasks/{DEMO}", headers=if_match(2), json={"document": _new_doc()})
    assert renamed.status_code == 422


def test_samples_add_edit_delete(client) -> None:
    sample = {"id": "add-big", "input": "What is 100 + 1?", "target": "101"}
    r = client.post(f"/admin/tasks/{DEMO}/samples", headers=if_match(1), json={"sample": sample})
    assert r.status_code == 200, r.text
    assert r.json()["sample_count"] == 5
    dup = client.post(f"/admin/tasks/{DEMO}/samples", headers=if_match(2), json={"sample": sample})
    assert dup.status_code == 409
    r = client.put(
        f"/admin/tasks/{DEMO}/samples/add-big",
        headers=if_match(2),
        json={"sample": {**sample, "target": "102", "input": "What is 100 + 2?"}},
    )
    assert r.status_code == 200 and r.json()["version"] == 3
    r = client.delete(f"/admin/tasks/{DEMO}/samples/add-big", headers=if_match(3))
    assert r.status_code == 200 and r.json()["sample_count"] == 4
    missing = client.delete(f"/admin/tasks/{DEMO}/samples/nope", headers=if_match(4))
    assert missing.status_code == 404


def test_a_verifiable_sample_without_a_target_is_refused(client) -> None:
    r = client.post(
        f"/admin/tasks/{DEMO}/samples",
        headers=if_match(1),
        json={"sample": {"id": "no-target", "input": "What is 1 + 1?"}},
    )
    assert r.status_code == 422


def test_archive_removes_from_catalog_keeps_revisions(client, ctx) -> None:
    assert client.delete(f"/admin/tasks/{DEMO}", headers=if_match(1)).status_code == 204
    assert client.get(f"/tasks/{DEMO}").status_code == 404
    assert _revisions(ctx, DEMO)
    r = client.delete("/admin/task-families/demo", headers=if_match(1))
    assert r.status_code == 409  # still has other live demo tasks


def test_family_claimed_by_a_class_cannot_be_archived(client) -> None:
    r = client.delete("/admin/task-families/mis200-is-concepts", headers=if_match(1))
    assert r.status_code == 409 and "unit" in r.json()["detail"]["message"]


def test_validate_endpoint_dry_runs_documents_and_yaml(client, ctx) -> None:
    ok = client.post("/admin/tasks/validate", headers=HEADERS, json={"document": _demo_doc()})
    assert ok.json()["ok"] is True and ok.json()["sample_count"] == 4
    bad = client.post("/admin/tasks/validate", headers=HEADERS, json={"yaml": "id: [unclosed\n"})
    issue = bad.json()["issues"][0]
    assert bad.json()["ok"] is False and issue["path"].startswith("line ")
    with session_scope(ctx.session_factory) as s:
        assert s.scalar(select(TaskRow).where(TaskRow.id == "demo/new-quiz")) is None


def _upload(client, content: bytes, *, commit=False, mode="create", name="t.yaml"):
    return client.post(
        "/admin/material/upload",
        headers=HEADERS,
        files={"file": (name, content, "application/yaml")},
        data={"commit": str(commit).lower(), "mode": mode},
    )


def _artifact_files(ctx) -> list:
    root = ctx.artifact_store._root / ctx.artifact_store.bucket / "admin-material"
    return list(root.rglob("*.yaml")) if root.exists() else []


def test_upload_preview_writes_nothing_commit_writes_object_and_task(client, ctx) -> None:
    raw = yaml.safe_dump(_new_doc()).encode()
    preview = _upload(client, raw)
    assert preview.status_code == 200 and preview.json()["ok"] is True
    assert preview.json()["committed"] is False
    assert _artifact_files(ctx) == []
    committed = _upload(client, raw, commit=True)
    body = committed.json()
    assert body["committed"] is True and body["task"]["source"] == "upload"
    [stored] = _artifact_files(ctx)
    assert stored.read_bytes() == raw
    with session_scope(ctx.session_factory) as s:
        row = s.get(TaskRow, "demo/new-quiz")
        assert row.upload_object_key.startswith("admin-material/")


def test_upload_replace_reports_a_sample_diff(client) -> None:
    doc = _demo_doc()
    doc["samples"] = copy.deepcopy(doc["samples"][:3])
    doc["samples"][0]["target"] = "42.0"
    doc["samples"].append({"id": "extra", "input": "What is 2 + 2?", "target": "4"})
    r = _upload(client, yaml.safe_dump(doc).encode(), mode="replace")
    assert r.json()["diff"] == {"samples_added": 1, "samples_removed": 1, "samples_changed": 1}
    exists = _upload(client, yaml.safe_dump(doc).encode(), mode="create")
    assert exists.json()["ok"] is False


def test_a_rejected_upload_is_never_persisted(client, ctx) -> None:
    doc = _new_doc()
    del doc["samples"][0]["target"]
    r = _upload(client, yaml.safe_dump(doc).encode(), commit=True)
    assert r.json()["ok"] is False and r.json()["committed"] is False
    assert _artifact_files(ctx) == []


def test_malformed_yaml_reports_line_and_column(client) -> None:
    r = _upload(client, b"version: 1\nid: x\nsamples: [\n  - {\n")
    issue = r.json()["issues"][0]
    assert issue["path"].startswith("line ") and ", col " in issue["path"]


def test_size_and_extension_limits(tmp_path) -> None:
    client = admin_client(admin_context(tmp_path, admin_upload_max_bytes=64))
    big = _upload(client, b"x" * 65)
    assert big.status_code == 422
    wrong = _upload(client, b"a: 1", name="t.json")
    assert wrong.status_code == 422


def test_unsafe_yaml_tags_are_not_constructed(client) -> None:
    r = _upload(client, b"!!python/object/apply:os.system ['echo pwned']\n")
    assert r.json()["ok"] is False
