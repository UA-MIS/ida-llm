"""One validation suite, two callers (admin-console design section 4.4).

The rules that decide whether authored configuration is acceptable used to be
reachable only through ``tools/validate_tasks.py`` -- a CLI over files.  Once the
database is the source of truth, the admin API needs the SAME rules on the
post-write state of a transaction, and so does the seeder on the YAML it is
about to load.  Two copies of the rules would drift, and the copy that drifted
would be the one guarding production.  So the rules are here, returning
:class:`Issue` lists, and both callers use them:

* ``tools/validate_tasks.py`` -- the CI ``task-schema`` gate and
  ``make lint-tasks`` -- reads YAML and prints;
* the admin API and :func:`ida_core.configdb.seed.ensure_seeded` validate
  documents and roll back / refuse to boot on any ``error``.

The individual checks already lived in ``ida_core`` (``check_task_tags``,
``check_against_curriculum``, ...); this module is the one place that runs them
together and speaks in path-addressed issues the admin console can pin to form
fields.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from ida_core.contracts import ModelRegistry, TaskSpec
from ida_core.curriculum import CurriculumMap, check_task_tags
from ida_core.majors import (
    Majors,
    check_against_curriculum,
    check_task_families,
    title_disagreements,
)
from ida_core.units import Unit
from ida_core.validation import (
    ValidationError,
    validate_curriculum_document,
    validate_majors_document,
    validate_models_document,
    validate_task_document,
)


@dataclass(frozen=True)
class Issue:
    """One finding.  ``path`` is what a UI pins the message to."""

    path: str
    message: str
    severity: Literal["error", "warning"] = "error"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def errors_of(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


def issues_from_validation_error(exc: ValidationError) -> list[Issue]:
    """``ValidationError.errors`` are already path-prefixed strings
    (``samples/3/target: ...``); split each on the first ``": "``."""
    out = []
    for raw in exc.errors:
        path, sep, message = raw.partition(": ")
        out.append(Issue(path=path, message=message) if sep else Issue(path="", message=raw))
    return out


def _pydantic_issues(exc: Exception, prefix: str = "") -> list[Issue]:
    """A pydantic ``ValidationError`` as issues with dotted paths; anything else
    as one issue at ``prefix``."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            out = []
            for error in errors():
                loc = ".".join(str(part) for part in error.get("loc", ()))
                path = ".".join(p for p in (prefix, loc) if p)
                out.append(Issue(path=path, message=str(error.get("msg", exc))))
            if out:
                return out
        except Exception:  # noqa: S110 - fall through to the generic form
            pass
    return [Issue(path=prefix, message=str(exc))]


# ─────────────────────────────────────────────────────────────── models ──


def validate_models(document: Any) -> list[Issue]:
    """``models.yaml`` (or its database reconstruction): JSON Schema, then the
    pydantic registry (unique keys, key-source exclusivity, ...)."""
    try:
        validate_models_document(document)
    except ValidationError as exc:
        return issues_from_validation_error(exc)
    try:
        ModelRegistry.model_validate(document)
    except Exception as exc:
        return _pydantic_issues(exc)
    return []


# ──────────────────────────────────────────────────────────────── tasks ──


def task_family_of(task_id: str) -> str:
    """A task id's leading segment -- the family, by the repo's convention."""
    return task_id.split("/", 1)[0]


def validate_task(
    document: Any,
    *,
    curriculum: CurriculumMap | None,
    families: set[str] | None,
) -> tuple[list[Issue], TaskSpec | None]:
    """One task document: schema -> ``TaskSpec`` (taxonomy, metadata-leak rule)
    -> ``check_task_tags`` (the ``slo:``/``use-mode:`` typo trap) -> the family
    rule (the id's leading segment names an existing family).

    Returns the issues and, when there are no errors, the spec (with its
    ``content_sha`` stamped) so a caller does not parse twice.

    ``families=None`` skips the family rule (the file-tree CLI, where a family
    IS a directory and cannot be missing); ``curriculum=None`` refuses an
    SLO-tagged task rather than passing it unchecked, the CLI's long-standing
    rule: "we could not check" must never read as "we checked".
    """
    if not isinstance(document, dict):
        return [Issue(path="", message="a task document must be a mapping")], None
    try:
        validate_task_document(document)
    except ValidationError as exc:
        return issues_from_validation_error(exc), None
    try:
        spec = TaskSpec.from_document(document)
    except Exception as exc:
        return _pydantic_issues(exc), None

    issues: list[Issue] = []
    if curriculum is not None:
        issues.extend(Issue(path="tags", message=p) for p in check_task_tags(spec, curriculum))
    elif "slo-benchmark" in spec.tags or any(
        t.startswith(("slo:", "use-mode:")) for t in spec.tags
    ):
        issues.append(
            Issue(
                path="tags",
                message="is SLO-tagged but no curriculum map is available to check the tags against",
            )
        )
    if families is not None and "/" in spec.id and task_family_of(spec.id) not in families:
        issues.append(
            Issue(
                path="id",
                message=(
                    f"task id {spec.id!r} must start with an existing task family "
                    f"(no family {task_family_of(spec.id)!r})"
                ),
            )
        )
    if families is not None and "/" not in spec.id:
        issues.append(Issue(path="id", message="task id must be '<family>/<name>'"))
    return issues, (spec if not errors_of(issues) else None)


# ─────────────────────────────────────────────────────────── curriculum ──


def parse_curriculum(slo_document: Any) -> tuple[list[Issue], CurriculumMap | None]:
    try:
        validate_curriculum_document(slo_document)
    except ValidationError as exc:
        return issues_from_validation_error(exc), None
    try:
        return [], CurriculumMap.model_validate(slo_document)
    except Exception as exc:
        return _pydantic_issues(exc), None


def parse_majors(majors_document: Any) -> tuple[list[Issue], Majors | None]:
    try:
        validate_majors_document(majors_document)
    except ValidationError as exc:
        return issues_from_validation_error(exc), None
    try:
        return [], Majors.model_validate(majors_document)
    except Exception as exc:
        return _pydantic_issues(exc), None


def validate_curriculum(
    slo_document: Any, majors_document: Any | None, families: set[str]
) -> list[Issue]:
    """The curriculum map and the majors taxonomy, together.

    ``check_against_curriculum`` (every class nameable, every coverage course
    claimed -- the "MIS 200 must stay reachable" gate) and
    ``check_task_families`` are errors; ``title_disagreements`` are WARNINGS,
    exactly as the CLI has always printed-but-not-gated them."""
    issues, curriculum = parse_curriculum(slo_document)
    issues = [Issue(f"slo.{i.path}" if i.path else "slo", i.message, i.severity) for i in issues]
    if majors_document is None:
        return issues
    major_issues, majors = parse_majors(majors_document)
    issues += [
        Issue(f"majors.{i.path}" if i.path else "majors", i.message, i.severity)
        for i in major_issues
    ]
    if curriculum is None or majors is None:
        return issues
    issues += [
        Issue(path="majors", message=p)
        for p in check_against_curriculum(majors, curriculum)
        + check_task_families(majors, families)
    ]
    issues += [
        Issue(
            path=f"classes.{course}.title",
            message=f"catalog says {catalog!r}, curriculum map says {mapped!r}",
            severity="warning",
        )
        for course, catalog, mapped in title_disagreements(majors, curriculum)
    ]
    return issues


# ──────────────────────────────────────────────────────────────── units ──


def validate_units(units: dict[str, list[Unit]], majors: Majors | None) -> list[Issue]:
    """The two invariants that stop a unit fabricating a score, plus per-class
    uniqueness.  (Moved from the frontend's ``units.test.ts``.)

    1. A family sits in AT MOST ONE unit, across every class.
    2. A unit's families are a SUBSET of its class's ``task_families``.
    Plus: unit keys and numbers are unique within a class, numbers run 1..k in
    file order, and the class exists in the majors taxonomy.
    """
    issues: list[Issue] = []
    owner_of_family: dict[str, str] = {}
    class_families: dict[str, set[str]] = {}
    if majors is not None:
        for major in majors.majors:
            for entry in major.classes:
                class_families[entry.course] = set(entry.task_families)
        for row in majors.unassigned_core:
            class_families.setdefault(row.course, set())

    for course, rows in units.items():
        base = f"units.{course}"
        if majors is not None and course not in class_families:
            issues.append(Issue(base, f"class {course!r} is not in the majors taxonomy"))
        keys: set[str] = set()
        numbers: set[int] = set()
        for index, unit in enumerate(rows):
            here = f"{base}[{index}]"
            if unit.key in keys:
                issues.append(Issue(f"{here}.key", f"duplicate unit key {unit.key!r} in {course}"))
            if unit.n in numbers:
                issues.append(Issue(f"{here}.n", f"duplicate unit number {unit.n} in {course}"))
            keys.add(unit.key)
            numbers.add(unit.n)
            if unit.n != index + 1:
                issues.append(
                    Issue(f"{here}.n", f"units must be numbered 1..k in order; got {unit.n}")
                )
            for family in unit.families:
                label = f"{course} / {unit.key}"
                if family in owner_of_family and owner_of_family[family] != label:
                    issues.append(
                        Issue(
                            f"{here}.families",
                            f"family {family!r} is already in unit {owner_of_family[family]}; "
                            "a family may sit in at most one unit",
                        )
                    )
                owner_of_family.setdefault(family, label)
                if majors is not None and family not in class_families.get(course, set()):
                    issues.append(
                        Issue(
                            f"{here}.families",
                            f"family {family!r} is not one of {course}'s task_families; "
                            "a unit may only hold families its class owns",
                        )
                    )
    return issues
