"""The DEV-ONLY demonstration curriculum is generated, consistent, and dev-only.

Three things this guards:

1. FRESHNESS. The committed `tasks-dev/`, `curriculum/majors.dev.yaml`,
   `curriculum/slo.dev.yaml` and `frontend/src/lib/demo-units.generated.ts` are
   exactly what `tools/gen_dev_curriculum.py` produces. Hand-editing one of the
   four without the others is the drift this exists to catch.

2. CONSISTENCY. The dev majors taxonomy, the dev coverage map and the dev task
   tree reconcile under the SAME rules `tools/validate_tasks.py` applies to the
   real ones -- a demo class claims only families that exist, every demo task's
   slo tag is a real outcome, and MIS 200's real families are untouched.

3. DEV-ONLY. Not one demo family or demo task_families claim is in the committed
   `tasks/` or `curriculum/majors.yaml`, so nothing demo can reach the prod
   image's effective curriculum. (The chart-render test proves the env side.)
"""

from __future__ import annotations

import importlib.util
import pathlib

import yaml

from ida_core.curriculum import check_task_tags, load_curriculum
from ida_core.majors import check_against_curriculum, check_task_families, load_majors
from ida_harness.tasks import TaskCatalog

REPO = pathlib.Path(__file__).resolve().parents[2]


def _gen():
    spec = importlib.util.spec_from_file_location(
        "gen_dev_curriculum", REPO / "tools" / "gen_dev_curriculum.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _gen()


# --------------------------------------------------------------------------
# 1. Freshness — committed output == freshly generated
# --------------------------------------------------------------------------


def _read(p: pathlib.Path) -> str:
    return p.read_text()


def test_committed_dev_curriculum_is_freshly_generated(tmp_path):
    # Generate into a throwaway tree, then compare file-for-file with what is
    # committed. Any difference means someone edited a generated file by hand or
    # changed the spec without re-running the generator.
    tasks_dir = tmp_path / "tasks-dev"
    tasks_dir.mkdir()
    gen.write_tasks(tasks_dir)
    gen.write_majors_dev(tmp_path / "majors.dev.yaml")
    gen.write_slo_dev(tmp_path / "slo.dev.yaml")
    gen.write_demo_units_ts(tmp_path / "demo-units.generated.ts")

    stale = []
    # task files
    committed_tasks = REPO / "tasks-dev"
    gen_files = {p.relative_to(tasks_dir) for p in tasks_dir.rglob("*.yaml")}
    com_files = {p.relative_to(committed_tasks) for p in committed_tasks.rglob("*.yaml")}
    if gen_files != com_files:
        stale.append(
            f"task file set differs: only-committed={com_files - gen_files}, "
            f"only-generated={gen_files - com_files}"
        )
    for rel in gen_files & com_files:
        if _read(tasks_dir / rel) != _read(committed_tasks / rel):
            stale.append(f"tasks-dev/{rel} is stale")

    pairs = [
        (tmp_path / "majors.dev.yaml", REPO / "curriculum" / "majors.dev.yaml"),
        (tmp_path / "slo.dev.yaml", REPO / "curriculum" / "slo.dev.yaml"),
        (
            tmp_path / "demo-units.generated.ts",
            REPO / "frontend" / "src" / "lib" / "demo-units.generated.ts",
        ),
    ]
    for gen_file, com_file in pairs:
        if not com_file.is_file() or _read(gen_file) != _read(com_file):
            stale.append(f"{com_file.name} is stale")

    assert not stale, (
        "committed dev curriculum is out of date -- run `python3 tools/gen_dev_curriculum.py`:\n  "
        + "\n  ".join(stale)
    )


# --------------------------------------------------------------------------
# 2. Consistency — the dev curriculum reconciles like the real one
# --------------------------------------------------------------------------


def _dev_task_families() -> set[str]:
    real = {p.name for p in (REPO / "tasks").iterdir() if p.is_dir()}
    demo = {p.name for p in (REPO / "tasks-dev").iterdir() if p.is_dir()}
    return real | demo


def test_dev_majors_reconcile_with_dev_curriculum():
    majors = load_majors(REPO / "curriculum" / "majors.dev.yaml")
    curriculum = load_curriculum(REPO / "curriculum" / "slo.dev.yaml")
    assert check_against_curriculum(majors, curriculum) == []
    assert check_task_families(majors, _dev_task_families()) == []


def test_every_demo_task_is_valid_and_its_slo_is_real():
    curriculum = load_curriculum(REPO / "curriculum" / "slo.dev.yaml")
    specs = list(TaskCatalog.from_directory(REPO / "tasks-dev").all())
    assert specs, "no demo tasks generated"
    errors: list[str] = []
    for spec in specs:
        errors.extend(check_task_tags(spec, curriculum))
    assert errors == [], errors


def test_mis200_real_families_are_untouched_in_dev_majors():
    majors = load_majors(REPO / "curriculum" / "majors.dev.yaml")
    mis200 = next(c for m in majors.majors for c in m.classes if c.course == "MIS 200")
    assert mis200.task_families == [
        "mis200-spreadsheet-formulas",
        "mis200-is-concepts",
        "mis200-is-problem-solving",
    ]


# --------------------------------------------------------------------------
# 3. Dev-only — nothing demo is in the committed prod curriculum
# --------------------------------------------------------------------------


def test_no_demo_family_is_in_the_committed_tasks_tree():
    real = {p.name for p in (REPO / "tasks").iterdir() if p.is_dir()}
    assert not any(name.startswith("demo-") for name in real), (
        "a demo-* family is in the committed tasks/ tree; it would ship into the prod catalogue"
    )


def test_no_demo_task_families_claim_is_in_the_committed_majors_yaml():
    doc = yaml.safe_load((REPO / "curriculum" / "majors.yaml").read_text())
    for major in doc["majors"]:
        for klass in major.get("classes") or []:
            for fam in klass.get("task_families") or []:
                assert not fam.startswith("demo-"), (
                    f"{klass['course']} claims demo family {fam!r} in the committed majors.yaml; "
                    "demo claims belong only in majors.dev.yaml"
                )
