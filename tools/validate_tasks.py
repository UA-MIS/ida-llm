#!/usr/bin/env python3
"""Validate every authored YAML file against its JSON Schema, then its contract.

This is what the ``task-schema`` job in ``.github/workflows/ci.yml`` runs and what ``make lint-tasks``
runs locally. It deliberately checks BOTH layers (see
``ida_core.validation``'s module docstring) and reports every failure rather
than stopping at the first, so a contributor fixing task files gets the whole
list in one pass.

Exit codes: 0 all valid, 1 one or more invalid.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ida_core.contracts import ModelRegistry, TaskSpec
from ida_core.validation import (
    ValidationError,
    discover_task_files,
    load_yaml,
    validate_models_document,
    validate_task_document,
)

OK = "  ok"
BAD = "FAIL"


def _check_models(path: Path) -> list[str]:
    if not path.exists():
        return [f"{path}: not found"]
    try:
        document = load_yaml(path)
        validate_models_document(document, path)
        registry = ModelRegistry.model_validate(document)
    except (ValidationError, ValueError) as exc:
        return [str(exc)]
    print(f"{OK}  {path}  ({len(registry.models)} model(s), enabled: {registry.enabled_keys()})")
    return []


def _check_tasks(tasks_dir: Path) -> list[str]:
    files = discover_task_files(tasks_dir)
    if not files:
        return [f"{tasks_dir}: no task files found"]

    errors: list[str] = []
    seen: dict[str, Path] = {}
    for path in files:
        try:
            document = load_yaml(path)
            validate_task_document(document, path)
            spec = TaskSpec.model_validate(document)
        except (ValidationError, ValueError) as exc:
            errors.append(str(exc))
            continue
        if spec.id in seen:
            errors.append(f"duplicate task id {spec.id!r}: {seen[spec.id]} and {path}")
            continue
        seen[spec.id] = path
        scorable = "scorable" if spec.is_scorable else "NOT YET SCORABLE"
        print(
            f"{OK}  {path}  ({spec.kind.value}, {spec.scorer.kind.value}, "
            f"{len(spec.samples)} sample(s), {scorable})"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    print(f"Validating authored content under {root}\n")
    errors = _check_models(root / "models.yaml") + _check_tasks(root / "tasks")

    if errors:
        print(f"\n{BAD}  {len(errors)} problem(s):\n", file=sys.stderr)
        for error in errors:
            print(f"  * {error}\n", file=sys.stderr)
        return 1

    print("\nAll authored content is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
