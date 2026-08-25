"""The Alembic baseline and the ORM metadata must not drift.

Production runs `alembic upgrade head`; tests and `make dev` run
`Base.metadata.create_all`. If those two ever describe different schemas, tests
pass against a database that production does not have. This test is the guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
import sqlalchemy as sa
from alembic.command import upgrade
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import inspect

from ida_core.db import Base, create_all, make_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
"""The repo root. Migrations live at `migrations/` with `alembic.ini` beside it --
NOT inside packages/core -- because the CI `migrations` job, Dockerfile.python and
the api's `migrate` initContainer all point there."""


def _alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
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
        wide = self._describe_table(tmp_path, "wide.db", self._id(), sa.Column("value", sa.Text()))
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
        ) == self._describe_table(tmp_path, "b.db", self._id(), sa.Column("value", sa.String(64)))


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

        downgrade(self._config(migrated_engine, monkeypatch), "ida_0001_baseline")
        after = _describe(migrated_engine)

        assert added_to_runs.isdisjoint(after["runs"]["columns"])
        assert added_to_results.isdisjoint(after["results"]["columns"])

    def test_the_0001_schema_is_left_intact(self, migrated_engine, monkeypatch) -> None:
        """Going back one revision must not take the baseline with it."""
        from alembic.command import downgrade

        downgrade(self._config(migrated_engine, monkeypatch), "ida_0001_baseline")
        after = _describe(migrated_engine)

        assert set(after) == {"runs", "results"}
        # A representative column from each table, with its type.
        assert after["runs"]["columns"]["status"] == ("VARCHAR(16)", False)
        assert after["results"]["columns"]["serving_config"] == ("JSON", False)

    def test_the_unique_index_reverts_to_two_columns(self, migrated_engine, monkeypatch) -> None:
        """0002 widened it to (run, sample, repeat); the downgrade must undo that,
        or a re-upgrade would try to create an index that already exists."""
        from alembic.command import downgrade

        widened = _describe(migrated_engine)["results"]["indexes"]["ix_results_run_sample"]
        assert widened == (("run_id", "sample_id", "repeat_index"), True)

        downgrade(self._config(migrated_engine, monkeypatch), "ida_0001_baseline")
        reverted = _describe(migrated_engine)["results"]["indexes"]["ix_results_run_sample"]
        assert reverted == (("run_id", "sample_id"), True)

    def test_downgrade_then_upgrade_round_trips_to_the_orm_schema(
        self, migrated_engine, metadata_engine, monkeypatch
    ) -> None:
        """The real operational sequence: roll back, fix, roll forward."""
        from alembic.command import downgrade, upgrade

        config = self._config(migrated_engine, monkeypatch)
        downgrade(config, "ida_0001_baseline")
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
        downgrade(config, "ida_0001_baseline")
        upgrade(config, "head")

        with migrated_engine.connect() as conn:
            rows = conn.execute(text("SELECT id, status FROM runs")).all()
        assert rows == [("run_keep", "succeeded")]


class TestForeignStampIsRefused:
    """The bug that broke the first real deploy of the port.

    ⚠ ALEMBIC RESOLVES PARTIAL REVISION IDENTIFIERS. The pre-port scaffold
    stamped its databases with the bare revision id ``"0001"``. Our baseline was
    ``"0001_baseline"`` -- of which ``"0001"`` is a unique PREFIX. So on every
    already-deployed environment, `alembic upgrade head` did NOT fail and did NOT
    run our baseline: it concluded the baseline was applied and went straight to
    0002, against the scaffold's schema, which shares table NAMES with ours and
    nothing else.

    It happened to die on `DROP INDEX ix_results_run_sample` (the scaffold never
    created that index). One statement earlier and it would have started adding
    our columns to the scaffold's tables and reported success. That is the
    failure this class exists to prevent: not a crash, a SILENT WRONG SCHEMA.

    All three environments held zero rows when this was found, which is the only
    reason it cost nothing.
    """

    def test_our_ids_cannot_be_prefix_matched_by_the_scaffolds(self) -> None:
        """The specific collision, closed by renaming."""
        config = _alembic_config("sqlite+pysqlite:///:memory:")
        script = ScriptDirectory.from_config(config)

        with pytest.raises(CommandError):
            script.get_revision("0001")

        # ...and ours still resolve by their real names.
        assert script.get_revision("ida_0001_baseline").revision == "ida_0001_baseline"

    def test_no_revision_id_is_a_prefix_of_another(self) -> None:
        """The general rule, so the next migration cannot reintroduce this.

        Alembic's partial matching makes any id that prefixes another id an
        ambiguity waiting to happen.
        """
        config = _alembic_config("sqlite+pysqlite:///:memory:")
        revisions = [s.revision for s in ScriptDirectory.from_config(config).walk_revisions()]
        for a in revisions:
            for b in revisions:
                if a != b:
                    assert not b.startswith(a), f"{b!r} is prefixed by {a!r}"

    def test_a_foreign_stamp_stops_the_migration_before_any_ddl(
        self, tmp_path, monkeypatch
    ) -> None:
        """THE guard. Reproduces dev's exact state: stamped '0001', scaffold schema.

        What must NOT happen is what happened: DDL running against a schema this
        chain did not build.
        """
        url = f"sqlite+pysqlite:///{tmp_path / 'foreign.db'}"
        monkeypatch.setenv("IDA_DATABASE_URL", url)
        engine = make_engine(url)
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0001')"))
            # the scaffold's `results`: same NAME, entirely different columns
            conn.execute(sa.text("CREATE TABLE results (id VARCHAR, run_id VARCHAR, score FLOAT)"))

        with pytest.raises(Exception) as exc:
            upgrade(_alembic_config(url), "head")
        assert "0001" in str(exc.value)

        # The scaffold's table is untouched: the guard ran before any DDL.
        with engine.begin() as conn:
            columns = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(results)")).fetchall()}
        assert columns == {"id", "run_id", "score"}, (
            "the guard must refuse BEFORE altering a schema it does not own"
        )

    def test_the_message_tells_the_operator_what_to_do(self, tmp_path, monkeypatch) -> None:
        """A migration that fails inside an initContainer is read once, in a hurry,
        by someone who did not write it. 'Can't locate revision' is not enough."""
        url = f"sqlite+pysqlite:///{tmp_path / 'foreign2.db'}"
        monkeypatch.setenv("IDA_DATABASE_URL", url)
        engine = make_engine(url)
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0001')"))

        with pytest.raises(Exception) as exc:
            upgrade(_alembic_config(url), "head")
        message = str(exc.value)
        assert "PRE-PORT SCAFFOLD" in message
        assert "DROP TABLE" in message
        assert "IF THEY ARE NOT EMPTY, STOP" in message

    def test_a_clean_database_is_unaffected(self, tmp_path, monkeypatch) -> None:
        """The guard must be invisible on the path everyone actually takes."""
        url = f"sqlite+pysqlite:///{tmp_path / 'clean.db'}"
        monkeypatch.setenv("IDA_DATABASE_URL", url)
        upgrade(_alembic_config(url), "head")
        assert {"runs", "results"} <= set(inspect(make_engine(url)).get_table_names())


class TestPartialDowngradeToTwo:
    """0003 -> 0002 specifically, for the same reason TestPartialDowngrade exists.

    The operational case is never "tear the database down"; it is "0003 is bad,
    go back one, keep 0002's schema and its rows".
    """

    ADDED_TO_RESULTS: ClassVar[set[str]] = {
        "judge_prompt_tokens",
        "judge_completion_tokens",
        "judge_cost_usd",
        "judge_transcript_uri",
    }

    def _config(self, engine, monkeypatch):
        url = str(engine.url)
        monkeypatch.setenv("IDA_DATABASE_URL", url)
        return _alembic_config(url)

    def test_head_carries_the_judge_spend_columns(self, migrated_engine) -> None:
        columns = _describe(migrated_engine)["results"]["columns"]
        assert set(columns) >= self.ADDED_TO_RESULTS

    def test_the_spend_columns_are_not_nullable_and_default_to_zero(self, migrated_engine) -> None:
        """Zero is the TRUE answer for a row nothing judged, so the column can be
        NOT NULL -- there is no 'unknown' state to represent."""
        columns = _describe(migrated_engine)["results"]["columns"]
        for name in ("judge_prompt_tokens", "judge_completion_tokens", "judge_cost_usd"):
            _type, nullable = columns[name]
            assert nullable is False, name
        assert columns["judge_transcript_uri"][1] is True, "no judge ran -> no pointer"

    def test_it_removes_exactly_the_0003_columns(self, migrated_engine, monkeypatch) -> None:
        from alembic.command import downgrade

        before = _describe(migrated_engine)
        assert set(before["results"]["columns"]) >= self.ADDED_TO_RESULTS

        downgrade(self._config(migrated_engine, monkeypatch), "ida_0002_failure_and_provenance")
        after = _describe(migrated_engine)

        assert self.ADDED_TO_RESULTS.isdisjoint(after["results"]["columns"])

    def test_the_0002_schema_is_left_intact(self, migrated_engine, monkeypatch) -> None:
        """Going back one revision must not take 0002's columns with it."""
        from alembic.command import downgrade

        downgrade(self._config(migrated_engine, monkeypatch), "ida_0002_failure_and_provenance")
        after = _describe(migrated_engine)

        assert {"judge_serving_config", "score_criteria", "cached", "archive_error"} <= set(
            after["results"]["columns"]
        )
        assert after["results"]["indexes"]["ix_results_run_sample"] == (
            ("run_id", "sample_id", "repeat_index"),
            True,
        )

    def test_downgrade_then_upgrade_round_trips_to_the_orm_schema(
        self, migrated_engine, metadata_engine, monkeypatch
    ) -> None:
        from alembic.command import downgrade, upgrade

        config = self._config(migrated_engine, monkeypatch)
        downgrade(config, "ida_0002_failure_and_provenance")
        upgrade(config, "head")
        assert _describe(migrated_engine) == _describe(metadata_engine)

    def test_the_downgrade_discards_judge_spend_and_the_docstring_says_so(
        self, migrated_engine, monkeypatch
    ) -> None:
        """E8 — expected for a column drop, but it must not be a surprise.

        0002 has a data-survival test; this is its counterpart, asserting the
        opposite and pinning the warning that tells an operator so. The judge
        TRANSCRIPTS are untouched in object storage — it is the pointers to them
        that a rollback discards.
        """
        import migrations.versions as _versions  # noqa: F401 - locate the package
        from alembic.command import downgrade, upgrade
        from sqlalchemy import text

        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO runs (id, status, task_id, model_key, harness_version, "
                    "sample_count, scored_count, error_count, prompt_tokens, "
                    "completion_tokens, total_cost_usd, created_at) VALUES "
                    "('r1', 'succeeded', 't', 'm', '0.1.0', 1, 1, 0, 0, 0, 0.0, "
                    "CURRENT_TIMESTAMP)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO results (id, run_id, task_id, sample_id, repeat_index, "
                    "model_key, serving_config, scorable, cached, prompt_tokens, "
                    "completion_tokens, cost_usd, latency_ms, judge_prompt_tokens, "
                    "judge_completion_tokens, judge_cost_usd, judge_transcript_uri, "
                    "created_at) VALUES ('x1', 'r1', 't', 's1', 0, 'm', '{}', 1, 0, 10, 2, "
                    "0.0, 1.0, 200, 40, 0.00028, 's3://b/runs/r1/judge/s1.json', "
                    "CURRENT_TIMESTAMP)"
                )
            )

        config = self._config(migrated_engine, monkeypatch)
        downgrade(config, "ida_0002_failure_and_provenance")
        upgrade(config, "head")

        with migrated_engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT judge_prompt_tokens, judge_completion_tokens, judge_cost_usd, "
                    "judge_transcript_uri FROM results WHERE id = 'x1'"
                )
            ).one()
        assert tuple(row) == (0, 0, 0.0, None), "the loss is real"

        # The row itself survives -- this is a column drop, not a table drop.
        with migrated_engine.begin() as conn:
            kept = conn.execute(
                text("SELECT cost_usd, latency_ms FROM results WHERE id = 'x1'")
            ).one()
        assert tuple(kept) == (0.0, 1.0)

        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3]
            / "migrations"
            / "versions"
            / "0003_judge_spend_and_evidence.py"
        ).read_text()
        assert "THE DOWNGRADE DESTROYS DATA" in source, (
            "an operator must be warned where they look, not only where we tested"
        )
