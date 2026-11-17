"""``ensure_seeded``: the git YAML -> the configuration tables, once, ever (AD-7).

WHEN IT RUNS.  At api, runner and sweep start, through
``ida_harness.config_provider.build_provider``, and only when
``IDA_CONFIG_SOURCE=db``.  NOT in a migration: the migrate initContainer gets
only ``DATABASE_URL`` and cannot see the per-environment overrides
(``IDA_MODELS_FILE``, ``IDA_TASKS_DIR``, ``IDA_MAJORS_FILE``, ``IDA_UNITS_FILE``
...) that decide WHICH YAML an environment uses.  Reading them here, through the
SAME resolvers the YAML path uses, is what makes dev seed dev's demo content and
prod seed prod's -- and why dev demo data can never reach a prod database.

ONCE, EVER.  If ``config_revisions`` has any row, this returns without reading a
file: after seeding, ``/admin`` is the authority, and a restarted pod must never
overwrite an admin's edits with the image's YAML.

SERIALISED.  Every api/runner/sweep pod may start at once.  On Postgres a
transaction-scoped advisory lock (``pg_advisory_xact_lock(0x1DA11A)``) makes one
of them the seeder; the others block on the lock, then see the revision row and
return.  SQLite (tests) has no advisory locks, so an in-process lock stands in.

LOUD.  The YAML runs through the shared validation suite first; any ``error``
raises :class:`SeedError` and the pod fails readiness, rather than seeding a
config the CI gate would have rejected.  Every task's stored document is
re-hashed and must reproduce the YAML's ``content_sha`` exactly, or the seed
aborts -- a drifted hash would quietly re-enqueue every pair and detach every
historical score from its task text.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from ida_core.config import Settings, repo_root
from ida_core.configdb.reader import MAJORS_META_DOCUMENT, SLO_DOCUMENT, is_seeded
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
    TaskRevisionRow,
    TaskRow,
    UnitFamilyRow,
    UnitRow,
)
from ida_core.contracts import ModelRegistry, TaskSpec
from ida_core.curriculum import default_curriculum_path
from ida_core.db import session_scope
from ida_core.gitmeta import current_git_sha
from ida_core.ids import new_id
from ida_core.majors import default_majors_path
from ida_core.units import Units, load_units
from ida_core.validation import discover_task_files, load_yaml
from ida_core.validation_suite import (
    Issue,
    errors_of,
    parse_curriculum,
    parse_majors,
    task_family_of,
    validate_curriculum,
    validate_models,
    validate_task,
    validate_units,
)

log = logging.getLogger(__name__)

SEED_LOCK_KEY = 0x1DA11A
"""The advisory-lock key every seeder contends on. Arbitrary, fixed, and named
once so two code paths can never pick different keys."""

SEED_ACTOR = "system:seed"

_SQLITE_SEED_LOCK = threading.Lock()


class SeedError(RuntimeError):
    """The YAML cannot be seeded as written.  Carries the issues found."""

    def __init__(self, message: str, issues: list[Issue] | None = None) -> None:
        self.issues = issues or []
        detail = "".join(f"\n  - {i.path}: {i.message}" for i in self.issues[:50])
        super().__init__(message + detail)


def normalise_document(document: Any) -> Any:
    """``json.loads(json.dumps(doc, default=str))`` -- the stored form.

    Exactly the value ``content_sha_of`` hashes (dates become their ISO strings,
    key order stops mattering, floats round-trip), so a stored task re-hashes to
    the YAML's ``content_sha`` by construction.  The seeder still checks."""
    return json.loads(json.dumps(document, default=str))


@dataclass
class ConfigSources:
    """Everything a seed (or an import) writes, already parsed from YAML."""

    models_document: dict
    task_documents: list[tuple[str, dict]]
    """``[(task_id, raw YAML document)]``, in discovery order."""
    slo_document: dict | None
    majors_document: dict | None
    units: Units
    git_sha: str | None = None
    origin: dict[str, str] = field(default_factory=dict)
    """Which file each part came from -- logged, so "what did dev seed from?"
    has an answer in the pod log."""


def read_yaml_sources(settings: Settings, *, tasks_dir: Path | None = None) -> ConfigSources:
    """Read the YAML this environment would serve in yaml mode -- through the
    SAME resolvers (``resolved_models_file`` ...), so dev's overrides apply."""
    root = repo_root()
    models_file = settings.resolved_models_file()
    tasks_root = tasks_dir or settings.resolved_tasks_dir()
    slo_file = settings.resolved_curriculum_file() or default_curriculum_path(root)
    majors_file = settings.resolved_majors_file() or default_majors_path(root)
    units_file = settings.resolved_units_file()

    task_documents = []
    for path in discover_task_files(tasks_root):
        document = load_yaml(path)
        task_id = document.get("id") if isinstance(document, dict) else None
        task_documents.append((str(task_id or path), document))
    return ConfigSources(
        models_document=load_yaml(models_file),
        task_documents=task_documents,
        slo_document=load_yaml(slo_file) if Path(slo_file).is_file() else None,
        majors_document=load_yaml(majors_file) if Path(majors_file).is_file() else None,
        units=load_units(units_file),
        git_sha=current_git_sha(tasks_root),
        origin={
            "models": str(models_file),
            "tasks": str(tasks_root),
            "slo": str(slo_file),
            "majors": str(majors_file),
            "units": str(units_file),
        },
    )


def validate_sources(sources: ConfigSources) -> list[Issue]:
    """The shared suite over the whole source set -- what the CI gate checks."""
    issues = [
        Issue(f"models.{i.path}", i.message, i.severity)
        for i in validate_models(sources.models_document)
    ]
    families = {task_family_of(task_id) for task_id, _ in sources.task_documents}
    curriculum = None
    if sources.slo_document is not None:
        _, curriculum = parse_curriculum(sources.slo_document)
        issues += validate_curriculum(sources.slo_document, sources.majors_document, families)
    seen: set[str] = set()
    for task_id, document in sources.task_documents:
        task_issues, _ = validate_task(document, curriculum=curriculum, families=families)
        issues += [Issue(f"tasks[{task_id}].{i.path}", i.message, i.severity) for i in task_issues]
        if task_id in seen:
            issues.append(Issue(f"tasks[{task_id}]", "duplicate task id"))
        seen.add(task_id)
    majors = None
    if sources.majors_document is not None:
        _, majors = parse_majors(sources.majors_document)
    issues += validate_units(sources.units, majors)
    return issues


def _bookkeeping(actor: str) -> dict:
    return {"created_by": actor, "updated_by": actor}


def write_sources(session: Session, sources: ConfigSources, *, actor: str) -> dict[str, int]:
    """Insert every config row from ``sources``.  Assumes empty tables.

    Returns counts for the log line and the audit row.  Raises
    :class:`SeedError` on a ``content_sha`` mismatch -- before anything is
    committed, because the caller's transaction rolls back."""
    who = _bookkeeping(actor)
    registry = ModelRegistry.model_validate(sources.models_document)

    # ── model families + models, in FILE order (`position`) ────────────────
    families: dict[str, str] = {}
    for entry in registry.models:
        if entry.family is None:
            if entry.family_display_name is not None:
                raise SeedError(f"model {entry.key!r} has family_display_name but no family")
            continue
        name = entry.family_display_name
        if name is None:
            raise SeedError(
                f"model {entry.key!r} has family {entry.family!r} but no family_display_name; "
                "the database stores the name once per family"
            )
        if families.setdefault(entry.family, name) != name:
            raise SeedError(
                f"family {entry.family!r} has two display names: "
                f"{families[entry.family]!r} and {name!r}"
            )
    for key, name in families.items():
        session.add(ModelFamilyRow(key=key, display_name=name, **who))
    session.flush()
    for position, entry in enumerate(registry.models, start=1):
        session.add(
            ModelRow(
                key=entry.key,
                display_name=entry.display_name,
                family_key=entry.family,
                display_order=entry.display_order,
                position=position * 10,
                base_url=entry.base_url,
                base_url_env=entry.base_url_env,
                api_key_env=entry.api_key_env,
                credential_ref=entry.credential_ref,
                enabled=entry.enabled,
                hidden=entry.hidden,
                timeout_s=entry.timeout_s,
                max_retries=entry.max_retries,
                tags=list(entry.tags),
                serving=entry.serving.model_dump(mode="json"),
                cost_input_usd_per_mtok=entry.cost.input_usd_per_mtok,
                cost_output_usd_per_mtok=entry.cost.output_usd_per_mtok,
                **who,
            )
        )

    # ── task families + tasks (+ a revision per task) ─────────────────────
    family_keys = sorted({task_family_of(task_id) for task_id, _ in sources.task_documents})
    for key in family_keys:
        # Families have no title in the file tree; the key is the honest
        # placeholder until an admin names it.
        session.add(
            TaskFamilyRow(key=key, title=key, description="", provenance="synthetic", **who)
        )
    session.flush()
    for task_id, raw in sources.task_documents:
        stored = normalise_document(raw)
        expected = TaskSpec.from_document(raw).content_sha
        spec = TaskSpec.from_document(stored)
        if spec.content_sha != expected:
            raise SeedError(
                f"task {task_id!r}: the stored document hashes to {spec.content_sha}, "
                f"the YAML to {expected}; seeding it would detach its scores"
            )
        session.add(
            TaskRow(
                id=spec.id,
                family_key=task_family_of(spec.id),
                document=stored,
                content_sha=spec.content_sha,
                title=spec.title,
                kind=spec.kind.value,
                sample_count=len(spec.samples),
                source="yaml_seed",
                **who,
            )
        )
        session.add(
            TaskRevisionRow(
                task_id=spec.id, content_sha=spec.content_sha, document=stored, actor=actor
            )
        )
    session.flush()

    # ── curriculum documents, majors, classes ──────────────────────────────
    if sources.slo_document is not None:
        session.add(
            CurriculumDocumentRow(
                name=SLO_DOCUMENT, document=normalise_document(sources.slo_document), **who
            )
        )
    class_count = 0
    if sources.majors_document is not None:
        doc = normalise_document(sources.majors_document)
        meta = {k: v for k, v in doc.items() if k not in ("majors", "unassigned_core")}
        session.add(CurriculumDocumentRow(name=MAJORS_META_DOCUMENT, document=meta, **who))
        position = 0
        for major_position, major in enumerate(doc.get("majors") or []):
            session.add(
                MajorRow(
                    id=major["id"],
                    name=major["name"],
                    department=major.get("department", ""),
                    subject_codes=list(major.get("subject_codes") or []),
                    display_code=major.get("display_code"),
                    catalog=major.get("catalog"),
                    class_source=major["class_source"],
                    position=major_position,
                    **who,
                )
            )
            session.flush()
            for entry in major.get("classes") or []:
                position += 1
                class_count += 1
                session.add(
                    ClassRow(
                        course=entry["course"],
                        major_id=major["id"],
                        title=entry.get("title"),
                        credit_hours=entry.get("credit_hours"),
                        position=position,
                        **who,
                    )
                )
                session.flush()
                for family_position, family in enumerate(entry.get("task_families") or []):
                    session.add(
                        ClassTaskFamilyRow(
                            course=entry["course"], family_key=family, position=family_position
                        )
                    )
        for row in doc.get("unassigned_core") or []:
            position += 1
            class_count += 1
            session.add(
                ClassRow(
                    course=row["course"],
                    major_id=None,
                    unassigned_reason=row.get("reason") or "",
                    position=position,
                    **who,
                )
            )
        session.flush()

    # ── units ──────────────────────────────────────────────────────────────
    unit_count = 0
    for course, units in sources.units.items():
        for unit in units:
            unit_id = new_id("unit")
            unit_count += 1
            session.add(
                UnitRow(
                    id=unit_id,
                    course=course,
                    key=unit.key,
                    n=unit.n,
                    title=unit.title,
                    covers=list(unit.covers),
                    blurb=unit.blurb,
                    source=unit.source,
                    caveat=unit.caveat,
                    **who,
                )
            )
            session.flush()
            for family_position, family in enumerate(unit.families):
                session.add(
                    UnitFamilyRow(
                        unit_id=unit_id, course=course, family_key=family, position=family_position
                    )
                )
    session.flush()
    return {
        "models": len(registry.models),
        "model_families": len(families),
        "task_families": len(family_keys),
        "tasks": len(sources.task_documents),
        "classes": class_count,
        "units": unit_count,
    }


def _acquire_seed_lock(session: Session) -> threading.Lock | None:
    """Serialise seeders: a Postgres advisory lock held until this transaction
    ends, or -- on SQLite, which has none -- an in-process lock the caller
    releases."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SEED_LOCK_KEY})
        return None
    _SQLITE_SEED_LOCK.acquire()
    return _SQLITE_SEED_LOCK


def record_revision(
    session: Session,
    *,
    actor: str,
    source: str,
    summary: str,
    seed_git_sha: str | None = None,
) -> int:
    """Append a ``config_revisions`` row and return its id."""
    row = ConfigRevisionRow(actor=actor, source=source, summary=summary, seed_git_sha=seed_git_sha)
    session.add(row)
    session.flush()
    return int(row.id)


def ensure_seeded(
    settings: Settings,
    session_factory: sessionmaker[Session],
    *,
    sources: ConfigSources | None = None,
) -> bool:
    """Seed the configuration tables from YAML if they have never been seeded.

    Returns ``True`` if THIS call seeded, ``False`` if there was nothing to do
    (yaml mode, or already seeded -- by an earlier boot or a racing pod).
    ``sources`` is injectable for tests; production reads the YAML."""
    if settings.config_source != "db":
        return False
    with session_scope(session_factory) as session:
        held = _acquire_seed_lock(session)
        try:
            if is_seeded(session):
                return False
            sources = sources or read_yaml_sources(settings)
            issues = validate_sources(sources)
            errors = errors_of(issues)
            if errors:
                raise SeedError(
                    f"refusing to seed: the YAML has {len(errors)} validation error(s)", errors
                )
            counts = write_sources(session, sources, actor=SEED_ACTOR)
            revision = record_revision(
                session,
                actor=SEED_ACTOR,
                source="seed",
                summary="seeded from YAML: " + ", ".join(f"{v} {k}" for k, v in counts.items()),
                seed_git_sha=sources.git_sha,
            )
            session.add(
                AuditLogRow(
                    actor_login=SEED_ACTOR,
                    via_subject="system",
                    action="config.seed",
                    entity_type="config",
                    entity_id=str(revision),
                    after={"counts": counts, "origin": sources.origin},
                    config_revision=revision,
                )
            )
            log.info(
                "config: seeded revision %d from YAML (%s) -- origin %s",
                revision,
                counts,
                sources.origin,
            )
            return True
        finally:
            if held is not None:
                held.release()
