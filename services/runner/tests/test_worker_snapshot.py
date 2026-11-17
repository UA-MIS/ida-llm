"""The worker reads ONE config snapshot per job (design 3.4, AD-9).

So a model or task added at ``/admin`` is runnable without a runner restart,
and one job never mixes two revisions (its registry and catalog come from the
same snapshot)."""

from __future__ import annotations

from datetime import UTC, datetime

from ida_core.config import repo_root
from ida_core.contracts import ModelRegistry, RunJobMessage, RunStatus
from ida_core.queue import InMemoryQueue
from ida_core.registry import load_registry
from ida_harness.config_provider import ConfigSnapshot
from ida_harness.tasks import TaskCatalog
from ida_runner import worker as worker_module
from ida_runner.worker import Worker

REGISTRY = load_registry(repo_root() / "models.yaml")
CATALOG = TaskCatalog.from_directory(repo_root() / "tasks")


class SwitchingProvider:
    """Hands out a different snapshot each time it is asked."""

    def __init__(self, snapshots: list[ConfigSnapshot]) -> None:
        self._snapshots = snapshots
        self.calls = 0

    def snapshot(self) -> ConfigSnapshot:
        snap = self._snapshots[min(self.calls, len(self._snapshots) - 1)]
        self.calls += 1
        return snap


def _snapshot(revision: int, registry: ModelRegistry) -> ConfigSnapshot:
    return ConfigSnapshot(
        revision=revision, registry=registry, catalog=CATALOG, curriculum=None, majors=None
    )


def _message(n: int) -> RunJobMessage:
    return RunJobMessage(
        run_id=f"run_{n}",
        task_id="demo/arithmetic-quiz-check",
        model_key="mock",
        enqueued_at=datetime.now(UTC),
    )


def test_each_job_reads_a_fresh_snapshot(monkeypatch) -> None:
    renamed = REGISTRY.model_copy(
        update={
            "models": [
                m.model_copy(update={"display_name": "Renamed"}) if m.key == "mock" else m
                for m in REGISTRY.models
            ]
        }
    )
    provider = SwitchingProvider([_snapshot(1, REGISTRY), _snapshot(2, renamed)])
    seen: list[str] = []

    class Done:
        status = RunStatus.SUCCEEDED

    def fake_execute(message, *, registry, catalog, **_kw):
        seen.append(registry.get("mock").display_name)
        assert catalog is CATALOG
        return Done()

    monkeypatch.setattr(worker_module, "execute_job", fake_execute)
    worker = Worker(
        queue=InMemoryQueue(),
        session_factory=None,
        registry=REGISTRY,
        catalog=CATALOG,
        artifact_store=None,
        config=provider,
    )
    worker._process(_message(1))
    worker._process(_message(2))
    assert provider.calls == 2
    assert seen == [REGISTRY.get("mock").display_name, "Renamed"]


def test_without_a_provider_the_startup_registry_is_used(monkeypatch) -> None:
    seen: list[object] = []

    class Done:
        status = RunStatus.SUCCEEDED

    def fake_execute(message, *, registry, catalog, **_kw):
        seen.append(registry)
        return Done()

    monkeypatch.setattr(worker_module, "execute_job", fake_execute)
    worker = Worker(
        queue=InMemoryQueue(),
        session_factory=None,
        registry=REGISTRY,
        catalog=CATALOG,
        artifact_store=None,
    )
    worker._process(_message(1))
    assert seen == [REGISTRY]


def test_a_credential_ref_model_resolves_its_key_in_the_worker(tmp_path, monkeypatch) -> None:
    """``execute_job`` hands the resolver to ``resolve_api_key``: a model that
    names an admin-entered credential gets the decrypted key, at use time."""
    from ida_core.contracts import RunRecord
    from ida_core.db import create_all, make_engine, make_session_factory, session_scope
    from ida_core.repositories import create_run
    from ida_runner.worker import execute_job

    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'w.db'}")
    create_all(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        create_run(
            session,
            RunRecord(
                id="run_cred",
                status=RunStatus.QUEUED,
                task_id="demo/arithmetic-quiz-check",
                model_key="mock",
                harness_version="t",
            ),
        )
    registry = REGISTRY.model_copy(
        update={
            "models": [
                m.model_copy(update={"credential_ref": "mock-cred", "api_key_env": None})
                if m.key == "mock"
                else m
                for m in REGISTRY.models
            ]
        }
    )

    class Resolver:
        def get(self, name: str) -> str:
            assert name == "mock-cred"
            return "sk-from-the-vault-not-real"

    captured = {}

    def fake_run_task(**kwargs):
        captured["api_key"] = kwargs["api_key"]
        raise RuntimeError("stop here")

    monkeypatch.setattr(worker_module, "run_task", fake_run_task)
    record = execute_job(
        _message(0).model_copy(update={"run_id": "run_cred"}),
        session_factory=factory,
        registry=registry,
        catalog=CATALOG,
        artifact_store=None,
        credentials=Resolver(),
    )
    assert captured["api_key"] == "sk-from-the-vault-not-real"
    assert record.status is RunStatus.FAILED  # the fake stopped it; the key got there
