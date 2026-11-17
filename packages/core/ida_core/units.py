"""Course units: ``curriculum/units.yaml`` -> ``{course: [Unit, ...]}`` (AD-11).

A unit is a part of a class as the class is taught -- its topics, and the task
families whose results define it.  The data used to be a hardcoded TypeScript
taxonomy in ``frontend/src/lib/units.ts``; it moved here so classes become
admin-editable, and the API serves it on ``CurriculumView.units``.

The two invariants that stop a unit fabricating a score -- a family in at most
one unit, and a unit's families a subset of its class's -- need the majors
taxonomy as well, so they live in :func:`ida_core.validation_suite.validate_units`
next to the other cross-file rules.  This module only parses.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ida_core.validation import ValidationError, load_yaml


class Unit(BaseModel):
    """One unit of one class.  Field-for-field the frontend's ``ClassUnit``."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    """URL segment and React key.  Stable; the title may be reworded."""
    n: int = Field(ge=1)
    """1-based position within the course, and its display order."""
    title: str = Field(min_length=1)
    covers: list[str] = Field(default_factory=list)
    """What this unit's tests cover -- the chips on the column header."""
    blurb: str = ""
    families: list[str] = Field(default_factory=list)
    """Task families whose results define this unit.  Empty = not measured yet."""
    source: str | None = None
    """The quiz or exercise set behind the unit's items.  Absent with no families."""
    caveat: str | None = None
    """An honesty caveat the unit's evidence page shows, when one is needed."""

    def as_document(self) -> dict:
        """The unit as authored: optional fields OMITTED when unset, exactly as
        the TypeScript taxonomy spelled them (so the snapshot test compares like
        with like)."""
        return self.model_dump(exclude_none=True)


Units = dict[str, list[Unit]]
"""Course code -> that class's units, in course order."""


def default_units_path(root: Path | str) -> Path:
    return Path(root) / "curriculum" / "units.yaml"


def parse_units_document(document: object, path: Path | str = "<units>") -> Units:
    """Validate a parsed ``units.yaml`` document.  Raises :class:`ValidationError`
    with every problem found, path-prefixed, rather than the first."""
    if not isinstance(document, dict):
        raise ValidationError(path, [f"top level must be a mapping, got {type(document).__name__}"])
    errors: list[str] = []
    if document.get("version") != 1:
        errors.append("version: must be 1")
    extra = set(document) - {"version", "classes"}
    if extra:
        errors.append(f"unknown top-level key(s): {sorted(extra)}")
    classes = document.get("classes")
    if not isinstance(classes, dict):
        errors.append("classes: must be a mapping of course code -> list of units")
        raise ValidationError(path, errors)
    out: Units = {}
    for course, units in classes.items():
        if not isinstance(units, list):
            errors.append(f"classes.{course}: must be a list of units")
            continue
        parsed: list[Unit] = []
        for index, raw in enumerate(units):
            try:
                parsed.append(Unit.model_validate(raw))
            except Exception as exc:
                errors.append(f"classes.{course}[{index}]: {exc}")
        out[str(course)] = parsed
    if errors:
        raise ValidationError(path, errors)
    return out


def load_units(path: Path | str) -> Units:
    """Load ``units.yaml``.  An ABSENT file is ``{}`` -- a deployment may run with
    no unit taxonomy, and the class page says so -- but a present, broken one
    raises: guessing at a class's units would be inventing a curriculum."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        document = load_yaml(path)
    except Exception as exc:
        raise ValidationError(path, [f"could not parse YAML: {exc}"]) from exc
    return parse_units_document(document, path)


def units_document(units: Units) -> dict:
    """The inverse of :func:`parse_units_document`: what ``units.yaml`` holds."""
    return {
        "version": 1,
        "classes": {course: [u.as_document() for u in rows] for course, rows in units.items()},
    }
