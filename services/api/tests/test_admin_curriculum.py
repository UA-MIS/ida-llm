"""``/admin/majors``, ``/admin/classes``, ``/admin/units``, ``/admin/curriculum/slo``
(design 5.2, 10.1): the two unit invariants, renumbering, slo editing, and the
"MIS 200 must stay reachable" gate."""

from __future__ import annotations

import pytest
import yaml
from _admin_helpers import HEADERS, admin_client, admin_context, if_match


@pytest.fixture
def ctx(tmp_path):
    return admin_context(tmp_path)


@pytest.fixture
def client(ctx):
    return admin_client(ctx)


def _class(client, course: str) -> dict:
    tree = client.get("/admin/majors", headers=HEADERS).json()
    for major in tree["majors"]:
        for klass in major["classes"]:
            if klass["course"] == course:
                return klass
    return next(c for c in tree["unassigned"] if c["course"] == course)


def _unit_body(**overrides) -> dict:
    return {
        "key": "new-unit",
        "n": 6,
        "title": "New unit",
        "covers": ["x"],
        "blurb": "b",
        "families": [],
        **overrides,
    }


def test_one_call_renders_the_whole_tree(client) -> None:
    tree = client.get("/admin/majors", headers=HEADERS).json()
    assert len(tree["majors"]) == 11 and tree["unassigned"]
    mis200 = _class(client, "MIS 200")
    assert mis200["resolved_title"] == mis200["title"] or mis200["resolved_title"]
    assert [u["n"] for u in mis200["units"]] == [1, 2, 3, 4, 5]
    assert "mis200-is-problem-solving" in mis200["task_families"]


def test_invariant_1_a_family_in_a_second_unit_is_refused(client) -> None:
    r = client.post(
        "/admin/classes/MIS 200/units",
        headers=HEADERS,
        json=_unit_body(families=["mis200-is-concepts"]),
    )
    assert r.status_code == 422
    issue = r.json()["detail"]["issues"][0]
    assert "already in unit 1" in issue["message"] and issue["path"] == "families[0]"


def test_invariant_2_a_family_the_class_does_not_own_is_refused(client) -> None:
    r = client.post(
        "/admin/classes/MIS 200/units",
        headers=HEADERS,
        json=_unit_body(families=["om300-exam1-ops-forecasting"]),
    )
    assert r.status_code == 422
    assert "not one of MIS 200's task families" in r.json()["detail"]["issues"][0]["message"]


def test_removing_a_class_family_a_unit_claims_is_409_naming_the_unit(client) -> None:
    mis200 = _class(client, "MIS 200")
    families = [f for f in mis200["task_families"] if f != "mis200-is-concepts"]
    r = client.put(
        "/admin/classes/MIS 200/task-families",
        headers=if_match(mis200["version"]),
        json={"families": families},
    )
    assert r.status_code == 409
    assert "unit 1" in r.json()["detail"]["message"]


def test_an_unclaimed_family_can_be_assigned_and_shows_publicly(client) -> None:
    r = client.post(
        "/admin/classes/MIS 200/units",
        headers=HEADERS,
        json=_unit_body(families=["mis200-is-problem-solving"], n=2),
    )
    assert r.status_code == 201, r.text
    assert r.json()["n"] == 2
    units = client.get("/curriculum").json()["units"]["MIS 200"]
    assert [u["n"] for u in units] == [1, 2, 3, 4, 5, 6]
    assert units[1]["key"] == "new-unit" and units[1]["families"] == ["mis200-is-problem-solving"]


def test_reorder_and_delete_keep_numbering_gapless(client) -> None:
    units = client.get("/admin/classes/MIS 200/units", headers=HEADERS).json()
    order = [u["id"] for u in reversed(units)]
    r = client.post("/admin/classes/MIS 200/units/reorder", headers=HEADERS, json={"order": order})
    assert r.status_code == 200
    assert [u["n"] for u in r.json()] == [1, 2, 3, 4, 5]
    assert r.json()[0]["key"] == units[-1]["key"]
    partial = client.post(
        "/admin/classes/MIS 200/units/reorder", headers=HEADERS, json={"order": order[:2]}
    )
    assert partial.status_code == 422

    current = client.get("/admin/classes/MIS 200/units", headers=HEADERS).json()
    victim = current[1]
    assert (
        client.delete(
            f"/admin/units/{victim['id']}", headers=if_match(victim["version"])
        ).status_code
        == 204
    )
    after = client.get("/admin/classes/MIS 200/units", headers=HEADERS).json()
    assert [u["n"] for u in after] == [1, 2, 3, 4]


def test_unit_edit_and_family_assignment(client) -> None:
    unit = client.get("/admin/classes/MIS 200/units", headers=HEADERS).json()[0]
    r = client.put(
        f"/admin/units/{unit['id']}",
        headers=if_match(unit["version"]),
        json={
            **{
                k: unit[k]
                for k in ("key", "n", "title", "covers", "blurb", "source", "caveat", "families")
            },
            "title": "Renamed",
        },
    )
    assert r.status_code == 200 and r.json()["title"] == "Renamed"
    stale = client.put(
        f"/admin/units/{unit['id']}/families",
        headers=if_match(unit["version"]),
        json={"families": []},
    )
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "version_conflict"
    r = client.put(
        f"/admin/units/{unit['id']}/families",
        headers=if_match(r.json()["version"]),
        json={"families": []},
    )
    assert r.status_code == 200 and r.json()["families"] == []


def test_mis200_must_stay_reachable(client) -> None:
    mis200 = _class(client, "MIS 200")
    for unit in mis200["units"]:
        client.delete(
            f"/admin/units/{unit['id']}", headers=if_match(_unit_version(client, unit["id"]))
        )
    r = client.delete(
        "/admin/classes/MIS 200", headers=if_match(_class(client, "MIS 200")["version"])
    )
    assert r.status_code == 422
    assert any("MIS 200" in i["message"] for i in r.json()["detail"]["issues"])


def _unit_version(client, unit_id: str) -> int:
    for unit in client.get("/admin/classes/MIS 200/units", headers=HEADERS).json():
        if unit["id"] == unit_id:
            return unit["version"]
    raise AssertionError(unit_id)


def test_major_crud(client) -> None:
    body = {
        "id": "data-science",
        "name": "Data Science",
        "department": "ISM",
        "class_source": "none",
    }
    r = client.post("/admin/majors", headers=HEADERS, json=body)
    assert r.status_code == 201, r.text
    r = client.put("/admin/majors/data-science", headers=if_match(1), json={**body, "name": "DS"})
    assert r.json()["name"] == "DS"
    owner = next(
        m for m in client.get("/admin/majors", headers=HEADERS).json()["majors"] if m["classes"]
    )
    assert (
        client.delete(
            f"/admin/majors/{owner['id']}", headers=if_match(owner["version"])
        ).status_code
        == 409
    )
    assert client.delete("/admin/majors/data-science", headers=if_match(2)).status_code == 204


def test_class_create_then_move(client) -> None:
    majors = client.get("/admin/majors", headers=HEADERS).json()["majors"]
    mis = next(m for m in majors if any(c["course"] == "MIS 200" for c in m["classes"]))
    r = client.post(
        "/admin/classes",
        headers=HEADERS,
        json={"course": "MIS 499", "major_id": mis["id"], "title": "Capstone", "position": 99},
    )
    assert r.status_code == 201, r.text
    both = client.post(
        "/admin/classes",
        headers=HEADERS,
        json={"course": "MIS 498", "major_id": mis["id"], "unassigned_reason": "x"},
    )
    assert both.status_code == 422


def test_slo_round_trip_and_validation(client) -> None:
    current = client.get("/admin/curriculum/slo", headers=HEADERS)
    doc = yaml.safe_load(current.json()["yaml"])
    version = current.json()["version"]
    doc["outcomes"][0]["title"] = doc["outcomes"][0]["title"] + " (edited)"
    r = client.put(
        "/admin/curriculum/slo", headers=if_match(version), json={"yaml": yaml.safe_dump(doc)}
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == version + 1
    served = client.get("/curriculum").json()["outcomes"][0]["title"]
    assert served.endswith("(edited)")

    broken = client.put(
        "/admin/curriculum/slo", headers=if_match(version + 1), json={"yaml": "outcomes: [\n"}
    )
    assert broken.status_code == 422 and broken.json()["detail"]["issues"][0]["path"].startswith(
        "line "
    )
    bad = dict(doc)
    # A coverage course no major claims would be unreachable from the drill-down.
    bad["coverage"] = [*doc["coverage"], {**doc["coverage"][0], "course": "XX 101"}]
    orphan = client.put(
        "/admin/curriculum/slo", headers=if_match(version + 1), json={"yaml": yaml.safe_dump(bad)}
    )
    assert orphan.status_code == 422


def test_reordering_class_families_keeps_unit_claims_intact(client) -> None:
    """Families a unit holds stay put while the class's list is rewritten -- on
    Postgres the unit's composite FK would refuse even a momentary removal."""
    mis200 = _class(client, "MIS 200")
    reordered = list(reversed(mis200["task_families"]))
    r = client.put(
        "/admin/classes/MIS 200/task-families",
        headers=if_match(mis200["version"]),
        json={"families": reordered},
    )
    assert r.status_code == 200, r.text
    assert r.json()["task_families"] == reordered
    assert [u["families"] for u in r.json()["units"]] == [u["families"] for u in mis200["units"]]
    dropped = [f for f in reordered if f != "mis200-is-problem-solving"]
    r = client.put(
        "/admin/classes/MIS 200/task-families",
        headers=if_match(r.json()["version"]),
        json={"families": dropped},
    )
    assert r.status_code == 200 and "mis200-is-problem-solving" not in r.json()["task_families"]
