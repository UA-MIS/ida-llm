"""add results.judge_attempts -- the bound on retroactive judge retries

``docs/llm-judge.md`` partitions every subjective sample into four states, one of
which -- **judge failed** -- is retryable *by design*.  That is the point of
retroactive grading: a judge outage must not make a sample permanently
ungradable.  It is also, without a counter, a money pump.  The nightly
judge-calibration sweep nominates the failed sample, the still-down judge fails
it again, and the loop repeats every night at judge cost with no terminating
condition and no symptom except the invoice.

⚠ NOTHING ALREADY IN THE SCHEMA COULD COUNT ATTEMPTS.  This is why a migration
rather than a query:

* ``judge_transcript_uri`` and ``judge_prompt_tokens`` record *that* a judge was
  asked.  They are booleans wearing other clothes; they do not increment.
* ``judge_cost_usd`` looks like the obvious candidate and is the trap.  It holds
  the **last** attempt's spend -- ``regrade_run`` overwrites it on every retry --
  not a running total, so a sample retried ten times reports the cost of the
  tenth.  Summing it across attempts is impossible after the fact because the
  earlier values are gone.
* ``results.created_at`` supports a cooling-off window but not a cap: a window
  slows the money pump down, it does not stop it.

So the count is persisted.  ``docs/llm-judge.md`` named this exact column --
``results.judge_attempts INTEGER NOT NULL DEFAULT 0`` -- as the additive
migration to make when a sweep needed to bound itself.  A sweep now does.

⚠ ``server_default`` IS LOAD-BEARING, NOT DECORATION.  Adding a NOT NULL column
to a populated table needs a value for the rows already there, and it must come
from the database: an ORM-side ``default=0`` runs in Python on insert and does
nothing for rows that already exist, so ``ALTER TABLE ... ADD COLUMN ... NOT
NULL`` without a server default fails outright on Postgres.  The backfill value
is ``0``, which is also the honest one -- a row written before this migration
was graded at most once and by the online path, and treating it as un-attempted
means the first nightly pass gets to retry it, which is the behaviour the
retryable class is supposed to have.

The counter is deliberately *not* reset when a grade finally succeeds.  A graded
row is excluded from nomination by ``score_value IS NOT NULL`` long before the
bound is read, so zeroing it would buy nothing and would destroy the answer to
"how many attempts did this grade take", which is exactly the number a
calibration study wants when the judge is flaky.

Revision ID: ida_0005_judge_attempts
Revises: ida_0004_harness_build_identity
Create Date: 2026-08-27 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ida_0005_judge_attempts"
down_revision: Union[str, None] = "ida_0004_harness_build_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table for the same reason 0004 uses it: ONE migration has to
    # run against both the CI SQLite suite and the CloudNativePG production
    # database, or `alembic upgrade head` is untested until it runs for real.
    # (A bare ADD COLUMN is in fact within SQLite's ALTER support, but keeping
    # the idiom uniform means the next migration that ISN'T does not have to
    # rediscover it.)
    with op.batch_alter_table("results") as batch_op:
        batch_op.add_column(
            sa.Column(
                "judge_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    # Dropping this loses the attempt history and, with it, the bound. A
    # deployment rolled back past this revision re-acquires the unbounded-retry
    # behaviour -- which is why the sweep reads the bound from settings and
    # treats a missing column as a hard error rather than degrading quietly.
    with op.batch_alter_table("results") as batch_op:
        batch_op.drop_column("judge_attempts")
