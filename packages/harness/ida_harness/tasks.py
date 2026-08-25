"""Task loading: ``tasks/**/*.yaml`` -> :class:`~ida_core.contracts.TaskSpec`.

Loading always runs *both* validation layers (JSON Schema then pydantic) -- see
:mod:`ida_core.validation` for why there are two.  A task that fails either one
is a hard error: we would rather fail a run than benchmark against a task whose
meaning we are guessing at.
"""

from __future__ import annotations

from pathlib import Path

from ida_core.contracts import TaskSpec
from ida_core.validation import (
    ValidationError,
    discover_task_files,
    load_yaml,
    validate_task_document,
)
from ida_harness.errors import TaskLoadError


def load_task_file(path: Path | str) -> TaskSpec:
    """Load and fully validate one task file.

    Raises :class:`~ida_harness.errors.TaskLoadError` for anything wrong with
    the file: missing, unparseable YAML, schema violation, or a semantic rule
    (e.g. a verifiable sample without a target).
    """
    path = Path(path)
    if not path.is_file():
        raise TaskLoadError(f"task file not found: {path}")
    try:
        document = load_yaml(path)
    except Exception as exc:
        raise TaskLoadError(f"{path}: could not parse YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise TaskLoadError(
            f"{path}: top level must be a mapping, got {type(document).__name__}"
        )
    try:
        validate_task_document(document, path)
    except ValidationError as exc:
        raise TaskLoadError(str(exc)) from exc
    try:
        # from_document, not model_validate: it stamps content_sha, which is the
        # per-task comparability key and the completion cache's key material (B8).
        return TaskSpec.from_document(document)
    except Exception as exc:
        raise TaskLoadError(f"{path}: {exc}") from exc


class TaskCatalog:
    """Every task under a directory, indexed by :attr:`TaskSpec.id`.

    Built eagerly at service startup so that a malformed task file is a
    *startup* failure, loudly, rather than a mystery at run time.  Duplicate
    task ids across files are an error -- ids are how runs refer to tasks.
    """

    def __init__(self, tasks: dict[str, TaskSpec], sources: dict[str, Path]) -> None:
        self._tasks = tasks
        self._sources = sources

    @classmethod
    def from_directory(cls, tasks_dir: Path | str) -> TaskCatalog:
        """Discover, load and validate every task file under ``tasks_dir``."""
        tasks: dict[str, TaskSpec] = {}
        sources: dict[str, Path] = {}
        for path in discover_task_files(tasks_dir):
            spec = load_task_file(path)
            if spec.id in tasks:
                raise TaskLoadError(
                    f"duplicate task id {spec.id!r}: {sources[spec.id]} and {path}"
                )
            tasks[spec.id] = spec
            sources[spec.id] = path
        return cls(tasks, sources)

    def get(self, task_id: str) -> TaskSpec:
        """Look up by task id.  Raises ``KeyError`` if absent."""
        try:
            return self._tasks[task_id]
        except KeyError:
            raise KeyError(f"no task with id {task_id!r}") from None

    def source_of(self, task_id: str) -> Path:
        """The file a task was loaded from.  Useful in error messages."""
        return self._sources[task_id]

    def ids(self) -> list[str]:
        return sorted(self._tasks)

    def all(self) -> list[TaskSpec]:
        return [self._tasks[i] for i in self.ids()]

    def __len__(self) -> int:
        return len(self._tasks)

    def __contains__(self, task_id: object) -> bool:
        return task_id in self._tasks
