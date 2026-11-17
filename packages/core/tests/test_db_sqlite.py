"""File-backed SQLite (tests, local dev) runs in WAL with a long busy timeout.

Pinned because the default -- rollback journal, an fsync per DDL statement and
per commit, a 5 s busy timeout -- made the in-process tracer flake with
``database is locked`` on a busy CI disk once the schema grew to 16 tables.
See ``ida_core.db._sqlite_wal``."""

from __future__ import annotations

from sqlalchemy import text

from ida_core.db import SQLITE_BUSY_TIMEOUT_S, make_engine


def test_file_backed_sqlite_uses_wal_and_normal_sync(tmp_path) -> None:
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'wal.db'}")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL


def test_in_memory_sqlite_is_left_alone() -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "memory"


def test_the_busy_timeout_is_longer_than_pysqlites_default() -> None:
    assert SQLITE_BUSY_TIMEOUT_S >= 30
