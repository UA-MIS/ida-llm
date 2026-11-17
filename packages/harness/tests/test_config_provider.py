"""The config switch point (design 3.4): yaml and db snapshots agree, a new
revision goes live within ``refresh_s`` without a restart, and a rebuild that
fails keeps serving the previous snapshot."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from ida_core.config import Settings, repo_root
from ida_core.configdb.tables import ConfigRevisionRow, ModelRow, TaskRow
from ida_core.db import create_all, make_engine, make_session_factory, session_scope
from ida_harness.config_provider import (
    DbConfigProvider,
    YamlConfigProvider,
    build_provider,
)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'cfg.db'}",
        config_source="db",
    )


@pytest.fixture
def factory(settings):
    engine = make_engine(settings.database_url)
    create_all(engine)
    return make_session_factory(engine)


def _comparable(snapshot) -> dict:
    return {
        "registry": snapshot.registry.model_dump(mode="json"),
        "tasks": {s.id: s.content_sha for s in snapshot.catalog.all()},
        "curriculum": snapshot.curriculum.model_dump(mode="json") if snapshot.curriculum else None,
        "majors": snapshot.majors.model_dump(mode="json") if snapshot.majors else None,
        "units": {c: [u.model_dump() for u in rows] for c, rows in snapshot.units.items()},
        "git_sha": snapshot.task_git_sha,
    }


def test_yaml_and_db_snapshots_are_equal(settings, factory) -> None:
    yaml_snapshot = YamlConfigProvider(settings.model_copy(update={"config_source": "yaml"}))
    db_provider = build_provider(settings, factory)  # seeds, then loads
    assert isinstance(db_provider, DbConfigProvider)
    db_snapshot = db_provider.snapshot()
    assert db_snapshot.revision == 1
    assert _comparable(yaml_snapshot.snapshot()) == _comparable(db_snapshot)
    assert db_snapshot.catalog.source_of("demo/arithmetic-quiz-check").as_posix() == (
        "db:demo/arithmetic-quiz-check"
    )


def test_yaml_mode_ignores_the_database(settings, factory) -> None:
    provider = build_provider(settings.model_copy(update={"config_source": "yaml"}), factory)
    assert isinstance(provider, YamlConfigProvider)
    assert provider.snapshot().revision is None
    with session_scope(factory) as session:
        assert session.scalar(select(ConfigRevisionRow.id)) is None


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _bump(factory, mutate) -> None:
    with session_scope(factory) as session:
        mutate(session)
        session.add(ConfigRevisionRow(actor="octo", source="admin", summary="test"))


def test_a_revision_bump_is_picked_up_within_refresh_s(settings, factory) -> None:
    build_provider(settings, factory)
    clock = FakeClock()
    provider = DbConfigProvider(factory, refresh_s=5.0, clock=clock)
    first = provider.snapshot()
    _bump(factory, lambda s: setattr(s.get(ModelRow, "mock"), "display_name", "Renamed"))

    clock.now = 4.9  # inside the window: no query, old snapshot
    assert provider.snapshot() is first
    clock.now = 5.1
    second = provider.snapshot()
    assert second.revision == 2
    assert second.registry.get("mock").display_name == "Renamed"
    clock.now = 6.0
    assert provider.snapshot() is second  # cached again


def test_an_unchanged_revision_does_not_rebuild(settings, factory, monkeypatch) -> None:
    build_provider(settings, factory)
    clock = FakeClock()
    provider = DbConfigProvider(factory, refresh_s=1.0, clock=clock)
    first = provider.snapshot()
    monkeypatch.setattr(provider, "_build", lambda: pytest.fail("rebuilt without a new revision"))
    clock.now = 10.0
    assert provider.snapshot() is first


def test_a_failed_rebuild_keeps_the_previous_snapshot_and_logs_error(
    settings, factory, caplog
) -> None:
    build_provider(settings, factory)
    clock = FakeClock()
    provider = DbConfigProvider(factory, refresh_s=1.0, clock=clock)
    first = provider.snapshot()

    def corrupt(session) -> None:
        row = session.get(TaskRow, "demo/arithmetic-quiz-check")
        row.document = {**row.document, "kind": "not-a-kind"}

    _bump(factory, corrupt)
    clock.now = 2.0
    with caplog.at_level(logging.ERROR, logger="ida_harness.config_provider"):
        assert provider.snapshot() is first
    assert any("still serving revision 1" in r.getMessage() for r in caplog.records)


def test_the_first_snapshot_raises_rather_than_serving_nothing(settings, factory) -> None:
    provider = DbConfigProvider(factory)  # nothing seeded: empty registry is invalid
    with pytest.raises(Exception):  # noqa: B017 - any failure is the point
        provider.snapshot()


def test_db_mode_without_a_session_factory_is_refused(settings) -> None:
    with pytest.raises(ValueError, match="session factory"):
        build_provider(settings)


def test_repo_root_is_the_seed_source() -> None:
    assert (repo_root() / "curriculum" / "units.yaml").is_file()
