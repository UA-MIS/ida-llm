"""The admin-editable configuration, as tables (design section 3.1).

**After seeding, these rows -- not the git YAML -- are the source of truth**
wherever ``IDA_CONFIG_SOURCE=db``.  The YAML seeds a fresh database and drives
local dev and CI; ``/admin`` is the only writer after that.

Shape decisions worth knowing before editing:

* **A task is stored as its WHOLE canonical document** (``tasks.document``,
  AD-8).  ``content_sha`` hashes exactly that value, so a seeded task hashes the
  same as its YAML and no score moves.  Forms edit the document; the same
  validators run on it.
* **Both unit invariants are enforced by the database**, not only in code:
  ``UNIQUE(unit_families.family_key)`` (a family sits in at most one unit) and
  the composite FK ``(course, family_key) -> class_task_families`` (a unit's
  families are a subset of its class's).  See :class:`UnitFamilyRow`.
* **Nothing here ever holds plaintext key material.**  ``provider_credentials``
  carries AES-GCM ciphertext under a KEK that lives only in env.
* Portable types only (``JSON``, ``LargeBinary``), for the reason
  :mod:`ida_core.db` gives: the test suite runs this exact schema on SQLite.
  Identity columns are ``BIGINT`` on Postgres and ``INTEGER`` on SQLite, because
  SQLite autoincrements only an ``INTEGER PRIMARY KEY``.

Every mutable config row carries :class:`_Versioned`'s columns: ``version``
(optimistic concurrency -- the ``If-Match`` the console echoes back) and who
created/last changed it, when.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ida_core.db import Base, utcnow

Identity = BigInteger().with_variant(Integer(), "sqlite")
"""``BIGSERIAL`` on Postgres; ``INTEGER PRIMARY KEY`` (the only autoincrementing
form) on SQLite."""


class _Versioned:
    """The bookkeeping every mutable config row carries."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    created_by: Mapped[str | None] = mapped_column(String(64))
    updated_by: Mapped[str | None] = mapped_column(String(64))


class ConfigRevisionRow(Base):
    """Append-only.  ``max(id)`` is the revision every process polls (AD-9).

    Row 1 is always the seed; a table with any row means "seeded, ever", which
    is what stops a restarted pod from re-seeding over admin edits."""

    __tablename__ = "config_revisions"

    id: Mapped[int] = mapped_column(Identity, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    """``seed`` / ``admin`` / ``import``."""
    seed_git_sha: Mapped[str | None] = mapped_column(String(64))


class ModelFamilyRow(_Versioned, Base):
    __tablename__ = "model_families"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)


class ProviderCredentialRow(_Versioned, Base):
    """An admin-entered provider key, ENCRYPTED (AD-10).

    ⚠ NO PLAINTEXT, PREFIX, SUFFIX OR HASH OF THE KEY ANYWHERE.  A hash of a
    high-entropy key is not a leak in theory and is a lookup table in practice
    the day a provider key format turns out to be guessable; there is no feature
    that needs one."""

    __tablename__ = "provider_credentials"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    kek_id: Mapped[str] = mapped_column(String(16), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelRow(_Versioned, Base):
    """One registry entry.  Rebuilt into a ``ModelEntry`` through the same
    pydantic model ``models.yaml`` goes through."""

    __tablename__ = "models"
    __table_args__ = (
        CheckConstraint(
            "NOT (api_key_env IS NOT NULL AND credential_ref IS NOT NULL)",
            name="ck_models_one_key_source",
        ),
    )

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    family_key: Mapped[str | None] = mapped_column(String(128), ForeignKey("model_families.key"))
    display_order: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    """REGISTRY order -- the order ``GET /models`` lists models in.

    Not in the design's table, and needed for the parity guarantee: the public
    API lists models in ``models.yaml`` FILE order, which is not
    ``display_order`` order (``mock`` has none and comes first).  Seeded from
    file order (10, 20, ...); a new model is appended.  ``display_order`` stays
    what it always was: position on the public grids."""
    base_url: Mapped[str | None] = mapped_column(Text)
    base_url_env: Mapped[str | None] = mapped_column(String(128))
    api_key_env: Mapped[str | None] = mapped_column(String(128))
    credential_ref: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("provider_credentials.name")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    timeout_s: Mapped[float] = mapped_column(Float, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    serving: Mapped[dict] = mapped_column(JSON, nullable=False)
    """``ModelEntry.serving`` verbatim."""
    cost_input_usd_per_mtok: Mapped[float] = mapped_column(
        Numeric(12, 4, asdecimal=False), nullable=False, default=0.0
    )
    cost_output_usd_per_mtok: Mapped[float] = mapped_column(
        Numeric(12, 4, asdecimal=False), nullable=False, default=0.0
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Soft delete (AD-15): an archived model leaves the registry and its key is
    never reused, because ``runs.model_key`` is history."""


class TaskFamilyRow(_Versioned, Base):
    __tablename__ = "task_families"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    """The ``tasks/<family>/`` directory-name convention, and every task id's
    leading segment."""
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provenance: Mapped[str] = mapped_column(String(16), nullable=False, default="synthetic")
    """``synthetic`` / ``private``.  ``private`` material must never be exported
    to the public repo, and may not be set until ``GET /tasks/{id}`` is gated
    (PR B6)."""
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskRow(_Versioned, Base):
    __tablename__ = "tasks"
    __table_args__ = (CheckConstraint("id LIKE family_key || '/%'", name="ck_tasks_id_in_family"),)

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    family_key: Mapped[str] = mapped_column(
        String(128), ForeignKey("task_families.key"), nullable=False, index=True
    )
    document: Mapped[dict] = mapped_column(JSON, nullable=False)
    """The WHOLE task document, samples and ``system_prompt`` included, stored as
    ``json.loads(json.dumps(doc, default=str))`` -- which is exactly the value
    ``content_sha_of`` hashes (design 4.2)."""
    content_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    """``yaml_seed`` / ``form`` / ``upload``."""
    upload_object_key: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskRevisionRow(Base):
    """Every version of every task's text, forever.

    **This replaces git as the D-1 reproducibility record for DB-authored
    material**: any ``runs.task_content_sha`` resolves back to the exact
    document through ``content_sha``."""

    __tablename__ = "task_revisions"

    id: Mapped[int] = mapped_column(Identity, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content_sha: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    config_revision: Mapped[int | None] = mapped_column(BigInteger)


class MajorRow(_Versioned, Base):
    """Mirrors ``ida_core.majors.Major``."""

    __tablename__ = "majors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subject_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    display_code: Mapped[str | None] = mapped_column(String(32))
    catalog: Mapped[str | None] = mapped_column(Text)
    class_source: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ClassRow(_Versioned, Base):
    """A class a major owns -- or, with ``major_id`` NULL, an ``unassigned_core``
    course and the reason no major owns it."""

    __tablename__ = "classes"
    __table_args__ = (
        CheckConstraint(
            "(major_id IS NULL) <> (unassigned_reason IS NULL)",
            name="ck_classes_one_owner",
        ),
    )

    course: Mapped[str] = mapped_column(String(32), primary_key=True)
    major_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("majors.id"))
    unassigned_reason: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(255))
    credit_hours: Mapped[float | None] = mapped_column(Float)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ClassTaskFamilyRow(Base):
    """``MajorClass.task_families``: the families whose results are ABOUT a class."""

    __tablename__ = "class_task_families"

    course: Mapped[str] = mapped_column(
        String(32), ForeignKey("classes.course", ondelete="CASCADE"), primary_key=True
    )
    family_key: Mapped[str] = mapped_column(
        String(128), ForeignKey("task_families.key"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UnitRow(_Versioned, Base):
    """One unit of one class (AD-11) -- the class page's column."""

    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("course", "key", name="uq_units_course_key"),
        UniqueConstraint("course", "n", name="uq_units_course_n"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    course: Mapped[str] = mapped_column(
        String(32), ForeignKey("classes.course", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    covers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blurb: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str | None] = mapped_column(Text)
    caveat: Mapped[str | None] = mapped_column(Text)


class UnitFamilyRow(Base):
    """A family assigned to a unit.  BOTH unit invariants live here:

    1. ``UNIQUE(family_key)`` -- a family sits in at most one unit, so one
       family's score can never be printed under two unit headings.
    2. FK ``(course, family_key) -> class_task_families`` -- a unit can only
       hold families its class already owns.  ``course`` is denormalised from
       ``units.course`` for exactly this purpose; the admin service sets it and
       checks it.  Removing a family from a class that a unit still claims is
       an FK violation, which the API reports as 409 naming the unit.
    """

    __tablename__ = "unit_families"
    __table_args__ = (
        UniqueConstraint("family_key", name="uq_unit_families_family"),
        ForeignKeyConstraint(
            ["course", "family_key"],
            ["class_task_families.course", "class_task_families.family_key"],
            name="fk_unit_families_class_family",
        ),
    )

    unit_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("units.id", ondelete="CASCADE"), primary_key=True
    )
    course: Mapped[str] = mapped_column(String(32), nullable=False)
    family_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CurriculumDocumentRow(_Versioned, Base):
    """Whole documents edited as validated YAML.

    ``slo``         the entire ``curriculum/slo.yaml`` (outcomes, use modes,
                    coverage).
    ``majors_meta`` the top-level keys of ``majors.yaml`` (institution,
                    college, degree, source, source_title, retrieved).
    """

    __tablename__ = "curriculum_documents"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    document: Mapped[dict] = mapped_column(JSON, nullable=False)


class AuditLogRow(Base):
    """Append-only.  No API endpoint updates or deletes a row.

    Credential rows are logged as metadata only; task ``before``/``after`` are a
    summary plus the ``task_revisions`` id, never the document."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Identity, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    actor_login: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_sub: Mapped[str | None] = mapped_column(String(255))
    via_subject: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    config_revision: Mapped[int | None] = mapped_column(BigInteger)
    request_id: Mapped[str | None] = mapped_column(String(64))


Index(
    "ix_audit_log_entity",
    AuditLogRow.entity_type,
    AuditLogRow.entity_id,
    AuditLogRow.at,
)
