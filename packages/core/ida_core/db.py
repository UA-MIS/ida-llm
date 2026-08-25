"""Relational schema (SQLAlchemy 2.0) + session plumbing.

Two tables, deliberately.  ``runs`` is the queryable spine; ``results`` is the
grain the UI and the recommender read.  Anything large, append-only and never
joined on (transcripts, raw provider JSON, full eval logs) lives in object
storage and is referenced by URI -- see :mod:`ida_core.artifacts`.

Why JSON columns for ``serving_config``
---------------------------------------
D-1 requires the serving config to be captured **by value** on every result so
that later edits to ``models.yaml`` cannot rewrite history.  Normalising it into
a ``serving_configs`` table would reintroduce exactly the mutable-reference
problem we are avoiding.  The blob is the pydantic
:class:`~ida_core.contracts.ServingConfig` ``model_dump()`` and round-trips
losslessly.

Portability
-----------
Production is CloudNativePG (Postgres 16).  Tests run the identical schema on
SQLite, so we use ``sqlalchemy.JSON`` (which maps to ``JSONB`` on Postgres via
the dialect and to ``TEXT``-backed JSON on SQLite) and timezone-aware
``DateTime`` rather than any Postgres-only type.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ida_core.config import normalize_database_url


def utcnow() -> datetime:
    """Timezone-aware "now".  Never use naive datetimes in this codebase."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base.  ``Base.metadata`` is what Alembic autogenerates against."""


class RunRow(Base):
    """A run: one (task, model) pair of work.

    Maps 1:1 to :class:`ida_core.contracts.RunRecord`.  The id is minted by the
    API before the row exists so that the enqueue response and the queue message
    carry the same id.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(255))

    sweep_id: Mapped[str | None] = mapped_column(String(64), index=True)
    """Groups every run from one ``POST /runs`` (B9).  Indexed: the comparison
    view's primary query is ``WHERE sweep_id = ?``."""

    task_git_sha: Mapped[str | None] = mapped_column(String(64))
    """D-1: the git SHA of the task/rubric definitions in effect for this run."""

    task_content_sha: Mapped[str | None] = mapped_column(String(64), index=True)
    """SHA-256 of the task's canonicalised content (B8).  Indexed because
    "every run of *this exact task text*" is the comparability query."""

    harness_version: Mapped[str] = mapped_column(String(32), nullable=False)
    serving_config: Mapped[dict | None] = mapped_column(JSON)
    """D-1 payload, by value.  NULL only while the run is still ``queued``."""

    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scored_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Samples that failed outright (B5).  Disambiguates
    ``scored_count < sample_count`` between "calls failed" and "not scorable"."""

    mean_score: Mapped[float | None] = mapped_column(Float)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResultRow(Base):
    """One scored sample.  The citable unit behind every recommendation (D-3)."""

    __tablename__ = "results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sample_id: Mapped[str] = mapped_column(String(255), nullable=False)

    repeat_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Which repetition of this sample (B7).  0 for a single, non-repeated run.

    Part of the uniqueness constraint so repeated sampling -- self-consistency,
    pass@k, variance at temperature > 0 -- needs no schema change later.
    """

    model_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    serving_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    """D-1 payload, by value.  Never a foreign key -- see the module docstring."""

    judge_serving_config: Mapped[dict | None] = mapped_column(JSON)
    """The judge's D-1 payload, by value (B6).  NULL when nothing judged this.

    Its own column rather than a key inside ``score_details`` so that
    "every result graded by judge X" is an indexable query, not a JSON scan.
    """

    task_content_sha: Mapped[str | None] = mapped_column(String(64), index=True)
    """SHA-256 of the task's canonicalised content (B8)."""

    scorer: Mapped[str | None] = mapped_column(String(32))
    score_value: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column()
    score_explanation: Mapped[str | None] = mapped_column(Text)
    score_criteria: Mapped[list | None] = mapped_column(JSON)
    """Per-criterion rubric breakdown (B6).  NULL for programmatic scorers."""

    score_details: Mapped[dict | None] = mapped_column(JSON)

    scorable: Mapped[bool] = mapped_column(default=True, nullable=False)
    """False for ``subjective`` samples until the LLM judge lands."""

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    """Money spent producing THIS record.  0.0 on a cache hit (B4)."""

    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    """Wall-clock observed on THIS run.  0.0 on a cache hit (B4)."""

    cached: Mapped[bool] = mapped_column(default=False, nullable=False)
    """True when the completion was served from cache rather than the endpoint."""

    archive_error: Mapped[str | None] = mapped_column(Text)
    """Set when the transcript could not be archived but the sample succeeded."""

    transcript_uri: Mapped[str | None] = mapped_column(String(1024))
    """``s3://bucket/key`` -- the transcript bytes in MinIO.  See ida_core.artifacts."""

    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# Uniqueness is (run, sample, repetition) -- NOT (run, sample). One result per
# sample per run would make repeated sampling structurally impossible, and the
# solver seam exists precisely to enable it (B7).
Index(
    "ix_results_run_sample",
    ResultRow.run_id,
    ResultRow.sample_id,
    ResultRow.repeat_index,
    unique=True,
)
Index("ix_runs_task_model", RunRow.task_id, RunRow.model_key)


def make_engine(database_url: str, *, echo: bool = False):
    """Build an engine with the settings both services should use.

    ``pool_pre_ping`` matters in k8s: a database failover kills connections and
    we would otherwise serve a stale-socket 500 on the first request after.

    This is the SINGLE funnel for engine creation, which is why the DSN scheme is
    normalised here and nowhere else -- see
    :func:`ida_core.config.normalize_database_url` for the incident that makes it
    load-bearing. (``migrations/env.py`` is the one caller that does not come
    through here; it calls ``Settings.sqlalchemy_url()``, the same helper.)
    """
    database_url = normalize_database_url(database_url)
    kwargs: dict = {"echo": echo, "future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        # SQLite has no real pool; pre-ping is meaningless and check_same_thread
        # must be relaxed for the TestClient's thread pool.
        kwargs.pop("pool_pre_ping")
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


def make_session_factory(engine) -> sessionmaker[Session]:
    """Session factory.  ``expire_on_commit=False`` so returned rows stay readable."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine) -> None:
    """Create the schema directly, bypassing Alembic.

    Used by tests and by the local docker-compose bootstrap.  **Production uses
    Alembic** (``alembic upgrade head``) -- the baseline migration in
    ``ida_core/migrations/versions`` is kept byte-equivalent to this metadata.
    """
    Base.metadata.create_all(engine)
