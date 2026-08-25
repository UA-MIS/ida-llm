"""The Alembic baseline and the ORM metadata must not drift.

Production runs `alembic upgrade head`; tests and `make dev` run
`Base.metadata.create_all`. If those two ever describe different schemas, tests
pass against a database that production does not have. This test is the guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.command import upgrade
from alembic.config import Config
from sqlalchemy import inspect

from ida_core.db import Base, create_all, make_engine

CORE_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CORE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(CORE_ROOT / "ida_core" / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _describe(engine) -> dict:
    """Tables -> {columns: {name: (type, nullable)}, indexes: {name: (cols, unique)}}.

    The column **type** is part of the comparison. Without it, changing
    ``String(64)`` to ``Text`` in ``db.py``, or ``Float`` to ``Numeric``, passes
    this guard with no matching migration -- and the README advertises this test
    as the thing that keeps the two definitions honest.

    Types are compared as the dialect renders them (``VARCHAR(64)``, ``TEXT``,
    ``FLOAT``, ``INTEGER``, ``BOOLEAN``, ``JSON``, ``DATETIME``), because that is
    what the database actually got.

    **What this cannot catch**, stated so the guarantee is not overread: it runs
    on SQLite only, so dialect-specific divergence Postgres would show -- ``JSON``
    rendering as ``JSONB``, timezone semantics on ``DateTime(timezone=True)``,
    ``String`` length enforcement -- is out of reach. It catches structural
    drift between the ORM and the migrations, not dialect drift between SQLite
    and CloudNativePG.
    """
    inspector = inspect(engine)
    described = {}
    for table in sorted(inspector.get_table_names()):
        if table == "alembic_version":
            continue
        described[table] = {
            "columns": {
                c["name"]: (str(c["type"]), bool(c["nullable"]))
                for c in inspector.get_columns(table)
            },
            "indexes": {
                i["name"]: (tuple(i["column_names"]), bool(i["unique"]))
                for i in inspector.get_indexes(table)
            },
        }
    return described


@pytest.fixture
def migrated_engine(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("IDA_DATABASE_URL", url)
    engine = make_engine(url)
    upgrade(_alembic_config(url), "head")
    return engine


@pytest.fixture
def metadata_engine(tmp_path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'metadata.db'}")
    create_all(engine)
    return engine


def test_baseline_migration_matches_orm_metadata(migrated_engine, metadata_engine) -> None:
    assert _describe(migrated_engine) == _describe(metadata_engine)


def test_migration_creates_the_expected_tables(migrated_engine) -> None:
    assert set(_describe(migrated_engine)) == {"runs", "results"}


def test_orm_metadata_declares_both_tables() -> None:
    assert set(Base.metadata.tables) == {"runs", "results"}


def test_downgrade_removes_everything(migrated_engine, tmp_path, monkeypatch) -> None:
    """A migration you cannot roll back is a migration you cannot deploy safely."""
    from alembic.command import downgrade

    url = str(migrated_engine.url)
    monkeypatch.setenv("IDA_DATABASE_URL", url)
    downgrade(_alembic_config(url), "base")
    assert _describe(migrated_engine) == {}


class TestTheGuardItselfIsNotVacuous:
    """A3 — meta-tests: prove `_describe` would actually FAIL on drift.

    These exist because the type comparison was once reported as implemented
    when the edit had silently not applied, and every migration test still
    passed -- a guard that compares too little is indistinguishable from a
    working one until the day it matters. Asserting the comparison *detects* a
    difference is the only way to know it is real.

    Built with SQLAlchemy Core rather than the ORM: a synthetic one-column table
    is all that is needed, and it keeps the drift being tested obvious.
    """

    def _describe_table(self, tmp_path, name: str, *columns, **index) -> dict:
        metadata = sa.MetaData()
        table = sa.Table("drift", metadata, *columns)
        if index:
            sa.Index("ix_drift_value", table.c.value, unique=index["unique"])
        engine = make_engine(f"sqlite+pysqlite:///{tmp_path / name}")
        metadata.create_all(engine)
        return _describe(engine)

    def _id(self):
        return sa.Column("id", sa.String(16), primary_key=True)

    def test_it_records_column_types_not_only_nullability(self, metadata_engine) -> None:
        label = _describe(metadata_engine)["runs"]["columns"]["label"]
        assert label == ("VARCHAR(255)", True), (
            "the guard must capture the rendered type; if this is a bare bool, "
            "String -> Text drift passes silently"
        )

    def test_it_detects_a_string_to_text_widening(self, tmp_path) -> None:
        """The exact drift class the reviewer demonstrated slipping through."""
        narrow = self._describe_table(
            tmp_path, "narrow.db", self._id(), sa.Column("value", sa.String(64))
        )
        wide = self._describe_table(
            tmp_path, "wide.db", self._id(), sa.Column("value", sa.Text())
        )
        assert narrow["drift"]["columns"]["value"] == ("VARCHAR(64)", True)
        assert wide["drift"]["columns"]["value"] == ("TEXT", True)
        assert narrow != wide, "String(64) -> Text must be visible to the guard"

    def test_it_detects_a_string_length_change(self, tmp_path) -> None:
        """String(64) -> String(255) is also a real migration, and also silent
        without the rendered type."""
        short = self._describe_table(
            tmp_path, "s64.db", self._id(), sa.Column("value", sa.String(64))
        )
        long = self._describe_table(
            tmp_path, "s255.db", self._id(), sa.Column("value", sa.String(255))
        )
        assert short != long

    def test_it_detects_a_float_to_numeric_change(self, tmp_path) -> None:
        assert self._describe_table(
            tmp_path, "f.db", self._id(), sa.Column("value", sa.Float())
        ) != self._describe_table(
            tmp_path, "n.db", self._id(), sa.Column("value", sa.Numeric(10, 2))
        )

    def test_it_still_detects_nullability_changes(self, tmp_path) -> None:
        """Adding types must not have displaced the original check."""
        assert self._describe_table(
            tmp_path, "y.db", self._id(), sa.Column("value", sa.String(64), nullable=True)
        ) != self._describe_table(
            tmp_path, "n2.db", self._id(), sa.Column("value", sa.String(64), nullable=False)
        )

    def test_it_detects_a_lost_unique_constraint(self, tmp_path) -> None:
        assert self._describe_table(
            tmp_path, "u.db", self._id(), sa.Column("value", sa.String(64)), unique=True
        ) != self._describe_table(
            tmp_path, "nu.db", self._id(), sa.Column("value", sa.String(64)), unique=False
        )

    def test_identical_schemas_still_compare_equal(self, tmp_path) -> None:
        """The guard must not be so sensitive that it fires on nothing."""
        assert self._describe_table(
            tmp_path, "a.db", self._id(), sa.Column("value", sa.String(64))
        ) == self._describe_table(
            tmp_path, "b.db", self._id(), sa.Column("value", sa.String(64))
        )


class TestPartialDowngrade:
    """0002 -> 0001 specifically. Full teardown-to-base was the only case covered.

    A downgrade that only works when it drops everything is not a rollback --
    the operational case is "the new revision is bad, go back ONE", with the
    previous schema and its data intact.
    """

    def _config(self, engine, monkeypatch):
        url = str(engine.url)
        monkeypatch.setenv("IDA_DATABASE_URL", url)
        return _alembic_config(url)

    def test_it_removes_exactly_the_0002_columns(self, migrated_engine, monkeypatch) -> None:
        from alembic.command import downgrade

        added_to_runs = {"error_count", "sweep_id", "task_content_sha"}
        added_to_results = {
            "repeat_index",
            "judge_serving_config",
            "score_criteria",
            "task_content_sha",
            "cached",
            "archive_error",
        }
        before = _describe(migrated_engine)
        assert added_to_runs <= set(before["runs"]["columns"])
        assert added_to_results <= set(before["results"]["columns"])

        downgrade(self._config(migrated_engine, monkeypatch), "0001_baseline")
        after = _describe(migrated_engine)

        assert added_to_runs.isdisjoint(after["runs"]["columns"])
        assert added_to_results.isdisjoint(after["results"]["columns"])

    def test_the_0001_schema_is_left_intact(self, migrated_engine, monkeypatch) -> None:
        """Going back one revision must not take the baseline with it."""
        from alembic.command import downgrade

        downgrade(self._config(migrated_engine, monkeypatch), "0001_baseline")
        after = _describe(migrated_engine)

        assert set(after) == {"runs", "results"}
        # A representative column from each table, with its type.
        assert after["runs"]["columns"]["status"] == ("VARCHAR(16)", False)
        assert after["results"]["columns"]["serving_config"] == ("JSON", False)

    def test_the_unique_index_reverts_to_two_columns(
        self, migrated_engine, monkeypatch
    ) -> None:
        """0002 widened it to (run, sample, repeat); the downgrade must undo that,
        or a re-upgrade would try to create an index that already exists."""
        from alembic.command import downgrade

        widened = _describe(migrated_engine)["results"]["indexes"]["ix_results_run_sample"]
        assert widened == (("run_id", "sample_id", "repeat_index"), True)

        downgrade(self._config(migrated_engine, monkeypatch), "0001_baseline")
        reverted = _describe(migrated_engine)["results"]["indexes"]["ix_results_run_sample"]
        assert reverted == (("run_id", "sample_id"), True)

    def test_downgrade_then_upgrade_round_trips_to_the_orm_schema(
        self, migrated_engine, metadata_engine, monkeypatch
    ) -> None:
        """The real operational sequence: roll back, fix, roll forward."""
        from alembic.command import downgrade, upgrade

        config = self._config(migrated_engine, monkeypatch)
        downgrade(config, "0001_baseline")
        upgrade(config, "head")
        assert _describe(migrated_engine) == _describe(metadata_engine)

    def test_existing_rows_survive_the_round_trip(self, migrated_engine, monkeypatch) -> None:
        """A rollback that silently drops the tables would also pass the shape
        checks above. Assert the data is still there."""
        from alembic.command import downgrade, upgrade
        from sqlalchemy import text

        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO runs (id, status, task_id, model_key, harness_version,"
                    " sample_count, scored_count, error_count, prompt_tokens,"
                    " completion_tokens, total_cost_usd, created_at)"
                    " VALUES ('run_keep', 'succeeded', 't', 'm', '0.1.0',"
                    " 1, 1, 0, 0, 0, 0.0, '2026-01-01 00:00:00')"
                )
            )

        config = self._config(migrated_engine, monkeypatch)
        downgrade(config, "0001_baseline")
        upgrade(config, "head")

        with migrated_engine.connect() as conn:
            rows = conn.execute(text("SELECT id, status FROM runs")).all()
        assert rows == [("run_keep", "succeeded")]
