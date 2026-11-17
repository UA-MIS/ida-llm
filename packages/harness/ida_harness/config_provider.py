"""The configuration switch point: YAML or the database (AD-6, design 3.4).

Every process that needs the model registry, the task catalog or the
curriculum asks a :class:`ConfigProvider` for a :class:`ConfigSnapshot` instead
of reading files itself.  ``IDA_CONFIG_SOURCE`` picks the provider:

``yaml`` (default)  :class:`YamlConfigProvider` -- today's behaviour, loaded once
                    at startup through today's loaders.  Every test, CLI and
                    ``make dev`` path keeps working byte for byte.
``db``              :class:`DbConfigProvider` -- the configuration tables, seeded
                    once from the same YAML, edited at ``/admin`` after that.

Lives in harness, not core, because a snapshot holds a ``TaskCatalog`` and
harness imports core, never the reverse.

HOW AN ADMIN EDIT GOES LIVE WITHOUT A RESTART (AD-9).  Every admin write appends
a ``config_revisions`` row.  :class:`DbConfigProvider` checks ``max(id)`` at most
once per ``IDA_CONFIG_REFRESH_S`` (5 s) and rebuilds its snapshot when the
number moved.  A rebuild that fails validation logs ERROR and KEEPS SERVING THE
PREVIOUS SNAPSHOT -- a process never serves half a config, and never goes dark
because one admin write it could not parse reached it first.  (The admin API
validates before committing, so this is the belt to those braces.)

Cost note (design R9): a rebuild re-validates the whole catalog.  Fine at tens
of tasks; if uploads grow it to thousands, rebuild incrementally by
``updated_at``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from ida_core.config import Settings, repo_root
from ida_core.configdb import reader
from ida_core.configdb.seed import ensure_seeded
from ida_core.contracts import ModelRegistry
from ida_core.curriculum import CurriculumMap, default_curriculum_path, load_curriculum
from ida_core.db import session_scope
from ida_core.gitmeta import current_git_sha
from ida_core.majors import Majors, default_majors_path, load_majors
from ida_core.registry import load_registry
from ida_core.units import Units, load_units
from ida_core.validation import (
    validate_curriculum_document,
    validate_majors_document,
    validate_models_document,
)
from ida_harness.tasks import TaskCatalog

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigSnapshot:
    """One consistent view of the configuration.  Never mutated; replaced."""

    revision: int | None
    """``config_revisions`` id this was built from; ``None`` in yaml mode."""
    registry: ModelRegistry
    catalog: TaskCatalog
    curriculum: CurriculumMap | None
    majors: Majors | None
    units: Units = field(default_factory=dict)
    task_git_sha: str | None = None
    """Unchanged meaning: the image's / task tree's git sha (D-1)."""


class ConfigProvider(Protocol):
    def snapshot(self) -> ConfigSnapshot: ...


class StaticConfigProvider:
    """A fixed snapshot -- tests, and callers that already hold the objects."""

    def __init__(self, snapshot: ConfigSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> ConfigSnapshot:
        return self._snapshot


# ───────────────────────────────────────────────────────────────── yaml ──


def _optional(loader: Callable, path, what: str):
    """Load an optional curriculum file: ``None`` if absent or broken (logged).

    The same never-take-the-site-down contract ``ida_api.slo`` has: a broken
    curriculum is ``make lint-tasks``'s problem, not a boot failure."""
    try:
        return loader(path) if path is not None and path.is_file() else None
    except Exception:
        log.exception("could not load the %s at %s", what, path)
        return None


def load_yaml_snapshot(settings: Settings) -> ConfigSnapshot:
    """Today's loaders, today's resolvers.  The model registry and the task
    catalog are REQUIRED (a malformed one crashes the pod at startup, as it
    always has); the curriculum files are optional."""
    root = repo_root()
    tasks_dir = settings.resolved_tasks_dir()
    try:
        units = load_units(settings.resolved_units_file())
    except Exception:
        log.exception("could not load the unit taxonomy at %s", settings.resolved_units_file())
        units = {}
    return ConfigSnapshot(
        revision=None,
        registry=load_registry(settings.resolved_models_file()),
        catalog=TaskCatalog.from_directory(tasks_dir),
        curriculum=_optional(
            load_curriculum,
            settings.resolved_curriculum_file() or default_curriculum_path(root),
            "curriculum map",
        ),
        majors=_optional(
            load_majors,
            settings.resolved_majors_file() or default_majors_path(root),
            "majors taxonomy",
        ),
        units=units,
        task_git_sha=current_git_sha(tasks_dir),
    )


class YamlConfigProvider(StaticConfigProvider):
    """``IDA_CONFIG_SOURCE=yaml``: loaded once, never refreshed -- exactly the
    pre-admin behaviour."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(load_yaml_snapshot(settings))


# ─────────────────────────────────────────────────────────────────── db ──


def load_db_snapshot(session: Session, *, task_git_sha: str | None) -> ConfigSnapshot:
    """Rebuild every config object from the tables, through the YAML path's own
    validators (see :mod:`ida_core.configdb.reader`).  Raises on anything invalid."""
    revision, _ = reader.current_revision(session)
    models_doc = reader.models_document(session)
    validate_models_document(models_doc, "db:models")
    registry = ModelRegistry.model_validate(models_doc)
    catalog = TaskCatalog.from_documents(reader.task_documents(session))

    curriculum = None
    slo_doc = reader.slo_document(session)
    if slo_doc is not None:
        validate_curriculum_document(slo_doc, "db:curriculum/slo")
        curriculum = CurriculumMap.model_validate(slo_doc)
    majors = None
    majors_doc = reader.majors_document(session)
    if majors_doc is not None:
        validate_majors_document(majors_doc, "db:curriculum/majors")
        majors = Majors.model_validate(majors_doc)
    return ConfigSnapshot(
        revision=revision,
        registry=registry,
        catalog=catalog,
        curriculum=curriculum,
        majors=majors,
        units=reader.units(session),
        task_git_sha=task_git_sha,
    )


class DbConfigProvider:
    """``IDA_CONFIG_SOURCE=db``: the tables, refreshed when the revision moves.

    The first :meth:`snapshot` builds synchronously and RAISES if it cannot --
    a process must not come up with no config.  After that, a failed rebuild
    keeps the previous snapshot and logs ERROR."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        refresh_s: float = 5.0,
        task_git_sha: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self._refresh_s = refresh_s
        self._task_git_sha = task_git_sha
        self._clock = clock
        self._lock = threading.Lock()
        self._current: ConfigSnapshot | None = None
        self._checked_at = float("-inf")

    def _build(self) -> ConfigSnapshot:
        with session_scope(self._session_factory) as session:
            return load_db_snapshot(session, task_git_sha=self._task_git_sha)

    def _latest_revision(self) -> int | None:
        with session_scope(self._session_factory) as session:
            return reader.current_revision(session)[0]

    def snapshot(self) -> ConfigSnapshot:
        current = self._current
        now = self._clock()
        if current is not None and now - self._checked_at < self._refresh_s:
            return current
        with self._lock:
            if self._current is None:
                self._current = self._build()
                self._checked_at = self._clock()
                log.info("config: loaded revision %s from the database", self._current.revision)
                return self._current
            if self._clock() - self._checked_at < self._refresh_s:
                return self._current
            self._checked_at = self._clock()
            try:
                latest = self._latest_revision()
                if latest == self._current.revision:
                    return self._current
                rebuilt = self._build()
            except Exception:
                log.exception(
                    "config: rebuild failed; still serving revision %s", self._current.revision
                )
                return self._current
            log.info("config: revision %s -> %s", self._current.revision, rebuilt.revision)
            self._current = rebuilt
            return rebuilt


def build_provider(
    settings: Settings, session_factory: sessionmaker[Session] | None = None
) -> ConfigProvider:
    """The provider ``IDA_CONFIG_SOURCE`` asks for.

    In db mode this ALSO runs :func:`ida_core.configdb.seed.ensure_seeded`
    first -- one call site for "seed if never seeded" instead of four callers
    each remembering it (api, runner, sweeps, regrade)."""
    if settings.config_source != "db":
        return YamlConfigProvider(settings)
    if session_factory is None:
        raise ValueError("IDA_CONFIG_SOURCE=db needs a database session factory")
    ensure_seeded(settings, session_factory)
    provider = DbConfigProvider(
        session_factory,
        refresh_s=settings.config_refresh_s,
        task_git_sha=current_git_sha(settings.resolved_tasks_dir()),
    )
    provider.snapshot()  # fail at startup, not on the first request
    return provider
