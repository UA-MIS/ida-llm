"""Rows -> the SAME documents the YAML loaders produce.

The parity guarantee (design 4.2/4.3) rests on one idea: the database path does
not get its own parsers.  Each reader here rebuilds the document the git file
would have held -- a ``models.yaml``-shaped dict, task documents, the
``slo.yaml``/``majors.yaml`` documents, the ``units.yaml`` map -- and the caller
runs it through the exact validators and pydantic models the YAML path uses.
If a row cannot be turned back into a document those validators accept, the
snapshot build fails loudly (and the provider keeps serving the previous one).

Optional keys are OMITTED rather than written as ``null`` wherever the YAML
would omit them: the JSON schemas are ``additionalProperties: false`` with
string types in places, and an explicit ``null`` the file never contained is a
schema error the YAML path would never see.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ida_core.configdb.tables import (
    ClassRow,
    ClassTaskFamilyRow,
    ConfigRevisionRow,
    CurriculumDocumentRow,
    MajorRow,
    ModelFamilyRow,
    ModelRow,
    TaskRow,
    UnitFamilyRow,
    UnitRow,
)
from ida_core.units import Unit, Units

SLO_DOCUMENT = "slo"
MAJORS_META_DOCUMENT = "majors_meta"


def current_revision(session: Session) -> tuple[int | None, datetime | None]:
    """``(max(config_revisions.id), its timestamp)`` -- ``(None, None)`` if unseeded."""
    revision = session.scalar(select(func.max(ConfigRevisionRow.id)))
    if revision is None:
        return None, None
    row = session.get(ConfigRevisionRow, revision)
    return int(revision), (row.at if row else None)


def is_seeded(session: Session) -> bool:
    return session.scalar(select(ConfigRevisionRow.id).limit(1)) is not None


def _put(target: dict, key: str, value: Any) -> None:
    if value is not None:
        target[key] = value


# ─────────────────────────────────────────────────────────────── models ──


def model_entry_document(row: ModelRow, family_names: dict[str, str]) -> dict:
    """One ``ModelRow`` as the ``models.yaml`` entry it would have been."""
    entry: dict[str, Any] = {
        "key": row.key,
        "display_name": row.display_name,
        # ModelEntry.base_url is a required str; "" is the file's own spelling
        # for "no literal, use base_url_env".
        "base_url": row.base_url or "",
        "serving": dict(row.serving),
        "cost": {
            "input_usd_per_mtok": float(row.cost_input_usd_per_mtok or 0.0),
            "output_usd_per_mtok": float(row.cost_output_usd_per_mtok or 0.0),
        },
        "timeout_s": float(row.timeout_s),
        "max_retries": int(row.max_retries),
        "enabled": bool(row.enabled),
        "tags": list(row.tags or []),
    }
    _put(entry, "base_url_env", row.base_url_env)
    _put(entry, "api_key_env", row.api_key_env)
    _put(entry, "credential_ref", row.credential_ref)
    if row.family_key is not None:
        entry["family"] = row.family_key
        entry["family_display_name"] = family_names.get(row.family_key, row.family_key)
    _put(entry, "display_order", row.display_order)
    if row.hidden:
        entry["hidden"] = True
    return entry


def models_document(session: Session) -> dict:
    """The live registry as a ``models.yaml`` document: non-archived models in
    REGISTRY order (``position``, then key)."""
    family_names = {f.key: f.display_name for f in session.scalars(select(ModelFamilyRow))}
    rows = session.scalars(
        select(ModelRow)
        .where(ModelRow.archived_at.is_(None))
        .order_by(ModelRow.position, ModelRow.key)
    )
    return {"version": 1, "models": [model_entry_document(r, family_names) for r in rows]}


# ──────────────────────────────────────────────────────────────── tasks ──


def task_documents(session: Session) -> list[tuple[str, dict]]:
    """``[(task_id, document)]`` for every live task, by id."""
    rows = session.scalars(
        select(TaskRow).where(TaskRow.archived_at.is_(None)).order_by(TaskRow.id)
    )
    return [(row.id, row.document) for row in rows]


# ─────────────────────────────────────────────────────────── curriculum ──


def slo_document(session: Session) -> dict | None:
    row = session.get(CurriculumDocumentRow, SLO_DOCUMENT)
    return dict(row.document) if row else None


def majors_document(session: Session) -> dict | None:
    """The live taxonomy as a ``majors.yaml`` document, or ``None`` if the
    deployment has none (no ``majors_meta`` row)."""
    meta = session.get(CurriculumDocumentRow, MAJORS_META_DOCUMENT)
    if meta is None:
        return None
    families_by_course: dict[str, list[str]] = {}
    for link in session.scalars(
        select(ClassTaskFamilyRow).order_by(ClassTaskFamilyRow.course, ClassTaskFamilyRow.position)
    ):
        families_by_course.setdefault(link.course, []).append(link.family_key)

    classes_by_major: dict[str, list[dict]] = {}
    unassigned: list[dict] = []
    for row in session.scalars(select(ClassRow).order_by(ClassRow.position, ClassRow.course)):
        if row.major_id is None:
            unassigned.append({"course": row.course, "reason": row.unassigned_reason or ""})
            continue
        entry: dict[str, Any] = {"course": row.course}
        _put(entry, "title", row.title)
        _put(entry, "credit_hours", row.credit_hours)
        entry["task_families"] = families_by_course.get(row.course, [])
        classes_by_major.setdefault(row.major_id, []).append(entry)

    majors = []
    for row in session.scalars(select(MajorRow).order_by(MajorRow.position, MajorRow.id)):
        major: dict[str, Any] = {
            "id": row.id,
            "name": row.name,
            "department": row.department,
            "subject_codes": list(row.subject_codes or []),
        }
        _put(major, "display_code", row.display_code)
        _put(major, "catalog", row.catalog)
        major["class_source"] = row.class_source
        major["classes"] = classes_by_major.get(row.id, [])
        majors.append(major)

    document = dict(meta.document)
    document["majors"] = majors
    document["unassigned_core"] = unassigned
    return document


# ──────────────────────────────────────────────────────────────── units ──


def units(session: Session) -> Units:
    """``{course: [Unit]}``: courses in code order, units by ``n``."""
    families: dict[str, list[str]] = {}
    for link in session.scalars(
        select(UnitFamilyRow).order_by(UnitFamilyRow.unit_id, UnitFamilyRow.position)
    ):
        families.setdefault(link.unit_id, []).append(link.family_key)
    # Course-code order. The served form (`ida_api.slo.units_view_from`) sorts
    # by course in BOTH modes, so neither the file's class order nor the
    # taxonomy's has to be reproduced here.
    rows = session.scalars(select(UnitRow).order_by(UnitRow.course, UnitRow.n))
    out: Units = {}
    for row in rows:
        out.setdefault(row.course, []).append(
            Unit(
                key=row.key,
                n=row.n,
                title=row.title,
                covers=list(row.covers or []),
                blurb=row.blurb or "",
                families=families.get(row.id, []),
                source=row.source,
                caveat=row.caveat,
            )
        )
    return out
