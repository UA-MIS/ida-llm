"""Startup helpers.

`wait_for_database` exists because docker-compose starts Postgres and the
services together and the API otherwise loses the race every time. Its retry
loop was itself untested (A16), which is an awkward place to have a bug: it only
runs when something is already going wrong.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from ida_core.bootstrap import bootstrap_schema, wait_for_database
from ida_core.db import make_engine


class TestBootstrapSchema:
    def test_creates_both_tables(self, tmp_path) -> None:
        url = f"sqlite+pysqlite:///{tmp_path / 'boot.db'}"
        bootstrap_schema(url)
        assert set(inspect(make_engine(url)).get_table_names()) == {"runs", "results"}

    def test_is_idempotent(self, tmp_path) -> None:
        """`make dev` re-runs it on every stack start."""
        url = f"sqlite+pysqlite:///{tmp_path / 'boot.db'}"
        bootstrap_schema(url)
        bootstrap_schema(url)
        assert set(inspect(make_engine(url)).get_table_names()) == {"runs", "results"}


class TestWaitForDatabase:
    def test_returns_immediately_when_reachable(self, tmp_path) -> None:
        wait_for_database(f"sqlite+pysqlite:///{tmp_path / 'ok.db'}", attempts=1, delay_s=0)

    def test_retries_then_gives_up_with_a_readable_error(self, monkeypatch) -> None:
        """The failure mode that matters: it must not hang forever, and the
        message must name the actual connection problem."""
        attempts = {"n": 0}

        class _DeadConn:
            def __enter__(self):
                attempts["n"] += 1
                raise OperationalError("connect", {}, Exception("connection refused"))

            def __exit__(self, *exc):
                return False

        class _DeadEngine:
            def connect(self):
                return _DeadConn()

        monkeypatch.setattr("ida_core.bootstrap.make_engine", lambda _url: _DeadEngine())

        with pytest.raises(RuntimeError, match="never became ready"):
            wait_for_database("postgresql+psycopg://nope/nope", attempts=3, delay_s=0)
        assert attempts["n"] == 3, "it must actually retry, not fail on the first try"

    def test_succeeds_on_a_later_attempt(self, monkeypatch) -> None:
        """The real-world case: Postgres comes up a second or two late."""
        attempts = {"n": 0}

        class _Conn:
            def __enter__(self):
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise OperationalError("connect", {}, Exception("starting up"))
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, _stmt):
                return None

        class _Engine:
            def connect(self):
                return _Conn()

        monkeypatch.setattr("ida_core.bootstrap.make_engine", lambda _url: _Engine())
        wait_for_database("postgresql+psycopg://late/db", attempts=5, delay_s=0)
        assert attempts["n"] == 3
