"""initial schema: runs + results

Revision ID: 0001
Revises:
Create Date: 2026-08-25

The two tables encode the project's one non-negotiable invariant: every result
cites the git SHA of the task suite and the model registry that produced it.
`tasks_sha` / `models_sha` are NOT NULL for that reason -- a result without its
citation is an anecdote, and allowing NULL would let one slip in silently.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("tasks_sha", sa.String(length=40), nullable=False),
        sa.Column("models_sha", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_runs_model_id", "runs", ["model_id"])

    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("transcript_key", sa.Text(), nullable=True),
    )
    op.create_index("ix_results_run_id", "results", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_results_run_id", table_name="results")
    op.drop_table("results")
    op.drop_index("ix_runs_model_id", table_name="runs")
    op.drop_table("runs")
