"""Runner test fixtures: real SQLite, real in-memory queue, real local artifact store."""

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

from ida_core.artifacts import LocalArtifactStore
from ida_core.config import repo_root
from ida_core.db import create_all, make_engine, make_session_factory
from ida_core.queue import InMemoryQueue
from ida_core.registry import load_registry
from ida_harness.client import OpenAICompatibleClient
from ida_harness.tasks import TaskCatalog


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'runner.db'}")
    create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def registry():
    return load_registry(repo_root() / "models.yaml")


@pytest.fixture
def catalog() -> TaskCatalog:
    return TaskCatalog.from_directory(repo_root() / "tasks")


@pytest.fixture
def artifact_store(tmp_path) -> LocalArtifactStore:
    store = LocalArtifactStore(tmp_path / "artifacts")
    store.ensure_bucket()
    return store


@pytest.fixture
def queue() -> InMemoryQueue:
    return InMemoryQueue()


@pytest.fixture
def mock_transport_factory(registry):
    """A client factory that reaches the REAL mock-model service, in process.

    No socket, no container -- but the genuine service code answering the
    genuine request. See ida_mock_model.testing.
    """
    from ida_mock_model.testing import make_transport

    transport = make_transport()

    def factory() -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            registry.get("mock"),
            transport=transport,
            sleep=lambda _s: None,
            jitter=lambda _lo, hi: hi,
        )

    return factory
