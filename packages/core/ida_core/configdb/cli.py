"""``python -m ida_core.configdb``: compare, import and (later) re-key the config DB.

    python -m ida_core.configdb diff            # YAML vs database; exit 1 on any difference
    python -m ida_core.configdb import <dir>    # DEV/TEST ONLY: replace the config with <dir>'s YAML

``diff`` is the parity gate (design 4.3).  Run it right after the first
``IDA_CONFIG_SOURCE=db`` deploy in each environment: it reads the YAML this
environment would serve in yaml mode (through the same ``IDA_*_FILE``
resolvers) and the live tables, and compares them STRUCTURALLY -- every
registry entry as parsed, every task's ``content_sha``, the curriculum map, the
majors taxonomy and the units.  Empty means the database serves exactly what
the YAML did.  After admins start editing, a non-empty diff is expected and is
the list of what they changed.

Only core is needed: the comparison is over the same pydantic objects both
config paths build, without a ``TaskCatalog``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ida_core.config import Settings, get_settings
from ida_core.configdb import reader
from ida_core.configdb.seed import (
    ConfigSources,
    SeedError,
    read_yaml_sources,
    record_revision,
    validate_sources,
    write_sources,
)
from ida_core.configdb.tables import (
    AuditLogRow,
    ClassRow,
    ClassTaskFamilyRow,
    ConfigRevisionRow,
    CurriculumDocumentRow,
    MajorRow,
    ModelFamilyRow,
    ModelRow,
    TaskFamilyRow,
    TaskRow,
    UnitFamilyRow,
    UnitRow,
)
from ida_core.contracts import ModelRegistry, TaskSpec
from ida_core.curriculum import CurriculumMap
from ida_core.db import make_engine, make_session_factory, session_scope
from ida_core.majors import Majors
from ida_core.units import Units
from ida_core.validation_suite import errors_of

# ──────────────────────────────────────────────────────────────── diff ──


@dataclass(frozen=True)
class ParsedConfig:
    """The comparable core of a configuration, however it was stored."""

    registry: dict[str, dict]
    registry_order: list[str]
    task_shas: dict[str, str]
    curriculum: dict | None
    majors: dict | None
    units: dict[str, list[dict]]


def _units_dump(units: Units) -> dict[str, list[dict]]:
    return {course: [u.model_dump() for u in rows] for course, rows in units.items() if rows}


def parse_config(
    models_document: dict,
    task_documents: list[tuple[str, dict]],
    slo_document: dict | None,
    majors_document: dict | None,
    units: Units,
) -> ParsedConfig:
    registry = ModelRegistry.model_validate(models_document)
    return ParsedConfig(
        registry={m.key: m.model_dump(mode="json") for m in registry.models},
        registry_order=[m.key for m in registry.models],
        task_shas={
            spec.id: spec.content_sha
            for spec in (TaskSpec.from_document(doc) for _, doc in task_documents)
        },
        curriculum=(
            CurriculumMap.model_validate(slo_document).model_dump(mode="json")
            if slo_document is not None
            else None
        ),
        majors=(
            Majors.model_validate(majors_document).model_dump(mode="json")
            if majors_document is not None
            else None
        ),
        units=_units_dump(units),
    )


def parse_sources(sources: ConfigSources) -> ParsedConfig:
    return parse_config(
        sources.models_document,
        sources.task_documents,
        sources.slo_document,
        sources.majors_document,
        sources.units,
    )


def parse_database(session: Session) -> ParsedConfig:
    return parse_config(
        reader.models_document(session),
        reader.task_documents(session),
        reader.slo_document(session),
        reader.majors_document(session),
        reader.units(session),
    )


def _diff_value(path: str, left: Any, right: Any, out: list[str]) -> None:
    """Walk two JSON-like values and record each differing leaf (capped)."""
    if len(out) >= 200:
        return
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right), key=str):
            if key not in left:
                out.append(f"{path}.{key}: only in database")
            elif key not in right:
                out.append(f"{path}.{key}: only in YAML")
            else:
                _diff_value(f"{path}.{key}", left[key], right[key], out)
    elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            _diff_value(f"{path}[{index}]", a, b, out)
    elif left != right:
        out.append(f"{path}: YAML {left!r} != database {right!r}")


def diff_configs(yaml_side: ParsedConfig, db_side: ParsedConfig) -> list[str]:
    """Every structural difference, as readable lines.  Empty means parity."""
    out: list[str] = []
    _diff_value("models", yaml_side.registry, db_side.registry, out)
    if yaml_side.registry_order != db_side.registry_order and set(yaml_side.registry) == set(
        db_side.registry
    ):
        out.append("models: registry ORDER differs (GET /models lists in this order)")
    for task_id in sorted(set(yaml_side.task_shas) | set(db_side.task_shas)):
        a, b = yaml_side.task_shas.get(task_id), db_side.task_shas.get(task_id)
        if a is None:
            out.append(f"tasks.{task_id}: only in database")
        elif b is None:
            out.append(f"tasks.{task_id}: only in YAML")
        elif a != b:
            out.append(f"tasks.{task_id}: content_sha YAML {a} != database {b}")
    _diff_value("curriculum", yaml_side.curriculum, db_side.curriculum, out)
    _diff_value("majors", yaml_side.majors, db_side.majors, out)
    _diff_value("units", yaml_side.units, db_side.units, out)
    return out


def run_diff(settings: Settings, session_factory) -> list[str]:
    yaml_side = parse_sources(read_yaml_sources(settings))
    with session_scope(session_factory) as session:
        if not reader.is_seeded(session):
            return ["database: not seeded (config_revisions is empty)"]
        db_side = parse_database(session)
    return diff_configs(yaml_side, db_side)


# ────────────────────────────────────────────────────────────── import ──

# Children before parents. Append-only history (config_revisions, audit_log,
# task_revisions) is NEVER deleted: an import is one more revision, not a
# rewrite of the past.
_REPLACED_TABLES = (
    UnitFamilyRow,
    UnitRow,
    ClassTaskFamilyRow,
    ClassRow,
    MajorRow,
    CurriculumDocumentRow,
    TaskRow,
    TaskFamilyRow,
    ModelRow,
    ModelFamilyRow,
)


def settings_for_directory(settings: Settings, root: Path) -> Settings:
    """``settings`` with every config file pointed under ``root``."""
    return settings.model_copy(
        update={
            "models_file": str(root / "models.yaml"),
            "tasks_dir": str(root / "tasks"),
            "curriculum_file": str(root / "curriculum" / "slo.yaml"),
            "majors_file": str(root / "curriculum" / "majors.yaml"),
            "units_file": str(root / "curriculum" / "units.yaml"),
        }
    )


def import_directory(
    settings: Settings, session_factory, root: Path, *, force: bool = False, actor: str = "cli"
) -> int:
    """Replace the live config with ``root``'s YAML.  DEV AND TESTS ONLY.

    Refuses when any revision came from ``/admin`` unless ``force`` -- an import
    over admin edits silently discards a person's work.  Credentials are kept
    (models that referenced one must still name it)."""
    sources = read_yaml_sources(settings_for_directory(settings, root))
    errors = errors_of(validate_sources(sources))
    if errors:
        raise SeedError(f"refusing to import {root}: {len(errors)} validation error(s)", errors)
    with session_scope(session_factory) as session:
        admin_edits = session.scalar(
            select(ConfigRevisionRow.id).where(ConfigRevisionRow.source == "admin").limit(1)
        )
        if admin_edits is not None and not force:
            raise SeedError(
                "refusing to import: this database has admin edits (config_revisions with "
                "source='admin'); pass --force to discard them"
            )
        for table in _REPLACED_TABLES:
            session.execute(delete(table))
        session.flush()
        counts = write_sources(session, sources, actor=actor)
        revision = record_revision(
            session, actor=actor, source="import", summary=f"imported {root}: {counts}"
        )
        session.add(
            AuditLogRow(
                actor_login=actor,
                via_subject="cli",
                action="config.import",
                entity_type="config",
                entity_id=str(revision),
                after={"counts": counts, "root": str(root)},
                config_revision=revision,
            )
        )
        return revision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ida_core.configdb", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("diff", help="compare the YAML with the database; exit 1 on any difference")
    imp = sub.add_parser("import", help="DEV/TEST ONLY: replace the config with a directory")
    imp.add_argument("root", type=Path, help="a repo-shaped directory (models.yaml, tasks/, ...)")
    imp.add_argument("--force", action="store_true", help="discard admin edits")
    args = parser.parse_args(argv)

    settings = get_settings()
    session_factory = make_session_factory(make_engine(settings.database_url))
    if args.command == "diff":
        differences = run_diff(settings, session_factory)
        for line in differences:
            print(line)
        if differences:
            print(f"\n{len(differences)} difference(s) between the YAML and the database")
            return 1
        print("no differences: the database serves exactly what the YAML does")
        return 0
    try:
        revision = import_directory(settings, session_factory, args.root, force=args.force)
    except SeedError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"imported {args.root} as config revision {revision}")
    return 0
