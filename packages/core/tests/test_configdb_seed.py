"""``ensure_seeded``: once, serialised, loud, and faithful (AD-7, design 4.1).

What would go wrong without each test:

* not idempotent -> every pod restart re-seeds over an admin's edits;
* not serialised -> three pods starting together insert three seeds and crash;
* quiet on bad YAML -> a config CI would reject goes live in the database;
* a content_sha drift -> every pair re-enqueues and every score detaches from
  its task text.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _configdb_helpers import db_settings, dev_overrides, session_factory_for

from ida_core.configdb import seed as seed_module
from ida_core.configdb.reader import current_revision
from ida_core.configdb.seed import SeedError, ensure_seeded, read_yaml_sources
from ida_core.configdb.tables import (
    AuditLogRow,
    ConfigRevisionRow,
    ModelRow,
    TaskRevisionRow,
    TaskRow,
    UnitRow,
)
from ida_core.db import session_scope


def _count(session_factory, table) -> int:
    with session_scope(session_factory) as session:
        return int(session.scalar(select(func.count()).select_from(table)))


def test_yaml_mode_never_touches_the_database(tmp_path) -> None:
    settings = db_settings(tmp_path, config_source="yaml")
    factory = session_factory_for(settings)
    assert ensure_seeded(settings, factory) is False
    assert _count(factory, ConfigRevisionRow) == 0


def test_seeds_once_and_records_revision_one(tmp_path) -> None:
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    assert ensure_seeded(settings, factory) is True
    with session_scope(factory) as session:
        revision, at = current_revision(session)
        row = session.get(ConfigRevisionRow, 1)
        assert row.source == "seed"
        assert row.actor == "system:seed"
    assert revision == 1 and at is not None
    assert _count(factory, ModelRow) > 0
    assert _count(factory, TaskRow) == _count(factory, TaskRevisionRow)
    assert _count(factory, AuditLogRow) == 1


def test_never_reruns_after_revision_one(tmp_path, monkeypatch) -> None:
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    ensure_seeded(settings, factory)
    models = _count(factory, ModelRow)

    def boom(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("re-read the YAML after seeding")

    monkeypatch.setattr(seed_module, "read_yaml_sources", boom)
    assert ensure_seeded(settings, factory) is False
    assert _count(factory, ModelRow) == models
    assert _count(factory, ConfigRevisionRow) == 1


def test_two_racing_seeders_produce_one_seed(tmp_path) -> None:
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    sources = read_yaml_sources(settings)
    results: list[object] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        barrier.wait()
        try:
            results.append(ensure_seeded(settings, factory, sources=sources))
        except Exception as exc:  # pragma: no cover - surfaced below
            results.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results, key=str) == [False, True]
    assert _count(factory, ConfigRevisionRow) == 1


def test_uses_the_dev_override_paths_when_set(tmp_path) -> None:
    settings = db_settings(tmp_path, **dev_overrides(tmp_path))
    factory = session_factory_for(settings)
    ensure_seeded(settings, factory)
    with session_scope(factory) as session:
        keys = set(session.scalars(select(ModelRow.key)))
        units = set(session.scalars(select(UnitRow.course)))
        demo_tasks = session.scalar(
            select(func.count()).select_from(TaskRow).where(TaskRow.id.like("demo-%"))
        )
    assert "vega" in keys  # only in models.dev.yaml
    assert "AC 210" in units  # only in units.dev.yaml
    assert demo_tasks > 0  # tasks-dev/


def test_prod_seed_carries_no_dev_demo_content(tmp_path) -> None:
    """The guarantee the deploy relies on: without the dev overrides (staging
    and prod set none), not one demo model, task or unit is seeded."""
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    ensure_seeded(settings, factory)
    with session_scope(factory) as session:
        assert "vega" not in set(session.scalars(select(ModelRow.key)))
        assert "AC 210" not in set(session.scalars(select(UnitRow.course)))
        assert not session.scalar(
            select(func.count()).select_from(TaskRow).where(TaskRow.id.like("demo-%"))
        )


def test_invalid_yaml_raises_and_writes_nothing(tmp_path) -> None:
    bad_models = tmp_path / "models.yaml"
    bad_models.write_text("version: 1\nmodels:\n  - key: Not A Key\n    display_name: x\n")
    settings = db_settings(tmp_path, models_file=str(bad_models))
    factory = session_factory_for(settings)
    with pytest.raises(SeedError) as excinfo:
        ensure_seeded(settings, factory)
    assert excinfo.value.issues
    assert _count(factory, ConfigRevisionRow) == 0
    assert _count(factory, ModelRow) == 0


def test_a_content_sha_mismatch_aborts_the_seed(tmp_path, monkeypatch) -> None:
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    real = seed_module.normalise_document

    def drifting(document):
        out = real(document)
        if isinstance(out, dict) and "samples" in out:
            out["title"] = out["title"] + " (drift)"
        return out

    monkeypatch.setattr(seed_module, "normalise_document", drifting)
    with pytest.raises(SeedError, match="hashes to"):
        ensure_seeded(settings, factory)
    assert _count(factory, ConfigRevisionRow) == 0
    assert _count(factory, TaskRow) == 0


def test_no_credentials_are_seeded(tmp_path) -> None:
    from ida_core.configdb.tables import ProviderCredentialRow

    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    ensure_seeded(settings, factory)
    assert _count(factory, ProviderCredentialRow) == 0
    with session_scope(factory) as session:
        assert all(r.credential_ref is None for r in session.scalars(select(ModelRow)))
