"""widen runs.harness_version so it can hold the build's git SHA

``harness_version`` is documented as "the version that executed the run" and is
written onto EVERY run row, so under D-1 it has one job: let a reader fetch the
code that produced the number.  It could not do that job.  It carried
``ida_harness.__version__`` -- a hardcoded ``"0.1.0"`` that no release step has
ever written to -- so a row from the 0.1.1 image and a row from an unreleased
branch were byte-identical.  It did not identify a build; it identified the day
someone typed the constant, and it *looked* like provenance while doing it.

It now carries what ``ida_core.gitmeta.build_identity()`` returns: the git SHA
baked into the image at build time (``IDA_GIT_SHA``), shape-checked by
``is_sha`` so an unsubstituted ``$GITHUB_SHA`` or a literal ``HEAD`` can never be
stored as though it were provenance, and the honest string ``"unknown"`` when the
build genuinely cannot be identified.

⚠ WHY A MIGRATION AT ALL: A 40-CHARACTER SHA DOES NOT FIT IN VARCHAR(32).
That is the whole change.  ``"0.1.0"`` fit in anything; a SHA does not.  64
matches ``runs.task_git_sha``, which holds the same kind of value -- a reader
comparing the two columns should not have to wonder whether one was truncated.
On Postgres an under-width column would have rejected the insert outright; on
SQLite (tests, `make dev`) VARCHAR lengths are not enforced, so without this the
divergence would have surfaced only in production.

⚠ EXISTING ROWS ARE NOT REWRITTEN, DELIBERATELY.  Every row already in the table
says ``"0.1.0"``, and nobody can know today which build actually produced it --
inventing one would replace a visible lie with an invisible one.  They keep the
value they were written with; only new runs get a truthful answer.  A reader
distinguishes the two eras by shape: pre-migration rows are version-shaped,
post-migration rows are a 40-hex SHA or ``"unknown"``.

⚠ THE DOWNGRADE CAN FAIL, AND FAILING IS THE CORRECT BEHAVIOUR.  Narrowing back
to VARCHAR(32) on a Postgres table that has recorded any SHA raises
``value too long for type character varying(32)``.  There is no safe automatic
answer: silently truncating a SHA to 32 characters would leave a string that
still looks like provenance and no longer resolves to a commit.  An operator who
must roll back past this revision has to decide explicitly what those rows should
say (``UPDATE runs SET harness_version = 'unknown' WHERE length(harness_version) > 32``
is the honest one) and then re-run the downgrade.

Revision ID: ida_0004_harness_build_identity
Revises: ida_0003_judge_spend
Create Date: 2026-08-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ida_0004_harness_build_identity"
down_revision: Union[str, None] = "ida_0003_judge_spend"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table, NOT a bare alter_column: SQLite's ALTER TABLE supports
    # only RENAME / ADD / DROP COLUMN, so a plain type change dies with
    # "near ALTER: syntax error" there. Batch mode recreates-and-copies on
    # SQLite and emits an ordinary ALTER on Postgres (recreate="auto"), so ONE
    # migration serves the CI SQLite suite and the CloudNativePG production
    # database -- which is the only way `alembic upgrade head` can be tested at
    # all before it runs for real.
    with op.batch_alter_table("runs") as batch_op:
        batch_op.alter_column(
            "harness_version",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Fails loudly on Postgres if any row is longer than 32 characters. See the
    # module docstring: that refusal is the point, not an oversight.
    with op.batch_alter_table("runs") as batch_op:
        batch_op.alter_column(
            "harness_version",
            existing_type=sa.String(length=64),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
