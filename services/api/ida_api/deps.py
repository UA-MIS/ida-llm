"""Composition root: build the API's collaborators once, hand them out by DI.

Everything the routes need -- database session factory, queue, artifact store,
model registry, task catalog -- is constructed in :func:`build_context` and
stashed on ``app.state``.  Tests build an :class:`AppContext` with in-memory
implementations and get the *same* routes under test as production runs.
"""

from __future__ import annotations

import dataclasses

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from ida_api.slo import CurriculumView, curriculum_view_from, load_curriculum_view
from ida_core.artifacts import ArtifactStore, LocalArtifactStore, S3ArtifactStore
from ida_core.config import Settings, get_settings, repo_root
from ida_core.contracts import ModelRegistry
from ida_core.db import make_engine, make_session_factory
from ida_core.queue import RedisQueue, RunQueue
from ida_harness.config_provider import (
    ConfigProvider,
    ConfigSnapshot,
    StaticConfigProvider,
    build_provider,
)
from ida_harness.tasks import TaskCatalog


class AppContext:
    """Everything the API needs, assembled.  One instance per process.

    ``registry``, ``catalog``, ``git_sha`` and ``curriculum`` are PROPERTIES
    over a :class:`~ida_harness.config_provider.ConfigProvider`, so route code
    reads ``ctx.registry`` exactly as it always has while, in
    ``IDA_CONFIG_SOURCE=db``, the answer follows the live config revision (an
    admin edit is visible within ``IDA_CONFIG_REFRESH_S`` with no restart).

    Tests (and yaml mode) may still pass ``registry=``/``catalog=``/
    ``git_sha=``/``curriculum=`` directly; those are wrapped in a fixed
    snapshot.  ``config=`` takes precedence when given.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        queue: RunQueue,
        artifact_store: ArtifactStore,
        registry: ModelRegistry | None = None,
        catalog: TaskCatalog | None = None,
        git_sha: str | None = None,
        curriculum: CurriculumView | None = None,
        config: ConfigProvider | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.queue = queue
        self.artifact_store = artifact_store
        if config is None:
            if registry is None or catalog is None:
                raise TypeError("AppContext needs either config= or registry= and catalog=")
            config = StaticConfigProvider(
                ConfigSnapshot(
                    revision=None,
                    registry=registry,
                    catalog=catalog,
                    curriculum=None,
                    majors=None,
                    task_git_sha=git_sha,
                )
            )
        self.config = config
        self._fixed_curriculum = curriculum
        """``curriculum/slo.yaml`` projected ONCE at startup (yaml mode, tests).

        Per request would re-read and re-validate a file that cannot change while
        the process lives, on the path that serves the front page. Unlike the task
        catalog a missing or malformed map is NOT a boot failure -- the results view
        works without outcome statements, and `make lint-tasks` is the gate that
        fails a pull request over a bad map. Taking the site down over it would
        replace a visible data error with an invisible outage.

        ``None`` in db mode: the view is derived from the snapshot instead, and
        memoised per revision (:attr:`curriculum`)."""
        self._derived: tuple[int | None, CurriculumView] | None = None

    @property
    def registry(self) -> ModelRegistry:
        return self.config.snapshot().registry

    @registry.setter
    def registry(self, value: ModelRegistry) -> None:
        """Swap the registry by replacing the snapshot (tests do this). Pins the
        context to a fixed snapshot from then on -- never used in db mode."""
        self.config = StaticConfigProvider(
            dataclasses.replace(self.config.snapshot(), registry=value)
        )

    @property
    def catalog(self) -> TaskCatalog:
        return self.config.snapshot().catalog

    @catalog.setter
    def catalog(self, value: TaskCatalog) -> None:
        self.config = StaticConfigProvider(
            dataclasses.replace(self.config.snapshot(), catalog=value)
        )

    @property
    def git_sha(self) -> str | None:
        """D-1: recorded on every run this process enqueues."""
        return self.config.snapshot().task_git_sha

    @property
    def curriculum(self) -> CurriculumView:
        if self._fixed_curriculum is not None:
            return self._fixed_curriculum
        snapshot = self.config.snapshot()
        derived = self._derived
        if derived is None or derived[0] != snapshot.revision:
            derived = (
                snapshot.revision,
                curriculum_view_from(snapshot.curriculum, snapshot.majors, snapshot.units),
            )
            self._derived = derived
        return derived[1]

    def replace(self, **changes) -> AppContext:
        """A copy with some collaborators swapped (the ``dataclasses.replace``
        tests used before this stopped being a dataclass)."""
        snapshot = self.config.snapshot()
        values = {
            "settings": self.settings,
            "session_factory": self.session_factory,
            "queue": self.queue,
            "artifact_store": self.artifact_store,
            "registry": snapshot.registry,
            "catalog": snapshot.catalog,
            "git_sha": snapshot.task_git_sha,
            "curriculum": self._fixed_curriculum,
        }
        values.update(changes)
        return AppContext(**values)


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

    Loads ``models.yaml`` and the whole task tree eagerly (or, in
    ``IDA_CONFIG_SOURCE=db``, seeds-if-needed and builds the first snapshot):
    a malformed config should crash the pod at startup (and fail the readiness
    probe) rather than surface as a confusing 500 on someone's first run.
    """
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    config = build_provider(settings, session_factory)
    curriculum = None
    if settings.config_source == "yaml":
        # Today's projection, byte for byte. In db mode the view is derived
        # from each snapshot instead (AppContext.curriculum).
        curriculum = load_curriculum_view(
            repo_root(),
            # DEV-ONLY overrides (unset in staging/prod -> default locations).
            curriculum_path=settings.resolved_curriculum_file(),
            majors_path=settings.resolved_majors_file(),
            units_path=settings.resolved_units_file(),
        )
    return AppContext(
        settings=settings,
        session_factory=session_factory,
        queue=RedisQueue.from_url(settings.redis_url),
        artifact_store=build_artifact_store(settings),
        config=config,
        curriculum=curriculum,
    )


def get_context(request: Request) -> AppContext:
    """FastAPI dependency: the process-wide :class:`AppContext`."""
    return request.app.state.context
