#!/usr/bin/env python3
"""Schema-validate tasks/**/*.yaml and models.yaml.

WHY THIS IS A REAL GATE AND NOT A STUB. Task definitions and rubrics are the
capstone's actual data: every benchmark result cites the git SHA of the task that
produced it, and that citation is worth nothing if the file was malformed. The
expensive failure mode is not "the YAML is broken" -- it is a rubric that points
at a `judge_model` somebody renamed in models.yaml three commits ago, discovered
an hour into a paid inference run. Rule 7 below is the one that catches that.

Dependency-light on purpose (PyYAML only): it must run in whatever container CI
happens to give it, without a resolver step.

Usage:
    python tools/validate_tasks.py                 # repo root auto-detected
    python tools/validate_tasks.py --root <path>
    ida-validate-tasks                             # console script, same thing

Exit codes: 0 = every file valid, 1 = at least one problem (each printed with its
file and a specific reason), 2 = usage/IO error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment problem, not a data problem
    print("error: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2) from exc

API_VERSION = "ida.capstone/v1"
SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
RUBRIC_KINDS = {"exact", "contains", "numeric", "judge"}
PROVIDERS = {"mock", "anthropic", "openai", "openai-compatible"}


class Problems(list):
    """Collected findings. Every entry names a file AND a specific reason."""

    def add(self, path: Path, message: str) -> None:
        self.append(f"{path}: {message}")


def _require(problems, path, condition, message) -> bool:
    if not condition:
        problems.add(path, message)
        return False
    return True


def validate_models(path: Path, problems: Problems) -> set[str]:
    """Validate models.yaml. Returns the set of declared model ids."""
    if not path.exists():
        problems.add(path, "models.yaml not found")
        return set()

    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        problems.add(path, f"not valid YAML: {exc}")
        return set()

    if not _require(problems, path, isinstance(doc, dict), "top level must be a mapping"):
        return set()
    _require(
        problems,
        path,
        doc.get("apiVersion") == API_VERSION,
        f"apiVersion must be {API_VERSION!r}, got {doc.get('apiVersion')!r}",
    )

    models = doc.get("models")
    if not _require(
        problems, path, isinstance(models, list) and models, "`models` must be a non-empty list"
    ):
        return set()

    ids: set[str] = set()
    for index, model in enumerate(models):
        where = f"models[{index}]"
        if not isinstance(model, dict):
            problems.add(path, f"{where} must be a mapping")
            continue

        model_id = model.get("id")
        if not (isinstance(model_id, str) and SLUG.match(model_id)):
            problems.add(path, f"{where}.id must be a slug ([a-z0-9-]), got {model_id!r}")
        elif model_id in ids:
            problems.add(path, f"{where}.id {model_id!r} is a duplicate")
        else:
            ids.add(model_id)

        provider = model.get("provider")
        _require(
            problems,
            path,
            provider in PROVIDERS,
            f"{where}.provider must be one of {sorted(PROVIDERS)}, got {provider!r}",
        )
        _require(
            problems,
            path,
            isinstance(model.get("model"), str) and model["model"].strip(),
            f"{where}.model must be a non-empty string",
        )

        max_tokens = model.get("max_tokens")
        _require(
            problems,
            path,
            isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and max_tokens > 0,
            f"{where}.max_tokens must be a positive integer, got {max_tokens!r}",
        )

        temperature = model.get("temperature")
        _require(
            problems,
            path,
            isinstance(temperature, (int, float))
            and not isinstance(temperature, bool)
            and 0 <= temperature <= 2,
            f"{where}.temperature must be a number in [0, 2], got {temperature!r}",
        )

        # RULE 8 -- the one that stops a pasted credential. These fields name an
        # ENVIRONMENT VARIABLE; the value arrives from Vault via ESO at runtime.
        # A real key is not uppercase-with-underscores, so this catches the paste.
        for field in ("api_key_env", "base_url_env"):
            value = model.get(field)
            if value is None:
                continue
            if not (isinstance(value, str) and ENV_NAME.match(value)):
                problems.add(
                    path,
                    f"{where}.{field} must be an ENV VAR NAME ([A-Z0-9_]), got {value!r} "
                    f"-- secrets belong in Vault, never in this file",
                )
    return ids


def validate_task(path: Path, model_ids: set[str], seen_ids: dict, problems: Problems) -> None:
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        problems.add(path, f"not valid YAML: {exc}")
        return

    if not _require(problems, path, isinstance(doc, dict), "top level must be a mapping"):
        return

    _require(
        problems,
        path,
        doc.get("apiVersion") == API_VERSION,
        f"apiVersion must be {API_VERSION!r}, got {doc.get('apiVersion')!r}",
    )
    _require(
        problems, path, doc.get("kind") == "Task", f"kind must be 'Task', got {doc.get('kind')!r}"
    )

    task_id = doc.get("id")
    if not (isinstance(task_id, str) and SLUG.match(task_id)):
        problems.add(path, f"id must be a slug ([a-z0-9-]), got {task_id!r}")
    else:
        # RULE 2 -- id matches the filename stem, so a result citing an id can be
        # traced straight back to a path without a lookup table.
        if task_id != path.stem:
            problems.add(path, f"id {task_id!r} must match the filename stem {path.stem!r}")
        if task_id in seen_ids:
            problems.add(path, f"id {task_id!r} is already used by {seen_ids[task_id]}")
        else:
            seen_ids[task_id] = path

    version = doc.get("version")
    _require(
        problems,
        path,
        isinstance(version, int) and not isinstance(version, bool) and version > 0,
        f"version must be a positive integer, got {version!r}",
    )
    _require(
        problems,
        path,
        isinstance(doc.get("title"), str) and doc["title"].strip(),
        "title must be a non-empty string",
    )
    _require(
        problems,
        path,
        isinstance(doc.get("prompt"), str) and doc["prompt"].strip(),
        "prompt must be non-empty",
    )

    rubric = doc.get("rubric")
    if not _require(problems, path, isinstance(rubric, dict), "rubric must be a mapping"):
        return

    kind = rubric.get("kind")
    if not _require(
        problems,
        path,
        kind in RUBRIC_KINDS,
        f"rubric.kind must be one of {sorted(RUBRIC_KINDS)}, got {kind!r}",
    ):
        return

    # RULE 6 -- gold is required for every kind EXCEPT judge, and forbidden for
    # judge. Enforced in BOTH directions: a judge rubric carrying a `gold` is a
    # sign someone converted a task and left the old answer behind, which reads
    # as authoritative and is not.
    if kind == "judge":
        if "gold" in doc:
            problems.add(
                path, "rubric.kind 'judge' must not carry `gold` (no single reference answer)"
            )
    elif "gold" not in doc:
        problems.add(path, f"rubric.kind {kind!r} requires a top-level `gold`")

    if kind == "contains":
        any_of = rubric.get("any_of")
        _require(
            problems,
            path,
            isinstance(any_of, list)
            and any_of
            and all(isinstance(x, str) and x.strip() for x in any_of),
            "rubric.any_of must be a non-empty list of non-empty strings",
        )
    elif kind == "numeric":
        tolerance = rubric.get("tolerance")
        _require(
            problems,
            path,
            isinstance(tolerance, (int, float))
            and not isinstance(tolerance, bool)
            and tolerance >= 0,
            f"rubric.tolerance must be a number >= 0, got {tolerance!r}",
        )
        gold = doc.get("gold")
        _require(
            problems,
            path,
            isinstance(gold, (int, float)) and not isinstance(gold, bool),
            f"rubric.kind 'numeric' requires a numeric `gold`, got {gold!r}",
        )
    elif kind == "exact":
        case_sensitive = rubric.get("case_sensitive", False)
        _require(
            problems,
            path,
            isinstance(case_sensitive, bool),
            f"rubric.case_sensitive must be a bool, got {case_sensitive!r}",
        )
    elif kind == "judge":
        criteria = rubric.get("criteria")
        _require(
            problems,
            path,
            isinstance(criteria, list)
            and criteria
            and all(isinstance(x, str) and x.strip() for x in criteria),
            "rubric.criteria must be a non-empty list of non-empty strings",
        )
        # RULE 7 -- the expensive one. A judge_model that no longer exists in
        # models.yaml fails HERE, in CI, instead of an hour into a paid run.
        judge_model = rubric.get("judge_model")
        if not isinstance(judge_model, str) or not judge_model:
            problems.add(path, "rubric.judge_model is required for rubric.kind 'judge'")
        elif model_ids and judge_model not in model_ids:
            problems.add(
                path,
                f"rubric.judge_model {judge_model!r} is not declared in models.yaml "
                f"(known ids: {', '.join(sorted(model_ids)) or 'none'})",
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root", type=Path, default=None, help="repo root (default: the parent of tools/)"
    )
    args = parser.parse_args(argv)

    root = args.root or Path(__file__).resolve().parent.parent
    tasks_dir = root / "tasks"
    problems = Problems()

    model_ids = validate_models(root / "models.yaml", problems)

    task_files = sorted(p for p in tasks_dir.rglob("*.yaml") if p.is_file())
    # An EMPTY suite must not pass. A gate that proves nothing is worse than no
    # gate, because it reports green.
    if not task_files:
        problems.add(tasks_dir, "no task files found -- the schema gate would pass vacuously")

    seen_ids: dict = {}
    for task_file in task_files:
        validate_task(task_file, model_ids, seen_ids, problems)

    if problems:
        print(f"FAIL  {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"OK  {len(task_files)} task(s), {len(model_ids)} model(s) -- schema valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
