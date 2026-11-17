"""PR B6: private-material hardening (design 4.6, risk R10).

``GET /tasks/{id}/meta`` serves what the public run page needs with NO prompt
and NO target, anonymously, always.  ``IDA_TASKS_SPEC_GATED`` then puts the
full spec and the transcript route behind ``author`` -- and only once it is on
may a family be marked ``private``."""

from __future__ import annotations

from _admin_helpers import HEADERS, admin_client, admin_context
from fastapi.testclient import TestClient

from ida_api.app import create_app
from ida_api.deps import AppContext

DEMO = "demo/arithmetic-quiz-check"
ADMIN = {"Authorization": HEADERS["Authorization"]}


def test_meta_has_no_prompt_and_no_target(client: TestClient) -> None:
    r = client.get(f"/tasks/{DEMO}/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == DEMO and body["sample_count"] == len(body["samples"])
    assert set(body["samples"][0]) == {"id", "metadata"}
    for forbidden in ("A quiz item reads", "system_prompt", '"target"', '"input"', "rubric"):
        assert forbidden not in r.text
    assert client.get("/tasks/nope/x/meta").status_code == 404


def test_ungated_by_default_nothing_changes(client: TestClient) -> None:
    """Merging this changes nothing until an environment opts in."""
    assert client.get(f"/tasks/{DEMO}").status_code == 200


def test_gated_full_spec_and_transcript_need_author(context: AppContext) -> None:
    context.settings.tasks_spec_gated = True
    client = TestClient(create_app(context))
    assert client.get(f"/tasks/{DEMO}").status_code == 403
    assert client.get("/runs/run_x/results/s1/transcript").status_code == 403
    assert client.get(f"/tasks/{DEMO}/meta").status_code == 200
    assert client.get("/tasks").status_code == 200  # the summary list stays public


def test_gated_admin_principal_still_reads_everything(tmp_path) -> None:
    ctx = admin_context(tmp_path, tasks_spec_gated=True)
    client = admin_client(ctx)
    assert client.get(f"/tasks/{DEMO}", headers=ADMIN).status_code == 200
    assert client.get("/admin/system", headers=HEADERS).json()["tasks_spec_gated"] is True


def test_private_families_are_allowed_only_once_gated(tmp_path) -> None:
    body = {"key": "secret-exam", "title": "Secret", "provenance": "private"}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ungated = admin_client(admin_context(tmp_path / "a"))
    assert ungated.post("/admin/task-families", headers=HEADERS, json=body).status_code == 422
    gated = admin_client(admin_context(tmp_path / "b", tasks_spec_gated=True))
    assert gated.post("/admin/task-families", headers=HEADERS, json=body).status_code == 201
