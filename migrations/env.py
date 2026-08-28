"""Alembic environment.

Reads DATABASE_URL from the environment -- the same variable the app reads, from
the same Secret ESO materializes -- so a migration can never run against a
different database than the code that follows it.

``target_metadata`` is ``ida_core.db.Base.metadata``, so
``alembic revision --autogenerate`` sees the same schema the ORM does.

⚠ THE MIGRATE initContainer RUNS IN A TIGHT BOX: it gets only DATABASE_URL (no
`envFrom: ida-llm-config`), `readOnlyRootFilesystem: true`, and NO /tmp volume.
So nothing imported here may need another env var or write to disk at import
time. `Settings` has safe defaults for every other field; keep it that way.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool

from ida_core.config import get_settings
from ida_core.db import Base

config = context.config

if config.config_file_name is not None:
    # ⚠ disable_existing_loggers=False IS REQUIRED, and its default is True.
    # fileConfig() otherwise DISABLES every logger that already exists in the
    # process -- silently. Alembic is usually its own process, where that is
    # harmless, but this env.py is also driven in-process by
    # packages/core/tests/test_migrations.py, and a `logging.Logger.disabled`
    # flag set halfway through a test session is an extremely confusing way to
    # find out (it presents as "my log assertion sees nothing", nowhere near
    # the cause).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    """Delegate to ida_core so migrations and the app can never disagree.

    This used to normalise the DSN scheme itself. That is exactly how the app and
    the migration ended up on different drivers -- the initContainer migrated the
    schema happily while the API could not connect at all. One helper, both
    callers (see Settings.sqlalchemy_url).
    """
    if not (os.environ.get("DATABASE_URL") or os.environ.get("IDA_DATABASE_URL")):
        raise RuntimeError(
            "DATABASE_URL is not set. In the cluster it is materialized by ESO from Vault "
            "(tenants/ida-llm/<env>/database); in CI it points at the throwaway Postgres "
            "service container; locally, copy .env.example to .env."
        )
    return get_settings().sqlalchemy_url()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection (``alembic upgrade --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _refuse_foreign_stamp(connectable) -> None:
    """Fail loudly if this database was stamped by a chain that is not ours.

    ⚠ ALEMBIC RESOLVES *PARTIAL* REVISION IDENTIFIERS, and that turned a stale
    stamp into silent schema corruption on the first real deploy of this code.

    The pre-port scaffold shipped a migration whose revision id was the bare
    string ``"0001"``. Ours was ``"0001_baseline"``. ``"0001"`` is a unique
    PREFIX of it, so on a database still stamped by the scaffold,
    ``alembic upgrade head`` did not fail and did not run the baseline -- it
    concluded the baseline was already applied and went straight to 0002,
    against a schema that shares only its TABLE NAMES with ours. It died on the
    first ``DROP INDEX``, having already been one statement away from adding our
    columns to the scaffold's tables and calling it a successful migration.

    Renaming our revisions (``ida_0001_...``) removes that particular collision.
    This guard removes the CLASS: any stamp that is not EXACTLY one of our
    revisions stops the migration before a single DDL statement runs, with a
    message that says what to do about it. A stale stamp is an operator problem
    with an operator answer; it must never be a schema problem.

    Deliberately does NOT repair anything. Dropping tables is irreversible and
    belongs to a human with the context to know whether the rows matter.
    """
    # ⚠ ITS OWN CONNECTION, and that is not incidental. Alembic OWNS the
    # transaction on the connection it migrates through. Reading from that same
    # connection first starts an implicit transaction alembic did not open and
    # never commits -- so every migration runs, reports success, and is silently
    # ROLLED BACK when the connection closes. (Found exactly that way: the
    # existing schema-vs-ORM test failed with the post-0002 columns missing while
    # the log cheerfully showed 0002 running.)
    with connectable.connect() as probe:
        if "alembic_version" not in sa.inspect(probe).get_table_names():
            return  # a fresh database; the whole chain is about to run
        stamped = [
            row[0] for row in probe.execute(sa.text("SELECT version_num FROM alembic_version"))
        ]
    if not stamped:
        return

    known = {script.revision for script in ScriptDirectory.from_config(config).walk_revisions()}
    foreign = sorted(set(stamped) - known)
    if not foreign:
        return

    raise RuntimeError(
        "This database is stamped with revision(s) "
        f"{foreign}, which this migration chain does not contain. "
        f"Known revisions: {sorted(known)}.\n"
        "\n"
        "Almost certainly it was created by the PRE-PORT SCAFFOLD, whose schema "
        "shares table names with ours and nothing else. Migrating on top of it "
        "would produce a schema that is neither.\n"
        "\n"
        "If the tables are EMPTY (they were in dev, staging and prod at the time "
        "of the port), the fix is to discard the scaffold schema and let this "
        "chain build its own:\n"
        "    DROP TABLE IF EXISTS results, runs, alembic_version CASCADE;\n"
        "then redeploy. IF THEY ARE NOT EMPTY, STOP: those rows predate the "
        "current contract and someone has to decide what they are worth."
    )


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    _refuse_foreign_stamp(connectable)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
