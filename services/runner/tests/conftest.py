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
from ida_core.contracts import ModelRegistry
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
    """The shipped registry with `qwen-local` switched off.

    The sweep/budget tests count runs against the {mock, luna} pair they were
    written for; `qwen-local` is a real, free, sweepable model and would double
    every expected figure. Its own sweep behaviour is not under test here.
    """
    shipped = load_registry(repo_root() / "models.yaml")
    return ModelRegistry(
        models=[
            m.model_copy(update={"enabled": False}) if m.key == "qwen-local" else m
            for m in shipped.models
        ]
    )


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
def mock_judge_factory(registry):
    """Build an :class:`LLMJudge` backed by the REAL mock-model service.

    ⚠ ZERO SPEND, AND THAT IS A PROPERTY OF THE FIXTURE, NOT A CONVENTION.
    The judge is the ``mock`` registry entry -- the only enabled key in
    ``models.yaml`` -- answered in process by the mock-model app. No hosted
    judge is reachable from here, so a test cannot start billing by accident.

    The mock answers the judge protocol for real (see
    ``ida_mock_model.responder``): it reads the criterion name and declared
    scale out of the prompt and returns a well-formed judgment chosen
    deterministically from the criterion name. So the grade is stable across
    runs, and if the judge prompt ever changes shape the mock stops matching and
    these tests fail loudly rather than a hand-written fixture continuing to
    answer a question nobody asks.

    ``judge_mode`` selects the failure drill: ``"json"`` grades, ``"malformed"``
    returns prose with a number in it -- the exact shape a real judge produces
    when it ignores the reply format -- which the harness correctly refuses.
    That is how the attempt-bound tests get a *service* that misbehaves rather
    than a stub that pretends to.
    """
    from ida_harness.judge import LLMJudge
    from ida_mock_model.app import create_app
    from ida_mock_model.testing import make_transport

    def factory(judge_mode: str = "json") -> LLMJudge:
        app = create_app()
        app.state.mock.responder.judge_mode = judge_mode
        entry = registry.get("mock")
        client = OpenAICompatibleClient(
            entry,
            transport=make_transport(app),
            sleep=lambda _s: None,
            jitter=lambda _lo, hi: hi,
        )
        return LLMJudge(entry=entry, client=client, owns_client=True)

    return factory


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
