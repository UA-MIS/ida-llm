"""``curriculum/units.yaml`` -- the unit taxonomy that moved out of TypeScript.

Pins three things (admin-console design 4.5):

1. THE MOVE LOST NOTHING.  ``units.yaml`` equals, byte for byte as parsed data,
   the frozen snapshot of the old ``TAXONOMY`` in ``frontend/src/lib/units.ts``
   (``frontend/tests/fixtures/units-taxonomy.snapshot.json``), and
   ``units.dev.yaml`` equals the real+demo merge the dev site used to compute in
   the browser.
2. THE TWO INVARIANTS still hold -- they moved here from ``units.test.ts``: a
   family sits in at most one unit, and a unit's families are a subset of its
   class's ``task_families`` in ``majors.yaml``.
3. A VIOLATION READS AS A SENTENCE, with a path a form can pin it to.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ida_core.majors import load_majors
from ida_core.units import Unit, load_units, parse_units_document, units_document
from ida_core.validation import ValidationError
from ida_core.validation_suite import validate_units

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "frontend" / "tests" / "fixtures"


def _as_snapshot(path: Path) -> dict:
    return {course: [u.as_document() for u in units] for course, units in load_units(path).items()}


def test_units_yaml_equals_the_frozen_typescript_taxonomy() -> None:
    snapshot = json.loads((FIXTURES / "units-taxonomy.snapshot.json").read_text())
    assert _as_snapshot(REPO / "curriculum" / "units.yaml") == snapshot


def test_units_dev_yaml_equals_the_frozen_dev_merge() -> None:
    snapshot = json.loads((FIXTURES / "units-taxonomy-demo.snapshot.json").read_text())
    loaded = _as_snapshot(REPO / "curriculum" / "units.dev.yaml")
    assert loaded == snapshot
    # Order is part of the contract: real classes first, as the merge produced.
    assert list(loaded) == list(snapshot)


@pytest.mark.parametrize(
    ("units_file", "majors_file"),
    [("units.yaml", "majors.yaml"), ("units.dev.yaml", "majors.dev.yaml")],
)
def test_the_two_invariants_hold_against_the_majors_taxonomy(units_file, majors_file) -> None:
    units = load_units(REPO / "curriculum" / units_file)
    majors = load_majors(REPO / "curriculum" / majors_file)
    assert validate_units(units, majors) == []


def test_mis200_keeps_its_five_units_in_course_order() -> None:
    units = load_units(REPO / "curriculum" / "units.yaml")["MIS 200"]
    assert [u.n for u in units] == [1, 2, 3, 4, 5]
    assert units[2].families == ["mis200-spreadsheet-formulas"]


def _unit(key: str, n: int, families: list[str]) -> Unit:
    return Unit(key=key, n=n, title=key.title(), families=families)


def test_a_family_in_two_units_is_a_readable_issue() -> None:
    majors = load_majors(REPO / "curriculum" / "majors.yaml")
    units = {
        "MIS 200": [
            _unit("a", 1, ["mis200-is-concepts"]),
            _unit("b", 2, ["mis200-is-concepts"]),
        ]
    }
    issues = validate_units(units, majors)
    assert len(issues) == 1
    assert issues[0].path == "units.MIS 200[1].families"
    assert "at most one unit" in issues[0].message


def test_a_family_the_class_does_not_own_is_a_readable_issue() -> None:
    majors = load_majors(REPO / "curriculum" / "majors.yaml")
    units = {"MIS 200": [_unit("a", 1, ["om300-exam1-ops-forecasting"])]}
    [issue] = validate_units(units, majors)
    assert "not one of MIS 200's task_families" in issue.message


def test_duplicate_keys_numbers_and_gaps_are_issues() -> None:
    units = {"MIS 200": [_unit("a", 1, []), _unit("a", 3, [])]}
    messages = [i.message for i in validate_units(units, None)]
    assert any("duplicate unit key" in m for m in messages)
    assert any("numbered 1..k" in m for m in messages)


def test_an_unknown_class_is_an_issue() -> None:
    majors = load_majors(REPO / "curriculum" / "majors.yaml")
    [issue] = validate_units({"XX 999": [_unit("a", 1, [])]}, majors)
    assert "not in the majors taxonomy" in issue.message


def test_a_malformed_document_lists_every_problem() -> None:
    with pytest.raises(ValidationError) as excinfo:
        parse_units_document({"version": 2, "classes": {"MIS 200": [{"key": "a"}], "X": 3}})
    errors = excinfo.value.errors
    assert any(e.startswith("version") for e in errors)
    assert any("classes.MIS 200[0]" in e for e in errors)
    assert any("classes.X" in e for e in errors)


def test_an_absent_file_is_no_units(tmp_path) -> None:
    assert load_units(tmp_path / "nope.yaml") == {}


def test_round_trip_through_the_document_form() -> None:
    units = load_units(REPO / "curriculum" / "units.yaml")
    assert parse_units_document(units_document(units)) == units
