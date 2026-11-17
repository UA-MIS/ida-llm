"""``configdb diff`` is EMPTY right after seeding (design 4.3) -- for the repo's
real config AND for the dev set (``models.dev.yaml``, ``tasks-all``,
``*.dev.yaml``, ``units.dev.yaml``).

This is the replay evidence for the B2 migration path: if seeding lost or
changed anything -- a field, an order, a task's hash, a class's families, a
unit -- this fails and names it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _configdb_helpers import db_settings, dev_overrides, session_factory_for

from ida_core.configdb.cli import (
    diff_configs,
    import_directory,
    main,
    parse_database,
    parse_sources,
    run_diff,
)
from ida_core.configdb.seed import SeedError, ensure_seeded, read_yaml_sources
from ida_core.configdb.tables import ConfigRevisionRow, ModelRow
from ida_core.db import session_scope


@pytest.mark.parametrize("dev", [False, True], ids=["real", "dev"])
def test_diff_is_empty_right_after_seeding(tmp_path, dev: bool) -> None:
    settings = db_settings(tmp_path, **(dev_overrides(tmp_path) if dev else {}))
    factory = session_factory_for(settings)
    ensure_seeded(settings, factory)
    assert run_diff(settings, factory) == []


def test_diff_names_an_edit(tmp_path) -> None:
    """The gate is not vacuous: change one row and it says what moved."""
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    ensure_seeded(settings, factory)
    with session_scope(factory) as session:
        session.get(ModelRow, "mock").display_name = "Edited"
    differences = run_diff(settings, factory)
    assert len(differences) == 1
    assert differences[0].startswith("models.mock.display_name: YAML ")
    assert differences[0].endswith("!= database 'Edited'")


def test_diff_reports_an_unseeded_database(tmp_path) -> None:
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    assert run_diff(settings, factory) == ["database: not seeded (config_revisions is empty)"]


def test_diff_detects_order_and_hash_changes() -> None:
    sources = read_yaml_sources(db_settings(Path("/nonexistent")))
    left = parse_sources(sources)
    right = parse_sources(sources)
    right.task_shas[next(iter(right.task_shas))] = "0" * 64
    right.registry_order.reverse()
    differences = diff_configs(left, right)
    assert any("content_sha" in d for d in differences)
    assert any("ORDER" in d for d in differences)


def test_cli_exit_codes(tmp_path, monkeypatch, capsys) -> None:
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    for key, value in {
        "IDA_DATABASE_URL": settings.database_url,
        "IDA_CONFIG_SOURCE": "db",
    }.items():
        monkeypatch.setenv(key, value)
    assert main(["diff"]) == 1  # not seeded
    ensure_seeded(settings, factory)
    assert main(["diff"]) == 0
    assert "no differences" in capsys.readouterr().out


def test_import_replaces_the_config_and_refuses_over_admin_edits(tmp_path) -> None:
    settings = db_settings(tmp_path)
    factory = session_factory_for(settings)
    ensure_seeded(settings, factory)
    repo = Path(__file__).resolve().parents[3]
    revision = import_directory(settings, factory, repo)
    assert revision == 2
    with session_scope(factory) as session:
        assert parse_database(session) == parse_sources(read_yaml_sources(settings))
        session.add(ConfigRevisionRow(actor="octo", source="admin", summary="edit"))
    with pytest.raises(SeedError, match="admin edits"):
        import_directory(settings, factory, repo)
    assert import_directory(settings, factory, repo, force=True) == 4
