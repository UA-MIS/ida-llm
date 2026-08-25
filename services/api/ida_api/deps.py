"""Composition root: build the API's collaborators once, hand them out by DI.

Everything the routes need -- database session factory, queue, artifact store,
model registry, task catalog -- is constructed in :func:`build_context` and
stashed on ``app.state``.  Tests build an :class:`AppContext` with in-memory
implementations and get the *same* routes under test as production runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from ida_core.artifacts import ArtifactStore, LocalArtifactStore, S3ArtifactStore
from ida_core.config import Settings, get_settings
from ida_core.contracts import ModelRegistry
from ida_core.db import make_engine, make_session_factory
from ida_core.gitmeta import current_git_sha
from ida_core.queue import RedisQueue, RunQueue
from ida_core.registry import load_registry
from ida_harness.tasks import TaskCatalog


@dataclass
class AppContext:
    """Everything the API needs, assembled.  One instance per process."""

    settings: Settings
    session_factory: sessionmaker[Session]
    queue: RunQueue
    artifact_store: ArtifactStore
    registry: ModelRegistry
    catalog: TaskCatalog
    git_sha: str | None
    """D-1: recorded on every run this process enqueues."""


def build_artifact_store(settings: Settings) -> ArtifactStore:
    """MinIO/S3 or a local directory, per ``IDA_ARTIFACT_BACKEND``."""
    if settings.artifact_backend == "local":
        store = LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    else:
        store = S3ArtifactStore.from_settings(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
    return store


def build_context(settings: Settings | None = None) -> AppContext:
    """Assemble the production context from environment settings.

    Loads ``models.yaml`` and the whole task tree eagerly: a malformed task file
    should crash the pod at startup (and fail the readiness probe) rather than
    surface as a confusing 500 on someone's first run.
    """
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    return AppContext(
        settings=settings,
        session_factory=make_session_factory(engine),
        queue=RedisQueue.from_url(settings.redis_url),
        artifact_store=build_artifact_store(settings),
        registry=load_registry(settings.resolved_models_file()),
        catalog=TaskCatalog.from_directory(settings.resolved_tasks_dir()),
        git_sha=current_git_sha(settings.resolved_tasks_dir()),
    )


def get_context(request: Request) -> AppContext:
    """FastAPI dependency: the process-wide :class:`AppContext`."""
    return request.app.state.context
