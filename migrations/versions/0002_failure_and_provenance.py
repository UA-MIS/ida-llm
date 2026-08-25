"""error accounting, judge/task provenance, repeats, sweeps

Adds the columns required by review findings B5-B9. Written as a *second*
revision rather than an edit to the baseline, even though nothing has been
deployed yet, so that the upgrade path itself is exercised: a hand-written
baseline that has never been upgraded past is a migration nobody has tested.
``tests/test_migrations.py`` runs 0001 -> 0002 and asserts the result matches
``Base.metadata``, and runs the downgrade back to base.

  runs.error_count        B5  disambiguates "calls failed" from "not scorable"
  runs.sweep_id           B9  groups the runs from one POST /runs
  runs.task_content_sha   B8  per-task comparability key
  results.repeat_index    B7  + widened unique index, for repeated sampling
  results.judge_serving_config
                          B6  D-1 applied to the grade, not just the completion
  results.score_criteria  B6  per-criterion rubric breakdown
  results.task_content_sha B8
  results.cached          B4  cache provenance (latency/cost are 0 on a hit)
  results.archive_error   A5  transcript archival failed but the work survived

Revision ID: 0002_failure_and_provenance
Revises: 0001_baseline
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_failure_and_provenance"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- runs -------------------------------------------------------------
    # server_default on the NOT NULL counter so the ALTER succeeds against a
    # table that already has rows; the ORM default covers new inserts.
    op.add_column(
        "runs",
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("runs", sa.Column("sweep_id", sa.String(length=64), nullable=True))
    op.add_column(
        "runs", sa.Column("task_content_sha", sa.String(length=64), nullable=True)
    )
    op.create_index("ix_runs_sweep_id", "runs", ["sweep_id"])
    op.create_index("ix_runs_task_content_sha", "runs", ["task_content_sha"])

    # --- results ----------------------------------------------------------
    op.add_column(
        "results",
        sa.Column("repeat_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("results", sa.Column("judge_serving_config", sa.JSON(), nullable=True))
    op.add_column("results", sa.Column("score_criteria", sa.JSON(), nullable=True))
    op.add_column(
        "results", sa.Column("task_content_sha", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "results",
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("results", sa.Column("archive_error", sa.Text(), nullable=True))
    op.create_index("ix_results_task_content_sha", "results", ["task_content_sha"])

    # Widen uniqueness from (run, sample) to (run, sample, repeat) so repeated
    # sampling becomes possible without another migration.
    op.drop_index("ix_results_run_sample", table_name="results")
    op.create_index(
        "ix_results_run_sample",
        "results",
        ["run_id", "sample_id", "repeat_index"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_results_run_sample", table_name="results")
    op.create_index(
        "ix_results_run_sample", "results", ["run_id", "sample_id"], unique=True
    )
    op.drop_index("ix_results_task_content_sha", table_name="results")
    op.drop_column("results", "archive_error")
    op.drop_column("results", "cached")
    op.drop_column("results", "task_content_sha")
    op.drop_column("results", "score_criteria")
    op.drop_column("results", "judge_serving_config")
    op.drop_column("results", "repeat_index")

    op.drop_index("ix_runs_task_content_sha", table_name="runs")
    op.drop_index("ix_runs_sweep_id", table_name="runs")
    op.drop_column("runs", "task_content_sha")
    op.drop_column("runs", "sweep_id")
    op.drop_column("runs", "error_count")
