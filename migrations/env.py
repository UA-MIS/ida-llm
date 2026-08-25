"""Alembic environment.

Reads DATABASE_URL from the environment -- the same variable the app reads, from
the same Secret ESO materializes -- so a migration can never run against a
different database than the code that follows it.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from ida_core.models import Base
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. In the cluster it is materialized by ESO from Vault "
            "(tenants/ida-llm/<env>/database); in CI it points at the throwaway Postgres "
            "service container; locally, copy .env.example to .env."
        )
    # SQLAlchemy 2 + psycopg 3 wants the explicit driver. The Vault-assembled DSN
    # is a plain `postgresql://`, so normalise here rather than asking every
    # consumer to remember.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
