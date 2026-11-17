"""``/admin/majors``, ``/admin/classes``, ``/admin/units``, ``/admin/curriculum/slo``.

The Classes area of the console.  Every write re-runs the curriculum rules on
the post-write state (``service.curriculum_issues``): every class nameable,
every coverage course claimed -- so MIS 200 can never be orphaned from the
drill-down -- class families real, and the two unit invariants:

1. a family sits in AT MOST ONE unit (``UNIQUE(unit_families.family_key)``);
2. a unit's families are a SUBSET of its class's (composite FK onto
   ``class_task_families``).

Both are also database constraints; the code checks them first so the admin
gets a sentence naming the unit, not a constraint name.

Units are numbered 1..k with no gaps, always: inserting at ``n`` shifts the
rest, deleting closes the gap, and renumbering goes through negative numbers
first so ``UNIQUE(course, n)`` never trips mid-update.
"""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select

from ida_api.admin.deps import Admin, IfMatch, set_etag
from ida_api.admin.schemas import (
    AdminClass,
    AdminMajor,
    AdminUnit,
    ClassInput,
    FamiliesInput,
    MajorInput,
    MajorsResponse,
    ReorderInput,
    SloDocument,
    SloInput,
    UnitInput,
)
from ida_api.admin.service import (
    SCOPE_CURRICULUM,
    admin_write,
    bump,
    conflict,
    expect_version,
    not_found,
    require_db_config,
    stamp_new,
    to_issue_models,
    validation_failed,
)
from ida_api.deps import AppContext, get_context
from ida_core.configdb.reader import SLO_DOCUMENT, slo_document
from ida_core.configdb.seed import normalise_document
from ida_core.configdb.tables import (
    ClassRow,
    ClassTaskFamilyRow,
    CurriculumDocumentRow,
    MajorRow,
    TaskFamilyRow,
    UnitFamilyRow,
    UnitRow,
)
from ida_core.contracts import content_sha_of
from ida_core.db import session_scope
from ida_core.ids import new_id
from ida_core.validation_suite import Issue, errors_of, parse_curriculum

router = APIRouter(tags=["admin: curriculum"])


def _write(ctx, admin, action: str, entity_type: str, entity_id: str, summary: str):
    return admin_write(
        ctx,
        admin,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        scopes={SCOPE_CURRICULUM},
    )


# ──────────────────────────────────────────────────────────────── views ──


def _unit_view(session, row: UnitRow) -> AdminUnit:
    families = list(
        session.scalars(
            select(UnitFamilyRow.family_key)
            .where(UnitFamilyRow.unit_id == row.id)
            .order_by(UnitFamilyRow.position)
        )
    )
    return AdminUnit(
        id=row.id,
        course=row.course,
        key=row.key,
        n=row.n,
        title=row.title,
        covers=list(row.covers or []),
        blurb=row.blurb or "",
        source=row.source,
        caveat=row.caveat,
        families=families,
        version=row.version,
    )


def _coverage_titles(session) -> dict[str, str]:
    doc = slo_document(session) or {}
    return {row.get("course"): row.get("title") for row in doc.get("coverage") or []}


def _class_view(session, row: ClassRow, titles: dict[str, str] | None = None) -> AdminClass:
    titles = titles if titles is not None else _coverage_titles(session)
    families = list(
        session.scalars(
            select(ClassTaskFamilyRow.family_key)
            .where(ClassTaskFamilyRow.course == row.course)
            .order_by(ClassTaskFamilyRow.position)
        )
    )
    units = session.scalars(select(UnitRow).where(UnitRow.course == row.course).order_by(UnitRow.n))
    return AdminClass(
        course=row.course,
        major_id=row.major_id,
        unassigned_reason=row.unassigned_reason,
        title=row.title,
        resolved_title=row.title or titles.get(row.course),
        credit_hours=row.credit_hours,
        position=row.position,
        task_families=families,
        units=[_unit_view(session, u) for u in units],
        version=row.version,
    )


def _major_view(session, row: MajorRow, titles: dict[str, str] | None = None) -> AdminMajor:
    titles = titles if titles is not None else _coverage_titles(session)
    classes = session.scalars(
        select(ClassRow)
        .where(ClassRow.major_id == row.id)
        .order_by(ClassRow.position, ClassRow.course)
    )
    return AdminMajor(
        id=row.id,
        name=row.name,
        department=row.department,
        subject_codes=list(row.subject_codes or []),
        display_code=row.display_code,
        catalog=row.catalog,
        class_source=row.class_source,
        position=row.position,
        classes=[_class_view(session, c, titles) for c in classes],
        version=row.version,
    )


def _majors_response(session) -> MajorsResponse:
    titles = _coverage_titles(session)
    majors = session.scalars(select(MajorRow).order_by(MajorRow.position, MajorRow.id))
    unassigned = session.scalars(
        select(ClassRow).where(ClassRow.major_id.is_(None)).order_by(ClassRow.position)
    )
    return MajorsResponse(
        majors=[_major_view(session, m, titles) for m in majors],
        unassigned=[_class_view(session, c, titles) for c in unassigned],
    )


# ─────────────────────────────────────────────────────────────── majors ──


@router.get("/majors", response_model=MajorsResponse)
def list_majors(_: Admin, ctx: AppContext = Depends(get_context)) -> MajorsResponse:
    """One call renders the whole Classes area: majors, classes, units."""
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        return _majors_response(session)


def _apply_major(row: MajorRow, body: MajorInput) -> None:
    row.name = body.name
    row.department = body.department
    row.subject_codes = list(body.subject_codes)
    row.display_code = body.display_code
    row.catalog = body.catalog
    row.class_source = body.class_source
    row.position = body.position


@router.post("/majors", response_model=AdminMajor, status_code=status.HTTP_201_CREATED)
def create_major(
    body: MajorInput, admin: Admin, response: Response, ctx: AppContext = Depends(get_context)
) -> AdminMajor:
    with _write(ctx, admin, "major.create", "major", body.id, f"create major {body.id}") as w:
        if w.session.get(MajorRow, body.id) is not None:
            raise conflict(f"major {body.id!r} already exists")
        row = stamp_new(MajorRow(id=body.id), admin)
        _apply_major(row, body)
        w.session.add(row)
        w.session.flush()
        view = _major_view(w.session, row)
        w.after = view.model_dump(mode="json", exclude={"classes"})
    set_etag(response, view.version)
    return view


@router.post("/majors/reorder", response_model=list[AdminMajor])
def reorder_majors(
    body: ReorderInput, admin: Admin, ctx: AppContext = Depends(get_context)
) -> list[AdminMajor]:
    with _write(ctx, admin, "major.reorder", "major", "*", "reorder majors") as w:
        for position, major_id in enumerate(body.order):
            row = w.session.get(MajorRow, major_id)
            if row is None:
                raise validation_failed([Issue(f"order[{position}]", f"no major {major_id!r}")])
            if row.position != position:
                row.position = position
                bump(row, admin)
        w.after = {"order": body.order}
    with session_scope(ctx.session_factory) as session:
        return _majors_response(session).majors


@router.put("/majors/{major_id}", response_model=AdminMajor)
def update_major(
    major_id: str,
    body: MajorInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminMajor:
    if body.id != major_id:
        raise validation_failed([Issue("id", "a major's id cannot change")])
    with _write(ctx, admin, "major.update", "major", major_id, f"update major {major_id}") as w:
        row = w.session.get(MajorRow, major_id)
        if row is None:
            raise not_found(f"major {major_id!r}")
        before = _major_view(w.session, row)
        expect_version(row, version, before.model_dump(mode="json"))
        _apply_major(row, body)
        bump(row, admin)
        view = _major_view(w.session, row)
        w.before = before.model_dump(mode="json", exclude={"classes"})
        w.after = view.model_dump(mode="json", exclude={"classes"})
    set_etag(response, view.version)
    return view


@router.delete(
    "/majors/{major_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_major(
    major_id: str, admin: Admin, version: IfMatch, ctx: AppContext = Depends(get_context)
) -> Response:
    """409 while it owns classes."""
    with _write(ctx, admin, "major.delete", "major", major_id, f"delete major {major_id}") as w:
        row = w.session.get(MajorRow, major_id)
        if row is None:
            raise not_found(f"major {major_id!r}")
        view = _major_view(w.session, row)
        expect_version(row, version, view.model_dump(mode="json"))
        if view.classes:
            raise conflict(
                f"major {major_id!r} still owns {[c.course for c in view.classes]}; move or "
                "delete those classes first"
            )
        w.before = view.model_dump(mode="json", exclude={"classes"})
        w.session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ────────────────────────────────────────────────────────────── classes ──


def _apply_class(session, row: ClassRow, body: ClassInput) -> None:
    if body.major_id is not None and session.get(MajorRow, body.major_id) is None:
        raise validation_failed([Issue("major_id", f"no major {body.major_id!r}")])
    row.major_id = body.major_id
    row.unassigned_reason = body.unassigned_reason
    row.title = body.title
    row.credit_hours = body.credit_hours
    row.position = body.position


def _live_class(session, course: str) -> ClassRow:
    row = session.get(ClassRow, course)
    if row is None:
        raise not_found(f"class {course!r}")
    return row


@router.post("/classes", response_model=AdminClass, status_code=status.HTTP_201_CREATED)
def create_class(
    body: ClassInput, admin: Admin, response: Response, ctx: AppContext = Depends(get_context)
) -> AdminClass:
    """Revalidated against the curriculum map's coverage (the "every coverage
    course is claimed" gate)."""
    with _write(
        ctx, admin, "class.create", "class", body.course, f"create class {body.course}"
    ) as w:
        if w.session.get(ClassRow, body.course) is not None:
            raise conflict(f"class {body.course!r} already exists")
        row = stamp_new(ClassRow(course=body.course), admin)
        _apply_class(w.session, row, body)
        w.session.add(row)
        w.session.flush()
        view = _class_view(w.session, row)
        w.after = view.model_dump(mode="json", exclude={"units"})
    set_etag(response, view.version)
    return view


@router.put("/classes/{course}", response_model=AdminClass)
def update_class(
    course: str,
    body: ClassInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminClass:
    if body.course != course:
        raise validation_failed([Issue("course", "a class's course code cannot change")])
    with _write(ctx, admin, "class.update", "class", course, f"update class {course}") as w:
        row = _live_class(w.session, course)
        before = _class_view(w.session, row)
        expect_version(row, version, before.model_dump(mode="json"))
        _apply_class(w.session, row, body)
        bump(row, admin)
        w.session.flush()
        view = _class_view(w.session, row)
        w.before = before.model_dump(mode="json", exclude={"units"})
        w.after = view.model_dump(mode="json", exclude={"units"})
    set_etag(response, view.version)
    return view


@router.delete("/classes/{course}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_class(
    course: str, admin: Admin, version: IfMatch, ctx: AppContext = Depends(get_context)
) -> Response:
    """409 while the class has units; the coverage gate refuses deleting a
    course the curriculum map still lists (MIS 200 included)."""
    with _write(ctx, admin, "class.delete", "class", course, f"delete class {course}") as w:
        row = _live_class(w.session, course)
        view = _class_view(w.session, row)
        expect_version(row, version, view.model_dump(mode="json"))
        if view.units:
            raise conflict(
                f"class {course!r} still has {len(view.units)} unit(s); delete them first"
            )
        for link in w.session.scalars(
            select(ClassTaskFamilyRow).where(ClassTaskFamilyRow.course == course)
        ):
            w.session.delete(link)
        w.session.flush()
        w.before = view.model_dump(mode="json", exclude={"units"})
        w.session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _check_families_exist(session, families: list[str], path: str) -> None:
    live = set(
        session.scalars(select(TaskFamilyRow.key).where(TaskFamilyRow.archived_at.is_(None)))
    )
    issues = [
        Issue(f"{path}[{i}]", f"no live task family {f!r}")
        for i, f in enumerate(families)
        if f not in live
    ]
    if len(set(families)) != len(families):
        issues.append(Issue(path, "a family is listed twice"))
    if issues:
        raise validation_failed(issues)


@router.put("/classes/{course}/task-families", response_model=AdminClass)
def set_class_families(
    course: str,
    body: FamiliesInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminClass:
    """409 ``conflict`` naming the unit if a removed family is still claimed by
    one of this class's units (invariant 2)."""
    with _write(ctx, admin, "class.update", "class", course, f"set task families of {course}") as w:
        row = _live_class(w.session, course)
        before = _class_view(w.session, row)
        expect_version(row, version, before.model_dump(mode="json"))
        _check_families_exist(w.session, body.families, "families")
        removed = set(before.task_families) - set(body.families)
        for unit in before.units:
            claimed = removed & set(unit.families)
            if claimed:
                raise conflict(
                    f"{sorted(claimed)} cannot leave {course}: unit {unit.n} "
                    f"({unit.title!r}) still holds it; remove it from the unit first"
                )
        # Diff the links rather than delete-all-and-reinsert: a family a unit
        # still holds must never be removed even for an instant, because on
        # Postgres the unit's composite FK refuses it at the statement.
        links = {
            link.family_key: link
            for link in w.session.scalars(
                select(ClassTaskFamilyRow).where(ClassTaskFamilyRow.course == course)
            )
        }
        for family in removed:
            w.session.delete(links[family])
        w.session.flush()
        for position, family in enumerate(body.families):
            if family in links:
                links[family].position = position
            else:
                w.session.add(
                    ClassTaskFamilyRow(course=course, family_key=family, position=position)
                )
        bump(row, admin)
        w.session.flush()
        view = _class_view(w.session, row)
        w.before = {"task_families": before.task_families}
        w.after = {"task_families": view.task_families}
    set_etag(response, view.version)
    return view


# ──────────────────────────────────────────────────────────────── units ──


def _course_units(session, course: str) -> list[UnitRow]:
    return list(
        session.scalars(select(UnitRow).where(UnitRow.course == course).order_by(UnitRow.n))
    )


def _renumber(session, ordered: list[UnitRow], admin) -> None:
    """Set n = 1..k in the given order.  Negatives first, so the
    ``UNIQUE(course, n)`` constraint never sees a transient duplicate."""
    for index, unit in enumerate(ordered, start=1):
        unit.n = -index
    session.flush()
    for index, unit in enumerate(ordered, start=1):
        if unit.n != index:
            unit.n = index
            bump(unit, admin)
    session.flush()


def _check_unit_families(session, course: str, families: list[str], unit_id: str | None) -> None:
    """Both invariants, as readable issues, before the database's constraints."""
    issues: list[Issue] = []
    owned = set(
        session.scalars(
            select(ClassTaskFamilyRow.family_key).where(ClassTaskFamilyRow.course == course)
        )
    )
    if len(set(families)) != len(families):
        issues.append(Issue("families", "a family is listed twice"))
    for index, family in enumerate(families):
        if family not in owned:
            issues.append(
                Issue(
                    f"families[{index}]",
                    f"{family!r} is not one of {course}'s task families; add it to the class first",
                )
            )
        holder = session.execute(
            select(UnitRow.course, UnitRow.n, UnitRow.title, UnitRow.id)
            .join(UnitFamilyRow, UnitFamilyRow.unit_id == UnitRow.id)
            .where(UnitFamilyRow.family_key == family)
        ).first()
        if holder is not None and holder[3] != unit_id:
            issues.append(
                Issue(
                    f"families[{index}]",
                    f"{family!r} is already in unit {holder[1]} ({holder[2]!r}) of {holder[0]}; "
                    "a family may sit in at most one unit",
                )
            )
    if issues:
        raise validation_failed(issues)


def _set_unit_families(session, unit: UnitRow, families: list[str]) -> None:
    for link in session.scalars(select(UnitFamilyRow).where(UnitFamilyRow.unit_id == unit.id)):
        session.delete(link)
    session.flush()
    for position, family in enumerate(families):
        session.add(
            UnitFamilyRow(unit_id=unit.id, course=unit.course, family_key=family, position=position)
        )
    session.flush()


def _apply_unit(unit: UnitRow, body: UnitInput) -> None:
    unit.key = body.key
    unit.title = body.title
    unit.covers = list(body.covers)
    unit.blurb = body.blurb
    unit.source = body.source
    unit.caveat = body.caveat


def _place(session, course: str, unit: UnitRow, n: int, admin) -> None:
    """Put ``unit`` at position ``n`` (clamped to 1..k) and close every gap."""
    others = [u for u in _course_units(session, course) if u.id != unit.id]
    index = max(0, min(n - 1, len(others)))
    _renumber(session, [*others[:index], unit, *others[index:]], admin)


def _key_taken(session, course: str, key: str, unit_id: str | None) -> bool:
    found = session.scalar(select(UnitRow.id).where(UnitRow.course == course, UnitRow.key == key))
    return found is not None and found != unit_id


@router.get("/classes/{course}/units", response_model=list[AdminUnit])
def list_units(course: str, _: Admin, ctx: AppContext = Depends(get_context)) -> list[AdminUnit]:
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        _live_class(session, course)
        return [_unit_view(session, u) for u in _course_units(session, course)]


@router.post(
    "/classes/{course}/units", response_model=AdminUnit, status_code=status.HTTP_201_CREATED
)
def create_unit(
    course: str,
    body: UnitInput,
    admin: Admin,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminUnit:
    """Inserted at ``n`` (later units shift down).  Invariants are checked
    before the database constraint and reported as issues with readable text."""
    with _write(
        ctx, admin, "unit.create", "unit", f"{course}/{body.key}", f"add unit to {course}"
    ) as w:
        _live_class(w.session, course)
        if _key_taken(w.session, course, body.key, None):
            raise validation_failed([Issue("key", f"{course} already has a unit {body.key!r}")])
        _check_unit_families(w.session, course, body.families, None)
        existing = _course_units(w.session, course)
        unit = stamp_new(UnitRow(id=new_id("unit"), course=course, n=len(existing) + 1), admin)
        _apply_unit(unit, body)
        w.session.add(unit)
        w.session.flush()
        _place(w.session, course, unit, body.n, admin)
        _set_unit_families(w.session, unit, body.families)
        view = _unit_view(w.session, unit)
        w.entity_id = unit.id
        w.after = view.model_dump(mode="json")
    set_etag(response, view.version)
    return view


@router.post("/classes/{course}/units/reorder", response_model=list[AdminUnit])
def reorder_units(
    course: str, body: ReorderInput, admin: Admin, ctx: AppContext = Depends(get_context)
) -> list[AdminUnit]:
    """Renumbers ``n`` 1..k in the given order, in one transaction.  The order
    must name every unit of the class exactly once."""
    with _write(ctx, admin, "unit.reorder", "unit", course, f"reorder units of {course}") as w:
        _live_class(w.session, course)
        units = {u.id: u for u in _course_units(w.session, course)}
        if sorted(body.order) != sorted(units):
            raise validation_failed(
                [Issue("order", f"list every unit of {course} exactly once: {sorted(units)}")]
            )
        w.before = {u.id: u.n for u in units.values()}
        _renumber(w.session, [units[i] for i in body.order], admin)
        w.after = {i: units[i].n for i in body.order}
        views = [_unit_view(w.session, units[i]) for i in body.order]
    return views


def _live_unit(session, unit_id: str) -> UnitRow:
    row = session.get(UnitRow, unit_id)
    if row is None:
        raise not_found(f"unit {unit_id!r}")
    return row


@router.put("/units/{unit_id}", response_model=AdminUnit)
def update_unit(
    unit_id: str,
    body: UnitInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminUnit:
    with _write(ctx, admin, "unit.update", "unit", unit_id, f"update unit {unit_id}") as w:
        unit = _live_unit(w.session, unit_id)
        before = _unit_view(w.session, unit)
        expect_version(unit, version, before.model_dump(mode="json"))
        if _key_taken(w.session, unit.course, body.key, unit.id):
            raise validation_failed(
                [Issue("key", f"{unit.course} already has a unit {body.key!r}")]
            )
        _check_unit_families(w.session, unit.course, body.families, unit.id)
        _apply_unit(unit, body)
        bump(unit, admin)
        _place(w.session, unit.course, unit, body.n, admin)
        _set_unit_families(w.session, unit, body.families)
        view = _unit_view(w.session, unit)
        w.before, w.after = before.model_dump(mode="json"), view.model_dump(mode="json")
    set_etag(response, view.version)
    return view


@router.put("/units/{unit_id}/families", response_model=AdminUnit)
def set_unit_families(
    unit_id: str,
    body: FamiliesInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> AdminUnit:
    """The focused "assign families" call."""
    with _write(
        ctx, admin, "unit.update", "unit", unit_id, f"assign families to unit {unit_id}"
    ) as w:
        unit = _live_unit(w.session, unit_id)
        before = _unit_view(w.session, unit)
        expect_version(unit, version, before.model_dump(mode="json"))
        _check_unit_families(w.session, unit.course, body.families, unit.id)
        _set_unit_families(w.session, unit, body.families)
        bump(unit, admin)
        view = _unit_view(w.session, unit)
        w.before, w.after = {"families": before.families}, {"families": view.families}
    set_etag(response, view.version)
    return view


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_unit(
    unit_id: str, admin: Admin, version: IfMatch, ctx: AppContext = Depends(get_context)
) -> Response:
    """Later units move up one, so numbering stays 1..k."""
    with _write(ctx, admin, "unit.delete", "unit", unit_id, f"delete unit {unit_id}") as w:
        unit = _live_unit(w.session, unit_id)
        view = _unit_view(w.session, unit)
        expect_version(unit, version, view.model_dump(mode="json"))
        course = unit.course
        _set_unit_families(w.session, unit, [])
        w.session.delete(unit)
        w.session.flush()
        _renumber(w.session, _course_units(w.session, course), admin)
        w.before = view.model_dump(mode="json")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────── outcomes (slo.yaml) ──


def _render(document: dict | None) -> str:
    return yaml.safe_dump(document or {}, sort_keys=False, allow_unicode=True, width=100)


@router.get("/curriculum/slo", response_model=SloDocument)
def get_slo(_: Admin, response: Response, ctx: AppContext = Depends(get_context)) -> SloDocument:
    """The whole ``slo.yaml`` (outcomes, use modes, coverage) as YAML."""
    require_db_config(ctx)
    with session_scope(ctx.session_factory) as session:
        row = session.get(CurriculumDocumentRow, SLO_DOCUMENT)
        if row is None:
            raise not_found("the curriculum map")
        doc = SloDocument(yaml=_render(row.document), version=row.version)
    set_etag(response, doc.version)
    return doc


@router.put("/curriculum/slo", response_model=SloDocument)
def put_slo(
    body: SloInput,
    admin: Admin,
    version: IfMatch,
    response: Response,
    ctx: AppContext = Depends(get_context),
) -> SloDocument:
    """Validated as ``slo.yaml`` (schema + model), then the whole curriculum
    suite on the result -- so registrar data stays editable without code and
    still cannot orphan a course."""
    try:
        document: Any = yaml.safe_load(body.yaml)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}, col {mark.column + 1}" if mark else "yaml"
        raise validation_failed([Issue(where, f"could not parse YAML: {exc}")]) from None
    issues, curriculum = parse_curriculum(document)
    if curriculum is None or errors_of(issues):
        raise validation_failed(issues, "The curriculum map failed validation")
    with _write(ctx, admin, "curriculum_slo.update", "curriculum_slo", "slo", "edit slo.yaml") as w:
        row = w.session.get(CurriculumDocumentRow, SLO_DOCUMENT)
        if row is None:
            raise not_found("the curriculum map")
        expect_version(row, version, {"version": row.version})
        before = {"version": row.version, "sha": content_sha_of(row.document)}
        row.document = normalise_document(document)
        bump(row, admin)
        w.before = before
        w.after = {"version": row.version, "sha": content_sha_of(row.document)}
        result = SloDocument(yaml=_render(row.document), version=row.version)
    with session_scope(ctx.session_factory) as session:
        from ida_api.admin.service import curriculum_issues

        result.issues = to_issue_models(
            [i for i in curriculum_issues(session) if i.severity == "warning"]
        )
    set_etag(response, result.version)
    return result
