"""runs: cancel, config revision and admin launcher

Three nullable columns, no backfill -- the same additive pattern as 0005:

* ``cancel_requested_at``  an admin cancelled a RUNNING run; the worker checks
  it between samples and lands the run on ``cancelled`` (AD-12).  A QUEUED run
  is cancelled outright, by status, and never needs this.
* ``config_revision``      which ``config_revisions`` id the run was planned
  against.  ``task_git_sha`` keeps meaning "the image's git sha", so the public
  run page's short-sha display does not change.
* ``launched_by``          the GitHub login behind an admin launch.  NULL for
  token/CLI/sweep launches, which already log ``principal.subject``.

⚠ THE REVISION ID IS ``ida_0007_run_cancel_provenance``, NOT THE DESIGN'S
``ida_0007_run_cancel_and_provenance``: ``alembic_version.version_num`` is
``VARCHAR(32)`` on Postgres and that name is 34 characters, so the upgrade
applied every DDL statement and then failed writing its own stamp.  SQLite does
not enforce the length, so only a Postgres run catches it.

``status`` is already ``VARCHAR(16)`` and ``"cancelled"`` fits, so the new
terminal status needs no type change.

Revision ID: ida_0007_run_cancel_provenance
Revises: ida_0006_admin_config_tables
Create Date: 2026-11-17 00:00:01.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ida_0007_run_cancel_provenance"
down_revision: Union[str, None] = "ida_0006_admin_config_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table, as 0004/0005 do, so the same revision runs on SQLite.
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("config_revision", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("launched_by", sa.String(length=64), nullable=True))


def downgrade() -> None:
    # A run cancelled after this revision keeps status 'cancelled' on downgrade;
    # code from before 0007 does not know that status. Roll back the code only
    # after no run is in that state, or accept those rows reading as unknown.
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("launched_by")
        batch_op.drop_column("config_revision")
        batch_op.drop_column("cancel_requested_at")
