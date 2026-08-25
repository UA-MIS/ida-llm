"""ORM models -- the schema Alembic migrates.

SCAFFOLDING, but not arbitrary: the two tables below encode the ONE invariant the
project brief calls non-negotiable -- every result cites the git SHA of the task
and rubric that produced it, plus the model id from models.yaml. Keep those
columns when you reshape the rest.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One benchmark run: a model evaluated over a task suite at a point in time."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # THE reproducibility citation. Without this a result is an anecdote.
    tasks_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    models_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    results: Mapped[list[Result]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Result(Base):
    """One task's outcome inside a run."""

    __tablename__ = "results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_version: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # The transcript itself lives in MinIO, not Postgres -- rows stay small and
    # the artifact bucket carries the bulk. This is the object key.
    transcript_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship(back_populates="results")
