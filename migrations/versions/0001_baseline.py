"""baseline: runs + results

The initial schema.  Kept byte-equivalent to ``ida_core.db.Base.metadata`` --
``tests/test_migrations.py`` asserts that ``alembic upgrade head`` and
``Base.metadata.create_all`` produce the same tables, columns and indexes, so
the two can never drift silently.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-01-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("task_git_sha", sa.String(length=64), nullable=True),
        sa.Column("harness_version", sa.String(length=32), nullable=False),
        sa.Column("serving_config", sa.JSON(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("scored_count", sa.Integer(), nullable=False),
        sa.Column("mean_score", sa.Float(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_cost_usd", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_created_at", "runs", ["created_at"])
    op.create_index("ix_runs_model_key", "runs", ["model_key"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_task_id", "runs", ["task_id"])
    op.create_index("ix_runs_task_model", "runs", ["task_id", "model_key"])

    op.create_table(
        "results",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("sample_id", sa.String(length=255), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("serving_config", sa.JSON(), nullable=False),
        sa.Column("scorer", sa.String(length=32), nullable=True),
        sa.Column("score_value", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("score_explanation", sa.Text(), nullable=True),
        sa.Column("score_details", sa.JSON(), nullable=True),
        sa.Column("scorable", sa.Boolean(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("transcript_uri", sa.String(length=1024), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_results_model_key", "results", ["model_key"])
    op.create_index("ix_results_run_id", "results", ["run_id"])
    op.create_index("ix_results_task_id", "results", ["task_id"])
    op.create_index("ix_results_run_sample", "results", ["run_id", "sample_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_results_run_sample", table_name="results")
    op.drop_index("ix_results_task_id", table_name="results")
    op.drop_index("ix_results_run_id", table_name="results")
    op.drop_index("ix_results_model_key", table_name="results")
    op.drop_table("results")
    op.drop_index("ix_runs_task_model", table_name="runs")
    op.drop_index("ix_runs_task_id", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_model_key", table_name="runs")
    op.drop_index("ix_runs_created_at", table_name="runs")
    op.drop_table("runs")
