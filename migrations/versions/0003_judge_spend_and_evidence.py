"""judge spend and judge evidence, accounted separately from the candidate model

The LLM-as-judge path (AB#5) buys TWO things per subjective sample: the answer
and the grade.  ``results`` already recorded the answer's tokens, cost and
transcript, and already recorded WHICH model graded
(``judge_serving_config``, added in 0002) -- but not what the grading cost, and
not where its reasoning went.

  results.judge_prompt_tokens      \\
  results.judge_completion_tokens   > what the judge consumed
  results.judge_cost_usd           /  priced at the JUDGE's rates
  results.judge_transcript_uri     the per-criterion judgments, in object storage

⚠ WHY NOT JUST ADD THEM TO ``cost_usd``.  Because the platform's whole output is
a comparison between models, and a cheap model graded by an expensive judge would
read as an expensive model -- irreversibly, since nothing downstream could split
the number again.  The judge is a constant of the *experiment*, not a property of
the model under test.  Keeping the two apart is what lets "what did this model
cost" and "what did grading cost" both be answerable, and it is the same
reasoning that gave ``judge_serving_config`` its own column rather than a corner
of ``score_details``.

Additive, all defaulted: an existing row is a row nothing judged, and zero is the
true answer for it rather than a placeholder.

⚠ THE DOWNGRADE DESTROYS DATA, AND THERE IS NO WAY FOR IT NOT TO. Dropping these
columns discards every judge spend figure and every judge-transcript pointer
recorded since the upgrade; a downgrade-then-upgrade round trip leaves them
reading (0, 0, 0.0, NULL). The evidence itself survives -- the JudgeTranscript
objects are in object storage under `runs/<id>/judge/` and are not touched -- but
the POINTERS to them do not, so a rollback means walking the bucket to find them
again. Rolling back past this revision on a database that has graded anything is
therefore a decision, not a formality. Export `results.judge_*` first if the
numbers matter.

Revision ID: ida_0003_judge_spend
Revises: ida_0002_failure_and_provenance
Create Date: 2026-08-25 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ida_0003_judge_spend"
down_revision: Union[str, None] = "ida_0002_failure_and_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default on the NOT NULL numerics so the ALTER succeeds against a
    # table that already has rows; the ORM default covers new inserts.
    op.add_column(
        "results",
        sa.Column("judge_prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "results",
        sa.Column("judge_completion_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "results",
        sa.Column("judge_cost_usd", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("results", sa.Column("judge_transcript_uri", sa.String(length=1024)))


def downgrade() -> None:
    op.drop_column("results", "judge_transcript_uri")
    op.drop_column("results", "judge_cost_usd")
    op.drop_column("results", "judge_completion_tokens")
    op.drop_column("results", "judge_prompt_tokens")
