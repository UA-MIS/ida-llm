"""Schema bootstrap for local dev and CI.

``make dev`` needs the tables to exist before the API and runner start.  In a
cluster that is an Alembic job; on a laptop it is this, invoked by
``scripts/bootstrap.py``.  Both paths converge on the same DDL because the
baseline migration is asserted equal to ``Base.metadata`` in
``packages/core/tests/test_migrations.py``.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ida_core.db import create_all, make_engine

log = logging.getLogger(__name__)


def wait_for_database(database_url: str, *, attempts: int = 30, delay_s: float = 1.0) -> None:
    """Block until the database accepts a connection.

    docker-compose starts Postgres and the services together; without this the
    API loses the startup race roughly every time.
    """
    engine = make_engine(database_url)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            last = exc
            log.info("database not ready (attempt %d/%d)", attempt, attempts)
            time.sleep(delay_s)
    raise RuntimeError(f"database never became ready: {last}")


def bootstrap_schema(database_url: str) -> None:
    """Create tables if they do not exist.  Idempotent."""
    engine = make_engine(database_url)
    create_all(engine)
    log.info("schema ready")
