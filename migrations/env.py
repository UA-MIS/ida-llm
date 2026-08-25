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

from alembic import context
from sqlalchemy import engine_from_config, pool

from ida_core.config import get_settings
from ida_core.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

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


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
