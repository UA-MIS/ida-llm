"""JSON Schema loading + validation for the two authored file formats.

There are deliberately **two** layers of checking and they do different jobs:

* **JSON Schema** (this module) -- structural, language-agnostic, and what CI
  runs over ``tasks/**/*.yaml`` and ``models.yaml`` without importing our code
  (the ``task-schema`` job in ``.github/workflows/ci.yml``).  It is the contract a non-Python
  contributor can read.
* **Pydantic** (:mod:`ida_core.contracts`) -- semantic cross-field rules that a
  schema expresses badly, e.g. "``scorer.rubric_id`` must equal ``rubric.id``".

A file that passes the schema but fails pydantic is a *bug in the schema*; keep
them in step.  ``tests/test_validation.py`` asserts both agree on the demo tasks.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import yaml

SCHEMA_DIR = Path(__file__).parent / "schemas"
TASK_SCHEMA_PATH = SCHEMA_DIR / "task.schema.json"
MODELS_SCHEMA_PATH = SCHEMA_DIR / "models.schema.json"


class ValidationError(ValueError):
    """Raised when an authored YAML file does not satisfy its schema.

    Carries ``path`` (the offending file) and ``errors`` (human-readable
    messages) so CI can print something actionable rather than a stack trace.
    """

    def __init__(self, path: Path | str, errors: list[str]) -> None:
        self.path = str(path)
        self.errors = errors
        joined = "\n  - ".join(errors)
        super().__init__(f"{self.path} failed validation:\n  - {joined}")


@lru_cache(maxsize=4)
def _load_schema(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def task_schema() -> dict[str, Any]:
    """The task JSON Schema as a dict."""
    return _load_schema(str(TASK_SCHEMA_PATH))


def models_schema() -> dict[str, Any]:
    """The models.yaml JSON Schema as a dict."""
    return _load_schema(str(MODELS_SCHEMA_PATH))


def _validate(document: Any, schema: dict[str, Any], source: Path | str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        messages = [
            f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
            for err in errors
        ]
        raise ValidationError(source, messages)


def validate_task_document(document: Any, source: Path | str = "<memory>") -> None:
    """Structurally validate one parsed task document.  Raises :class:`ValidationError`."""
    _validate(document, task_schema(), source)


def validate_models_document(document: Any, source: Path | str = "<memory>") -> None:
    """Structurally validate a parsed ``models.yaml``.  Raises :class:`ValidationError`."""
    _validate(document, models_schema(), source)


def load_yaml(path: Path | str) -> Any:
    """Read a YAML file with ``safe_load``.

    ``safe_load``, not ``load``: task files are authored content and must never
    be able to construct arbitrary Python objects.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def discover_task_files(tasks_dir: Path | str) -> list[Path]:
    """All task YAML files under ``tasks_dir``, sorted.

    Convention: any ``*.yaml``/``*.yml`` under the tree is a task, **except**
    files whose name starts with ``_`` (reserved for docs/partials, e.g.
    ``tasks/SCHEMA.md``'s companions).
    """
    root = Path(tasks_dir)
    if not root.is_dir():
        return []
    found = [
        p
        for pattern in ("**/*.yaml", "**/*.yml")
        for p in root.glob(pattern)
        if not p.name.startswith("_")
    ]
    return sorted(set(found))
