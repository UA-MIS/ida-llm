"""The college's majors, and the rule that keeps the class taxonomy honest.

``curriculum/majors.yaml`` is the authority for **which classes exist and whose
they are**; ``curriculum/slo.yaml`` is the authority for **which outcomes a
class teaches**.  Two files, two sources, one join key -- the course code.  This
module parses the first, reconciles it against the second, and answers the
question neither file can answer alone: *is this taxonomy consistent with the
curriculum map it is drilled into?*

Why the split, and why it is not over-engineering
-------------------------------------------------
The drill-down used to start at a single programme, because a single programme
is all ``slo.yaml`` describes: it is the published course x outcome grid for the
shared business core.  But nobody is a professor of "the core".  They are a
professor of Management Information Systems, and the flow has to start where
they already stand.  The list of majors, and which classes belong to each, is
simply not in the curriculum map -- it is in the course catalog, a different
document with a different publisher and a different revision date.  Folding it
into ``slo.yaml`` would put two provenances behind one ``source:`` field, which
is the point at which a provenance trail stops being one.

The three cross-file rules
--------------------------
None of these can be seen from ``majors.yaml`` alone, which is why they live
here rather than in the JSON Schema:

1. **A class must be able to name itself.**  A class entry may omit ``title``,
   and most do -- the title then comes from the coverage row for the same course
   code, so the two files cannot disagree about a course they both name.  A
   class with no title and no coverage row would render as a nameless column,
   so it is an error.

2. **A coverage course is claimed exactly once.**  Every course in the map's
   coverage grid belongs to exactly one major, or is listed under
   ``unassigned_core`` with a reason.  This is not tidiness: ``MIS 200`` is the
   only class in the product with a scored benchmark behind it, and an edit that
   dropped it from every class list would empty the demonstration path without
   failing anything else.  Claiming one course twice is the same failure
   mirrored -- it double-counts the measured fraction the whole grid is for.

3. **A major's id is unique and is a URL segment.**  Ids are authored rather
   than slugified from names, so that renaming a major in the catalog does not
   silently break every link to it -- which means nothing else enforces
   uniqueness.

Title precedence
----------------
``majors.yaml`` wins where it states a title, because the course catalog is the
authority on course titles and the curriculum map abbreviates them (the map
prints "Fundamentals of MIS"; the catalog prints "Fundamentals of Management
Information Systems").  :func:`title_disagreements` reports every such
difference so a divergence is *visible* rather than silent.  It is deliberately
not an error: an abbreviation is not a bug, and gating on it would force a
transcription of one document to be edited to match another.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ida_core.curriculum import CurriculumMap
from ida_core.validation import ValidationError, load_yaml, validate_majors_document

CLASS_SOURCE_LABELS: dict[str, str] = {
    "catalog": "Transcribed from the course catalog",
    "core-only": "Only the classes this major owns in the shared business core",
    "none": "No class of this major has been catalogued yet",
}
"""What each ``class_source`` value means, in the words a reader gets.

Held here rather than in the UI for the reason every other enum label is: a
list of three strings typed into a component is a list that disagrees with the
data the first time a fourth value is added.
"""


class MajorClass(BaseModel):
    """One class a major owns."""

    model_config = ConfigDict(extra="forbid")

    course: str
    """The course code as the catalog prints it, e.g. ``MIS 200``.

    The join key into ``curriculum/slo.yaml``'s coverage grid, so it must be
    spelled the way that grid spells it.
    """

    title: str | None = None
    """The catalog's title, when it differs from the map's or the map has none.

    ``None`` means "inherit from the coverage row", which is the common case and
    the drift-proof one.  :meth:`Majors.resolve_title` is the one place that
    resolution happens.
    """

    credit_hours: float | None = None

    task_families: list[str] = Field(default_factory=list)
    """Task families whose results are ABOUT this class's own material.

    ⚠ THE FIELD THAT MAKES "MEASURED" A CLAIM ABOUT A CLASS.  Results are filed
    by OUTCOME -- a task carries ``slo:SLO2``, not ``course:MIS 200``.  So
    "how does a model do on MIS 200" computed from the outcomes MIS 200 teaches
    is really "how does it do on SLO1, SLO2 and SLO9", and that number is
    identical for every other course the map marks against those outcomes.  The
    moment the MIS 200 families are run, AC 210, ST 260, GBA 300, OM 300 and
    FI 302 would each display an exam score from a course none of them is.

    An empty list therefore means "no result can be attributed to this class",
    and that is the right default: a class shows a number only when somebody has
    authored tasks about it and said so here.
    """


class Major(BaseModel):
    """One undergraduate major, and the classes it owns."""

    model_config = ConfigDict(extra="forbid")

    id: str
    """The URL segment.  Authored, not slugified -- see the module docstring."""

    name: str
    department: str
    subject_codes: list[str] = Field(default_factory=list)
    """The prefixes this major's classes carry.

    ⚠ RECORDED FOR THE READER, NEVER USED TO DERIVE A CLASS LIST.  A class
    belongs to a major because it is listed under it, not because a regex
    matched its code: ``MIS 460`` is an MIS-prefix course that a Business Cyber
    Security student takes, and a derivation would have to decide that silently.
    """

    catalog: str | None = None
    class_source: Literal["catalog", "core-only", "none"]
    classes: list[MajorClass] = Field(default_factory=list)

    @property
    def class_source_label(self) -> str:
        return CLASS_SOURCE_LABELS[self.class_source]

    @model_validator(mode="after")
    def _classes_are_unique(self) -> Major:
        codes = [c.course for c in self.classes]
        dupes = sorted({c for c in codes if codes.count(c) > 1})
        if dupes:
            raise ValueError(f"major {self.id!r} lists the same course twice: {dupes}")
        return self

    @model_validator(mode="after")
    def _an_empty_list_says_so(self) -> Major:
        """``class_source: none`` and a non-empty list contradict each other.

        Small, and worth catching: ``class_source`` is what the UI renders to
        explain a short list, so a value that disagrees with the list beside it
        is a caption describing a different page.
        """
        if self.class_source == "none" and self.classes:
            raise ValueError(
                f"major {self.id!r} declares class_source: none but lists "
                f"{len(self.classes)} class(es); one of the two is wrong"
            )
        if self.class_source != "none" and not self.classes:
            raise ValueError(
                f"major {self.id!r} lists no classes but declares "
                f"class_source: {self.class_source!r}; use 'none' to say so"
            )
        return self


class UnassignedCourse(BaseModel):
    """A coverage course no single major owns, and why."""

    model_config = ConfigDict(extra="forbid")

    course: str
    reason: str


class Majors(BaseModel):
    """Parsed ``curriculum/majors.yaml``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    institution: str
    college: str
    degree: str = ""
    source: str
    source_title: str = ""
    retrieved: str
    majors: Annotated[list[Major], Field(min_length=1)]
    unassigned_core: list[UnassignedCourse] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Majors:
        ids = [m.id for m in self.majors]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate major ids: {dupes}")
        return self

    @model_validator(mode="after")
    def _no_course_belongs_to_two_majors(self) -> Majors:
        """One class, one owner.

        A course listed under two majors double-counts in the one number the
        top-level grid exists to show -- how much of a major has been measured.
        """
        owners: dict[str, list[str]] = {}
        for major in self.majors:
            for entry in major.classes:
                owners.setdefault(entry.course, []).append(major.id)
        clashes = {course: sorted(ids) for course, ids in owners.items() if len(ids) > 1}
        if clashes:
            problems = "; ".join(
                f"{course} is claimed by {', '.join(ids)}"
                for course, ids in sorted(clashes.items())
            )
            raise ValueError(f"a course may belong to only one major: {problems}")
        return self

    # -- lookups ---------------------------------------------------------

    def get(self, major_id: str) -> Major:
        for major in self.majors:
            if major.id == major_id:
                return major
        raise KeyError(f"no major with id {major_id!r} in the majors file")

    def major_ids(self) -> list[str]:
        return [m.id for m in self.majors]

    def claimed_courses(self) -> set[str]:
        """Every course code any major lists."""
        return {entry.course for major in self.majors for entry in major.classes}

    def major_for_course(self, course_code: str) -> Major | None:
        """The major that owns a course, or ``None``.

        ``None`` rather than a raise: a course the catalog does not attribute is
        a real state (``unassigned_core``), and callers that need to tell it
        apart from a typo should check :meth:`claimed_courses`.
        """
        for major in self.majors:
            if any(entry.course == course_code for entry in major.classes):
                return major
        return None

    def task_families(self) -> set[str]:
        """Every task family any class in this taxonomy is measured by."""
        return {
            family
            for major in self.majors
            for entry in major.classes
            for family in entry.task_families
        }

    def resolve_title(self, entry: MajorClass, curriculum: CurriculumMap | None) -> str | None:
        """This class's title, catalog first, then the curriculum map.

        ``None`` means the class can name itself from neither file, which
        :func:`check_against_curriculum` reports as an error rather than
        rendering as a nameless column.
        """
        if entry.title:
            return entry.title
        if curriculum is None:
            return None
        for row in curriculum.coverage:
            if row.course == entry.course:
                return row.title
        return None


def load_majors(path: Path | str) -> Majors:
    """Load and fully validate ``curriculum/majors.yaml``.

    Runs both layers, for the reason :mod:`ida_core.validation` gives: the JSON
    Schema for structure, the pydantic model for the cross-field rules a schema
    expresses badly (a course claimed by two majors).  The cross-FILE rules need
    the curriculum map too and live in :func:`check_against_curriculum`.
    """
    path = Path(path)
    if not path.is_file():
        raise ValidationError(path, ["majors file not found"])
    try:
        document = load_yaml(path)
    except Exception as exc:
        raise ValidationError(path, [f"could not parse YAML: {exc}"]) from exc
    if not isinstance(document, dict):
        raise ValidationError(path, [f"top level must be a mapping, got {type(document).__name__}"])
    validate_majors_document(document, path)
    try:
        return Majors.model_validate(document)
    except Exception as exc:
        raise ValidationError(path, [str(exc)]) from exc


def default_majors_path(root: Path | str) -> Path:
    """Where the majors file lives relative to a repo root."""
    return Path(root) / "curriculum" / "majors.yaml"


def check_against_curriculum(majors: Majors, curriculum: CurriculumMap) -> list[str]:
    """Every cross-file problem between the taxonomy and the map.  Empty is clean.

    Returns *all* problems rather than raising on the first, so an author fixing
    the taxonomy gets the whole list in one pass -- the same contract
    :func:`ida_core.curriculum.check_task_tags` has, and for the same reason.

    Enforced, in order:

    1. Every class can name itself: it carries a ``title``, or the coverage grid
       has a row for its code.
    2. Every coverage course is claimed by exactly one major, or is listed under
       ``unassigned_core`` with a reason.
    3. ``unassigned_core`` names courses that are actually in the coverage grid
       and are not also claimed by a major -- an escape hatch that names a
       course nobody was going to look for is a stale line, and one that names a
       claimed course is a contradiction.
    """
    problems: list[str] = []
    coverage_codes = {row.course for row in curriculum.coverage}

    for major in majors.majors:
        for entry in major.classes:
            if majors.resolve_title(entry, curriculum) is None:
                problems.append(
                    f"major {major.id!r}: class {entry.course!r} has no title and no row in "
                    f"the curriculum coverage grid, so nothing can name it; give it a "
                    f"'title:' or add it to curriculum/slo.yaml's coverage"
                )

    claimed = majors.claimed_courses()
    excused = {row.course for row in majors.unassigned_core}

    for code in sorted(coverage_codes - claimed - excused):
        problems.append(
            f"course {code!r} is in the curriculum coverage grid but no major claims it and "
            f"it is not in 'unassigned_core'; it would be unreachable from the drill-down"
        )

    for row in majors.unassigned_core:
        if row.course not in coverage_codes:
            problems.append(
                f"'unassigned_core' names {row.course!r}, which is not in the curriculum "
                f"coverage grid; the line is stale"
            )
        if row.course in claimed:
            owner = majors.major_for_course(row.course)
            problems.append(
                f"'unassigned_core' names {row.course!r}, but major "
                f"{owner.id if owner else '?'!r} also claims it; it cannot be both"
            )

    return problems


def check_task_families(majors: Majors, known_families: set[str]) -> list[str]:
    """Every ``task_families`` entry that names a family the catalogue does not have.

    ⚠ THE FAILURE THIS CATCHES IS PERFECTLY SILENT.  A misspelled family is not
    an error anywhere: the class simply matches no result, renders "not measured
    yet" forever, and looks exactly like a class nobody has got round to running.
    It is the same shape as the ``slo:SL02`` typo :mod:`ida_core.curriculum`
    exists to catch, one file over -- a real number filed under a heading that
    does not exist -- except here the number never appears at all, which is
    harder to notice, not easier.
    """
    return [
        f"major {major.id!r}: class {entry.course!r} lists task family {family!r}, which no "
        f"task in the catalogue belongs to; the class would read 'not measured yet' forever"
        for major in majors.majors
        for entry in major.classes
        for family in entry.task_families
        if family not in known_families
    ]


def title_disagreements(majors: Majors, curriculum: CurriculumMap) -> list[tuple[str, str, str]]:
    """``(course, catalog title, map title)`` for every course the two files name differently.

    ⚠ REPORTED, NOT GATED, AND THAT IS THE DECISION.  The catalog is the
    authority on course titles and the curriculum map abbreviates them, so a
    difference is expected -- ``MIS 200`` is "Fundamentals of Management
    Information Systems" in one and "Fundamentals of MIS" in the other.  Failing
    on it would force a transcription of one published document to be edited to
    agree with a different published document, which is exactly the kind of
    quiet reconciliation the provenance fields exist to prevent.  Printing it
    means a divergence that *is* a mistake is visible in CI rather than silent.
    """
    by_code = {row.course: row.title for row in curriculum.coverage}
    out: list[tuple[str, str, str]] = []
    for major in majors.majors:
        for entry in major.classes:
            mapped = by_code.get(entry.course)
            if entry.title and mapped and entry.title != mapped:
                out.append((entry.course, entry.title, mapped))
    return sorted(out)
