"""API test fixtures.

The API is exercised through the *real* routes with real SQLAlchemy and a real
(in-memory) queue and artifact store. Only the boundaries that would need a
server are swapped, and each swap is a real implementation of the same protocol,
never a mock -- so a passing test means the wiring works, not that the mock does.
"""

from __future__ import annotations

import sys
from pathlib import Path

# CI runs ONE `pytest` from the repo root with `--import-mode=importlib`, which
# (unlike the legacy `prepend` mode) puts NOTHING on sys.path. Without this line
# `from _runner_helpers import ...` resolves only when pytest happens to be
# invoked from this service's directory -- i.e. it passes locally and fails in
# CI. conftest.py is imported before any test module, so here is the one place
# it can be fixed once.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from fastapi.testclient import TestClient

from ida_api.app import create_app
from ida_api.deps import AppContext
from ida_core.artifacts import LocalArtifactStore
from ida_core.config import Settings, repo_root
from ida_core.db import create_all, make_engine, make_session_factory
from ida_core.queue import InMemoryQueue
from ida_core.registry import load_registry
from ida_harness.tasks import TaskCatalog


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}",
        artifact_backend="local",
        artifact_local_root=str(tmp_path / "artifacts"),
    )


@pytest.fixture
def context(settings: Settings, tmp_path) -> AppContext:
    engine = make_engine(settings.database_url)
    create_all(engine)
    store = LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    store.ensure_bucket()
    return AppContext(
        settings=settings,
        session_factory=make_session_factory(engine),
        queue=InMemoryQueue(),
        artifact_store=store,
        registry=load_registry(repo_root() / "models.yaml"),
        catalog=TaskCatalog.from_directory(repo_root() / "tasks"),
        git_sha="d" * 40,
    )


@pytest.fixture
def client(context: AppContext) -> TestClient:
    return TestClient(create_app(context))
