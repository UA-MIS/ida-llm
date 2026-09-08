"""The majors taxonomy, and the cross-file rules that keep the drill-down honest.

The tests that matter here are the NEGATIVE ones and the ones about
``task_families``.  Loading a well-formed file is easy to get right; what this
module exists to guarantee is that the three failures nothing else would notice
are REJECTED:

* a class neither file can name -- it would render as a nameless column;
* a coverage course no major claims -- ``MIS 200`` is the only class in the
  product with a scored benchmark behind it, and an edit that dropped it from
  every class list would empty the demonstration path silently;
* a ``task_families`` entry naming a family the catalogue does not have -- the
  class then matches no result, reads "not measured yet" forever, and looks
  exactly like a class nobody has got round to running.

And one about the shape of the data itself: ``task_families`` is what makes a
class's score a claim about THAT CLASS.  Results are filed by outcome, so
without it, running the three MIS 200 exam families would light up every course
the map marks against SLO1, SLO2 or SLO9 with a score from a class none of them
is.  :func:`test_only_one_class_claims_any_task_family_today` pins the fact that
exactly one class does, so the day a second one is added it is a deliberate edit
rather than a side effect.
"""

from __future__ import annotations

import pytest
import yaml

from ida_core.config import repo_root
from ida_core.curriculum import CurriculumMap, default_curriculum_path, load_curriculum
from ida_core.majors import (
    CLASS_SOURCE_LABELS,
    MajorClass,
    Majors,
    check_against_curriculum,
    check_task_families,
    default_majors_path,
    load_majors,
    title_disagreements,
)
from ida_core.validation import ValidationError


@pytest.fixture(scope="module")
def curriculum() -> CurriculumMap:
    return load_curriculum(default_curriculum_path(repo_root()))


@pytest.fixture(scope="module")
def majors() -> Majors:
    return load_majors(default_majors_path(repo_root()))


def _document(**overrides) -> dict:
    """A minimal valid taxonomy, so a negative test changes exactly one thing."""
    document = {
        "version": 1,
        "institution": "The University of Alabama",
        "college": "Culverhouse College of Business",
        "source": "https://catalog.ua.edu/undergraduate/business/",
        "retrieved": "2026-09-08",
        "majors": [
            {
                "id": "management-information-systems",
                "name": "Management Information Systems",
                "department": "Information Systems, Statistics and Management Science",
                "class_source": "catalog",
                "classes": [{"course": "MIS 200", "title": "Fundamentals of MIS"}],
            }
        ],
    }
    document.update(overrides)
    return document


def _load(tmp_path, document) -> Majors:
    path = tmp_path / "majors.yaml"
    path.write_text(yaml.safe_dump(document))
    return load_majors(path)


# ---------------------------------------------------------------------------
# The real file
# ---------------------------------------------------------------------------


def test_the_repository_taxonomy_loads(majors: Majors) -> None:
    assert majors.majors
    assert len(majors.major_ids()) == len(set(majors.major_ids()))


def test_the_repository_taxonomy_agrees_with_the_curriculum_map(
    majors: Majors, curriculum: CurriculumMap
) -> None:
    # The gate `tools/validate_tasks.py` runs, asserted here too so a broken
    # taxonomy fails the unit suite and not only the lint job.
    assert check_against_curriculum(majors, curriculum) == []


def test_every_coverage_course_is_reachable_from_a_major_or_excused(
    majors: Majors, curriculum: CurriculumMap
) -> None:
    claimed = majors.claimed_courses()
    excused = {row.course for row in majors.unassigned_core}
    for row in curriculum.coverage:
        assert row.course in claimed or row.course in excused, row.course


def test_mis_200_is_owned_by_the_mis_major(majors: Majors) -> None:
    # The one populated leaf in the product. If this moves, the demonstration
    # path moves with it, and nothing else in the suite would say so.
    owner = majors.major_for_course("MIS 200")
    assert owner is not None
    assert owner.id == "management-information-systems"


def test_only_one_class_claims_any_task_family_today(majors: Majors) -> None:
    claiming = [
        (major.id, entry.course)
        for major in majors.majors
        for entry in major.classes
        if entry.task_families
    ]
    assert claiming == [("management-information-systems", "MIS 200")], (
        "a second class now claims task families. That is a real product change -- "
        "another class can show a score -- so update this test deliberately rather "
        "than deleting it."
    )


def test_the_catalog_title_supersedes_the_maps_abbreviation(
    majors: Majors, curriculum: CurriculumMap
) -> None:
    # Reported, never gated: the catalog is the authority on course titles and
    # the curriculum map abbreviates them. Gating would force a transcription of
    # one published document to be edited to agree with another.
    diffs = {course: (a, b) for course, a, b in title_disagreements(majors, curriculum)}
    assert diffs["MIS 200"] == (
        "Fundamentals of Management Information Systems",
        "Fundamentals of MIS",
    )
    entry = next(
        e for e in majors.get("management-information-systems").classes if e.course == "MIS 200"
    )
    assert majors.resolve_title(entry, curriculum) == (
        "Fundamentals of Management Information Systems"
    )


def test_a_class_with_no_title_inherits_the_maps(majors: Majors, curriculum: CurriculumMap) -> None:
    entry = next(e for e in majors.get("accounting").classes if e.course == "AC 210")
    assert entry.title is None
    assert majors.resolve_title(entry, curriculum) == "Intro to Accounting"


def test_every_class_source_has_a_reader_facing_label(majors: Majors) -> None:
    for major in majors.majors:
        assert major.class_source_label == CLASS_SOURCE_LABELS[major.class_source]


# ---------------------------------------------------------------------------
# The negatives
# ---------------------------------------------------------------------------


def test_a_missing_file_is_a_validation_error(tmp_path) -> None:
    with pytest.raises(ValidationError):
        load_majors(tmp_path / "nope.yaml")


def test_a_duplicate_major_id_is_rejected(tmp_path) -> None:
    document = _document()
    document["majors"] = document["majors"] * 2
    with pytest.raises(ValidationError, match="duplicate major ids"):
        _load(tmp_path, document)


def test_a_course_claimed_by_two_majors_is_rejected(tmp_path) -> None:
    # It double-counts in the one number the top-level grid exists to show:
    # how much of a major has been measured.
    document = _document()
    document["majors"].append(
        {
            "id": "operations-management",
            "name": "Operations Management",
            "department": "Information Systems, Statistics and Management Science",
            "class_source": "core-only",
            "classes": [{"course": "MIS 200", "title": "Fundamentals of MIS"}],
        }
    )
    with pytest.raises(ValidationError, match="only one major"):
        _load(tmp_path, document)


def test_the_same_course_twice_in_one_major_is_rejected(tmp_path) -> None:
    document = _document()
    document["majors"][0]["classes"] *= 2
    with pytest.raises(ValidationError, match="same course twice"):
        _load(tmp_path, document)


def test_class_source_none_must_agree_with_an_empty_list(tmp_path) -> None:
    # `class_source` is what the UI renders to explain a short list, so a value
    # that disagrees with the list beside it is a caption for a different page.
    document = _document()
    document["majors"][0]["class_source"] = "none"
    with pytest.raises(ValidationError, match="class_source: none"):
        _load(tmp_path, document)

    document = _document()
    document["majors"][0]["classes"] = []
    with pytest.raises(ValidationError, match="use 'none' to say so"):
        _load(tmp_path, document)


def test_an_unknown_class_source_is_rejected(tmp_path) -> None:
    document = _document()
    document["majors"][0]["class_source"] = "somewhat"
    with pytest.raises(ValidationError):
        _load(tmp_path, document)


def test_an_unknown_top_level_key_is_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError):
        _load(tmp_path, _document(colleges="plural"))


def test_a_malformed_course_code_is_rejected(tmp_path) -> None:
    # The code is the join key into the coverage grid. A code the grid could
    # never match makes the class silently unmeasurable.
    document = _document()
    document["majors"][0]["classes"] = [{"course": "mis200", "title": "x"}]
    with pytest.raises(ValidationError):
        _load(tmp_path, document)


def test_a_major_id_that_is_not_a_url_segment_is_rejected(tmp_path) -> None:
    document = _document()
    document["majors"][0]["id"] = "Management Information Systems"
    with pytest.raises(ValidationError):
        _load(tmp_path, document)


# ---------------------------------------------------------------------------
# The cross-file rules
# ---------------------------------------------------------------------------


def test_a_class_neither_file_can_name_is_reported(tmp_path, curriculum: CurriculumMap) -> None:
    document = _document()
    # No title, and no row in the coverage grid for this code.
    document["majors"][0]["classes"] = [{"course": "ZZ 999"}]
    taxonomy = _load(tmp_path, document)
    problems = check_against_curriculum(taxonomy, curriculum)
    assert any("no title and no row" in p for p in problems)


def test_an_orphaned_coverage_course_is_reported(tmp_path, curriculum: CurriculumMap) -> None:
    # The whole taxonomy claims one course; every other course in the map is
    # unreachable from the drill-down, and each one is named.
    taxonomy = _load(tmp_path, _document())
    problems = check_against_curriculum(taxonomy, curriculum)
    assert any("AC 210" in p and "unreachable" in p for p in problems)


def test_unassigned_core_must_name_a_course_the_map_actually_has(
    tmp_path, curriculum: CurriculumMap
) -> None:
    document = _document()
    document["unassigned_core"] = [{"course": "ZZ 999", "reason": "why not"}]
    problems = check_against_curriculum(_load(tmp_path, document), curriculum)
    assert any("stale" in p for p in problems)


def test_a_course_cannot_be_both_claimed_and_excused(tmp_path, curriculum: CurriculumMap) -> None:
    document = _document()
    document["unassigned_core"] = [{"course": "MIS 200", "reason": "why not"}]
    problems = check_against_curriculum(_load(tmp_path, document), curriculum)
    assert any("cannot be both" in p for p in problems)


def test_unassigned_core_requires_a_reason(tmp_path) -> None:
    document = _document()
    document["unassigned_core"] = [{"course": "LGS 200"}]
    with pytest.raises(ValidationError):
        _load(tmp_path, document)


def test_a_task_family_the_catalogue_does_not_have_is_reported(tmp_path) -> None:
    # The silent one: a misspelled family makes the class read "not measured
    # yet" forever, indistinguishable from a class nobody has run.
    document = _document()
    document["majors"][0]["classes"] = [
        {"course": "MIS 200", "title": "x", "task_families": ["mis200-typo"]}
    ]
    taxonomy = _load(tmp_path, document)
    assert check_task_families(taxonomy, {"mis200-is-concepts"}) != []
    assert check_task_families(taxonomy, {"mis200-typo"}) == []


def test_the_repository_task_families_all_exist(majors: Majors) -> None:
    known = {p.name for p in (repo_root() / "tasks").iterdir() if p.is_dir()}
    assert check_task_families(majors, known) == []


def test_task_families_default_to_empty(tmp_path) -> None:
    # The default has to be "nothing can be attributed to this class". Anything
    # else and a class inherits a sibling's number by omission.
    assert MajorClass(course="MIS 200").task_families == []
    taxonomy = _load(tmp_path, _document())
    assert taxonomy.get("management-information-systems").classes[0].task_families == []
