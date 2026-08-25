"""Load and represent task definitions.

The on-disk schema is documented in tasks/SCHEMA.md and enforced by
tools/validate_tasks.py in CI. This loader assumes VALID input -- the gate runs
first, on every PR -- but still fails loudly rather than silently skipping a
malformed file, because "the suite got smaller" is the kind of bug that quietly
makes every score look better.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Task:
    id: str
    version: int
    title: str
    category: str
    prompt: str
    rubric: dict[str, Any]
    gold: Any = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Task:
        return cls(
            id=doc["id"],
            version=doc["version"],
            title=doc["title"],
            category=doc.get("category", "uncategorized"),
            prompt=doc["prompt"],
            rubric=doc["rubric"],
            gold=doc.get("gold"),
            tags=list(doc.get("tags", [])),
        )


def load_tasks(tasks_dir: Path | str) -> list[Task]:
    """Load every task under `tasks_dir`, sorted by id for deterministic runs.

    Deterministic ordering matters more than it looks: an unordered suite makes
    two runs of the same commit produce transcripts that diff for no reason,
    which destroys the "cite the SHA and re-run it" property.
    """
    root = Path(tasks_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"task directory not found: {root}")

    tasks: list[Task] = []
    for path in sorted(root.rglob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        if not isinstance(doc, dict) or doc.get("kind") != "Task":
            raise ValueError(f"{path}: not a Task document (run tools/validate_tasks.py)")
        tasks.append(Task.from_dict(doc))

    if not tasks:
        raise ValueError(f"no tasks found under {root} -- an empty suite scores vacuously")
    return sorted(tasks, key=lambda t: t.id)
