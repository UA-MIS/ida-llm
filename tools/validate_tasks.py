#!/usr/bin/env python3
"""Validate every authored YAML file against its JSON Schema, then its contract.

This is what the ``task-schema`` job in ``.github/workflows/ci.yml`` runs and what ``make lint-tasks``
runs locally. It deliberately checks BOTH layers (see
``ida_core.validation``'s module docstring) and reports every failure rather
than stopping at the first, so a contributor fixing task files gets the whole
list in one pass.

Four authored formats are checked: ``models.yaml``, ``curriculum/slo.yaml``,
``curriculum/majors.yaml`` and ``tasks/**/*.yaml`` -- plus the rules that span
more than one of them.

The cross-file rules
--------------------
An SLO-anchored task carries ``slo:<ID>`` and ``use-mode:<id>`` tags, and this
is the only place they can be checked: nothing in a task file knows which
outcomes exist. An ``slo:SL02`` typo is not a loud failure anywhere else --
the task loads, the run succeeds, the score is real, and it is filed under a
heading that does not exist, so it vanishes from every per-outcome view without
producing an error. Checking it here turns that into a failed pull request.
See ``ida_core.curriculum.check_task_tags``.

The second spans the two curriculum files. ``curriculum/majors.yaml`` says which
classes exist and whose they are; ``curriculum/slo.yaml`` says which outcomes a
class teaches. They join on the course code, and the join is where the silent
failures live: a class neither file can name renders as a nameless column, and a
coverage course no major claims becomes unreachable from the drill-down -- which
would quietly delete ``MIS 200``, the only class in the product with a scored
benchmark behind it, from every path a reader can walk. See
``ida_core.majors.check_against_curriculum``.

Exit codes: 0 all valid, 1 one or more invalid.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ida_core.contracts import ModelRegistry, TaskSpec
from ida_core.curriculum import (
    BENCHMARK_TAG,
    CurriculumMap,
    check_task_tags,
    default_curriculum_path,
    load_curriculum,
)
from ida_core.majors import (
    Majors,
    check_against_curriculum,
    check_task_families,
    default_majors_path,
    load_majors,
    title_disagreements,
)
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


def _check_curriculum(path: Path) -> tuple[CurriculumMap | None, list[str]]:
    """Load the curriculum map, or report why it could not be loaded.

    Returns the map so the task pass can check tags against it. A ``None`` map
    does NOT downgrade the task pass to "tags unchecked and therefore fine":
    :func:`_check_tasks` refuses SLO-tagged tasks outright in that case, because
    "we could not check" and "we checked and it was clean" must never print the
    same.
    """
    try:
        curriculum = load_curriculum(path)
    except ValidationError as exc:
        return None, [str(exc)]
    print(
        f"{OK}  {path}  ({len(curriculum.outcomes)} outcome(s), "
        f"{len(curriculum.text_benchmarkable_ids())} text-benchmarkable, "
        f"{len(curriculum.coverage)} course(s), "
        f"use modes in use: {curriculum.in_use_mode_ids()})"
    )
    return curriculum, []


def _task_families(tasks_dir: Path) -> set[str]:
    """Every family the task catalogue actually has.

    Read off the FILESYSTEM rather than off the parsed specs: this is used to
    check the majors taxonomy, which must still be checkable when an unrelated
    task file fails to parse. A family IS a directory under ``tasks/`` -- that
    is the repo's own convention, and the same one a task id's leading segment
    follows (``mis200-is-concepts/l1-core-is-concepts``).
    """
    if not tasks_dir.is_dir():
        return set()
    return {entry.name for entry in tasks_dir.iterdir() if entry.is_dir()}


def _check_majors(
    path: Path, curriculum: CurriculumMap | None, task_families: set[str]
) -> list[str]:
    """Load the majors taxonomy and reconcile it against the curriculum map.

    An ABSENT file is not an error: a deployment can run without the taxonomy
    (the drill-down says so and degrades to the outcome views), and making a new
    optional file mandatory would fail every checkout that has not pulled it.
    A file that is present and broken IS an error -- the failure mode this gate
    exists for is a taxonomy that looks fine on its own and contradicts the map.
    """
    if not path.exists():
        print(f"{OK}  {path}  (absent; the drill-down falls back to outcome views)")
        return []
    try:
        majors: Majors = load_majors(path)
    except ValidationError as exc:
        return [str(exc)]

    class_count = sum(len(m.classes) for m in majors.majors)
    print(
        f"{OK}  {path}  ({len(majors.majors)} major(s), {class_count} class(es), "
        f"{len(majors.unassigned_core)} core course(s) no major owns)"
    )

    if curriculum is None:
        # Same rule as the task pass: "we could not check" must never print the
        # same as "we checked and it was clean".
        return [
            f"{path}: the curriculum map failed to load, so the majors taxonomy could not be "
            "reconciled against it; fix the curriculum error above"
        ]

    # Reported, never gated -- see `title_disagreements`. The catalog is the
    # authority on titles and the map abbreviates them, so a difference is
    # expected; printing it is what makes a difference that IS a mistake visible.
    for course, catalog_title, map_title in title_disagreements(majors, curriculum):
        print(f"      {course}: catalog says {catalog_title!r}, curriculum map says {map_title!r}")

    problems = check_against_curriculum(majors, curriculum) + check_task_families(
        majors, task_families
    )
    return [f"{path}: {problem}" for problem in problems]


def _check_tasks(tasks_dir: Path, curriculum: CurriculumMap | None) -> list[str]:
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

        if curriculum is not None:
            errors.extend(f"{path}: {problem}" for problem in check_task_tags(spec, curriculum))
        elif BENCHMARK_TAG in spec.tags or any(
            t.startswith(("slo:", "use-mode:")) for t in spec.tags
        ):
            errors.append(
                f"{path}: is SLO-tagged but the curriculum map failed to load, so its tags "
                "could not be checked; fix the curriculum error above"
            )

        scorable = "scorable" if spec.is_scorable else "NOT YET SCORABLE"
        slo = next((t for t in spec.tags if t.startswith("slo:")), None)
        anchor = f", {slo}" if slo else ""
        print(
            f"{OK}  {path}  ({spec.kind.value}, {spec.scorer.kind.value}, "
            f"{len(spec.samples)} sample(s), {scorable}{anchor})"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    print(f"Validating authored content under {root}\n")
    curriculum, curriculum_errors = _check_curriculum(default_curriculum_path(root))
    errors = (
        _check_models(root / "models.yaml")
        + curriculum_errors
        + _check_majors(default_majors_path(root), curriculum, _task_families(root / "tasks"))
        + _check_tasks(root / "tasks", curriculum)
    )

    if errors:
        print(f"\n{BAD}  {len(errors)} problem(s):\n", file=sys.stderr)
        for error in errors:
            print(f"  * {error}\n", file=sys.stderr)
        return 1

    print("\nAll authored content is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
