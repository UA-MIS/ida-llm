"""Shared fixtures for the config-database tests (seed, parity, provider).

Not a conftest: CI runs one pytest across five distributions, and a
``from conftest import`` binds to whichever conftest loaded first.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ida_core.config import Settings, repo_root
from ida_core.db import create_all, make_engine, make_session_factory

REPO = repo_root()


def db_settings(tmp_path: Path, **overrides) -> Settings:
    """``config_source=db`` over a fresh SQLite file, with the real YAML."""
    values = {
        "database_url": f"sqlite+pysqlite:///{tmp_path / 'config.db'}",
        "config_source": "db",
        "artifact_backend": "local",
        "artifact_local_root": str(tmp_path / "artifacts"),
    }
    values.update(overrides)
    return Settings(**values)


def dev_overrides(tmp_path: Path) -> dict:
    """The dev overlay's file overrides, with the image's ``/app/tasks-all``
    (``tasks/`` + ``tasks-dev/``) rebuilt under ``tmp_path``."""
    tasks_all = tmp_path / "tasks-all"
    shutil.copytree(REPO / "tasks", tasks_all)
    shutil.copytree(REPO / "tasks-dev", tasks_all, dirs_exist_ok=True)
    return {
        "models_file": str(REPO / "models.dev.yaml"),
        "tasks_dir": str(tasks_all),
        "majors_file": str(REPO / "curriculum" / "majors.dev.yaml"),
        "curriculum_file": str(REPO / "curriculum" / "slo.dev.yaml"),
        "units_file": str(REPO / "curriculum" / "units.dev.yaml"),
    }


def session_factory_for(settings: Settings):
    engine = make_engine(settings.database_url)
    create_all(engine)
    return make_session_factory(engine)
