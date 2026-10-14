#!/usr/bin/env python3
"""Generate the DEV-ONLY demonstration curriculum from one spec.

WHY A GENERATOR. The populated-demo dev site needs the same family name in four
places that must agree exactly: the demo task files (so the catalogue has
samples to seed), ``curriculum/majors.dev.yaml`` (so a class CLAIMS the family —
the #79 rule: a class scores only on families it claims), ``curriculum/slo.dev
.yaml`` (coverage for classes the real map does not list), and the frontend unit
taxonomy (so the class page breaks the family into a named unit). Hand-syncing
four files is how they drift. This script is the single source of truth; a
freshness test (``tools/tests/test_dev_curriculum.py``) re-runs it and fails if
the committed output is stale.

STRICTLY DEV-ONLY. Everything it writes is loaded only when the dev overlay sets
IDA_MAJORS_FILE / IDA_CURRICULUM_FILE / IDA_TASKS_DIR / IDA_DEMO_CURRICULUM.
Staging and prod set none of them, so not one demo family, class-claim, coverage
row or unit reaches their effective curriculum — the chart-render test asserts
exactly that, both directions.

HONESTY. The demo task CONTENT is openly illustrative: synthetic placeholder
items, ``provenance: synthetic``, a description that says it is not an ingest of
any real instrument. The SCORES shown against it on dev are seeded and carry the
demonstration flag the UI renders as "illustrative". Nothing here fabricates a
real measurement or reproduces any real course material.

Run: ``python3 tools/gen_dev_curriculum.py`` (writes under the repo root).
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# THE SPEC. course code -> the units the dev site shows for it, each a
# (title, covers, blurb, slo). The family for unit N of a class is
# demo-<ckey>-u<N>, derived below, so the spec is the only thing to edit.
#
# MIS 200 is ABSENT on purpose: it is the one REAL class, its units live in the
# committed frontend taxonomy and its families are real. These are the OTHER
# classes the dev site fills with illustrative data. Every class here already
# exists in curriculum/majors.yaml; MIS 221 / MIS 330 are the only two the real
# coverage map does not list, so they get a dev-only coverage row (below).
# --------------------------------------------------------------------------
DEMO_UNITS: dict[str, list[tuple[str, list[str], str, str]]] = {
    "AC 210": [
        (
            "Financial statement foundations",
            ["The accounting equation", "Balance sheet vs income statement", "Accruals"],
            "What the core financial statements report and how they fit together.",
            "SLO9",
        ),
        (
            "Transaction analysis",
            ["Debits and credits", "Journal entries", "Trial balance"],
            "Recording business transactions and reading their effect on the books.",
            "SLO2",
        ),
    ],
    "ST 260": [
        (
            "Descriptive statistics",
            ["Centre and spread", "Distributions", "Reading a dataset"],
            "Summarising a business dataset before any inference is drawn from it.",
            "SLO2",
        ),
        (
            "Probability and inference",
            ["Sampling", "Confidence intervals", "Hypothesis tests"],
            "Reasoning from a sample to a claim about the population behind it.",
            "SLO2",
        ),
    ],
    "EC 110": [
        (
            "Microeconomic principles",
            ["Scarcity and tradeoffs", "Supply and demand", "Elasticity"],
            "The core model of how prices and quantities are set in a market.",
            "SLO9",
        ),
        (
            "Markets and incentives",
            ["Marginal analysis", "Incentives", "Market outcomes"],
            "How rational responses to incentives aggregate into market behaviour.",
            "SLO2",
        ),
    ],
    "FI 302": [
        (
            "Time value of money",
            ["Present value", "Future value", "Discounting cash flows"],
            "Valuing money across time — the foundation of every finance decision.",
            "SLO2",
        ),
        (
            "Risk and return",
            ["Expected return", "Diversification", "Risk measures"],
            "Trading expected return against risk in an investment decision.",
            "SLO2",
        ),
    ],
    "GBA 146": [
        (
            "Business foundations",
            ["Forms of business", "Functional areas", "Business vocabulary"],
            "The shared vocabulary and structure the rest of the core builds on.",
            "SLO9",
        ),
        (
            "Professional communication",
            ["Audience", "Structure", "Clear business writing"],
            "Writing a clear, well-structured message for a business reader.",
            "SLO7",
        ),
    ],
    "GBA 300": [
        (
            "Cross-functional cases",
            ["Framing a problem", "Weighing options", "Recommending an action"],
            "Appraising a business situation that crosses functional boundaries.",
            "SLO1",
        ),
        (
            "Business writing",
            ["Argument", "Evidence", "Executive summary"],
            "Making an evidence-backed written recommendation a manager can act on.",
            "SLO7",
        ),
    ],
    "MGT 300": [
        (
            "Organizational behavior",
            ["Motivation", "Organisational structure", "Decision making"],
            "How individuals and structures shape what an organisation does.",
            "SLO9",
        ),
        (
            "Management concepts",
            ["Planning", "Organising", "Controlling"],
            "The core functions of management, named and distinguished.",
            "SLO9",
        ),
    ],
    "MKT 300": [
        (
            "Marketing concepts",
            ["The marketing mix", "Segmentation", "Positioning"],
            "The vocabulary of marketing strategy and what each term decides.",
            "SLO9",
        ),
        (
            "Consumer and market analysis",
            ["Consumer behaviour", "Market research", "Cultural context"],
            "Reading a market and the buyers in it, in their own context.",
            "SLO4",
        ),
    ],
    "OM 300": [
        (
            "Process analysis",
            ["Process flow", "Bottlenecks", "Capacity"],
            "Reading a process as a flow and finding where it is constrained.",
            "SLO2",
        ),
        (
            "Quality and operations",
            ["Quality concepts", "Inventory basics", "Operations strategy"],
            "The concepts that govern how operations are run and improved.",
            "SLO9",
        ),
    ],
    "MIS 221": [
        (
            "Programming fundamentals",
            ["Variables", "Control flow", "Functions"],
            "The building blocks of a program, before any one language's syntax.",
            "SLO1",
        ),
        (
            "Data types and logic",
            ["Types", "Boolean logic", "Tracing code"],
            "Reasoning about what a small piece of code computes.",
            "SLO9",
        ),
    ],
    "MIS 330": [
        (
            "Database concepts",
            ["Tables and keys", "Relationships", "Normalisation basics"],
            "How a relational database organises data without redundancy.",
            "SLO9",
        ),
        (
            "Querying and data modelling",
            ["SELECT basics", "Joins", "Modelling a domain"],
            "Asking questions of data and modelling a domain as tables.",
            "SLO2",
        ),
    ],
}

# MIS 221 / MIS 330 are not in the real coverage map (it is the business core,
# not the MIS subject listing). A dev-only coverage row lets the class page show
# "teaches N outcomes" instead of "not in the published map". Levels are
# illustrative (I=introduced, R=reinforced).
DEMO_COVERAGE: dict[str, tuple[str, dict[str, str]]] = {
    "MIS 221": ("Business Programming I", {"SLO1": "I", "SLO9": "I"}),
    "MIS 330": ("Database Administration", {"SLO9": "R", "SLO2": "R"}),
}

GENERATED_BANNER = (
    "# GENERATED by tools/gen_dev_curriculum.py — DEV ONLY. Do not hand-edit.\n"
    "# Loaded only when the dev overlay sets the matching IDA_* override; staging\n"
    "# and prod never do. See the generator's module docstring.\n"
)


def ckey(course: str) -> str:
    return course.lower().replace(" ", "")


def family(course: str, n: int) -> str:
    return f"demo-{ckey(course)}-u{n}"


def unit_key(title: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in title.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def task_doc(course: str, n: int, title: str, slo: str) -> dict:
    fam = family(course, n)
    samples = []
    for i, letter in enumerate(["A", "B", "C", "D"], start=1):
        samples.append(
            {
                "id": f"item-{i}",
                "input": (
                    f"Illustrative demonstration item {i} for {course} — unit “{title}”. "
                    "This is synthetic placeholder content shown to demonstrate the benchmark "
                    "layout; it is not a real exam question. Which option is marked correct for "
                    "this demonstration item?\n"
                    "A) Alpha\nB) Bravo\nC) Charlie\nD) Delta"
                ),
                "target": letter,
                "metadata": {
                    "skill": "demonstration",
                    "provenance": "synthetic",
                    "slo": slo,
                    "use_mode": "capability",
                },
            }
        )
    return {
        "version": 1,
        "id": f"{fam}/items",
        "title": f"{title} — illustrative demonstration items",
        "description": (
            f"Synthetic placeholder items for {course}, unit “{title}”. NOT an ingest "
            "of any real instrument: the content is illustrative, the provenance is synthetic, "
            "and the scores shown against it on the dev site are seeded demonstration figures, "
            "not measurements. No real course material, exam or answer key is reproduced.\n"
        ),
        "kind": "verifiable",
        "domain": "demonstration",
        "system_prompt": (
            "You are answering a multiple-choice demonstration item. Put the letter of the "
            "correct option alone on the last line, with no other text on that line."
        ),
        "scorer": {
            "kind": "exact_match",
            "normalisation": {
                "take_last_line": True,
                "strip": True,
                "collapse_whitespace": True,
                "strip_punctuation": True,
                "lowercase": True,
            },
        },
        "tags": [
            "slo-benchmark",
            f"slo:{slo}",
            "use-mode:capability",
            fam,
            "demonstration",
            "synthetic",
        ],
        "samples": samples,
    }


def write_tasks(tasks_dir: pathlib.Path) -> list[str]:
    """Write every demo task file. Returns the family names written."""
    families: list[str] = []
    for course, units in DEMO_UNITS.items():
        for n, (title, _covers, _blurb, slo) in enumerate(units, start=1):
            fam = family(course, n)
            families.append(fam)
            d = tasks_dir / fam
            d.mkdir(parents=True, exist_ok=True)
            doc = task_doc(course, n, title, slo)
            (d / "items.yaml").write_text(
                "# GENERATED by tools/gen_dev_curriculum.py — DEV-ONLY demonstration task.\n"
                "# Do not hand-edit; edit the spec in the generator and re-run.\n"
                + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
            )
    return families


def write_majors_dev(path: pathlib.Path) -> None:
    doc = yaml.safe_load((REPO / "curriculum" / "majors.yaml").read_text())
    for major in doc["majors"]:
        for klass in major.get("classes") or []:
            course = klass["course"]
            if course in DEMO_UNITS:
                klass["task_families"] = [
                    family(course, n) for n in range(1, len(DEMO_UNITS[course]) + 1)
                ]
    path.write_text(
        GENERATED_BANNER + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
    )


def write_slo_dev(path: pathlib.Path) -> None:
    doc = yaml.safe_load((REPO / "curriculum" / "slo.yaml").read_text())
    covered = {row["course"] for row in doc["coverage"]}
    for course, (title, outcomes) in DEMO_COVERAGE.items():
        if course not in covered:
            doc["coverage"].append({"course": course, "title": title, "outcomes": outcomes})
    path.write_text(
        GENERATED_BANNER + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
    )


def write_demo_units_ts(path: pathlib.Path) -> None:
    """Emit the frontend demo unit taxonomy consumed by lib/units.ts (dev gate)."""
    lines = [
        "// GENERATED by tools/gen_dev_curriculum.py — DEV ONLY. Do not hand-edit.",
        "// Merged into the unit taxonomy ONLY when the server-side dev gate",
        "// (IDA_DEMO_CURRICULUM) is on; see lib/units.ts. Inert otherwise.",
        'import type { ClassUnit } from "./units";',
        "",
        "export const DEMO_TAXONOMY: Record<string, ClassUnit[]> = {",
    ]
    for course, units in DEMO_UNITS.items():
        lines.append(f"  {ts(course)}: [")
        for n, (title, covers, blurb, _slo) in enumerate(units, start=1):
            fam = family(course, n)
            covers_ts = ", ".join(ts(c) for c in covers)
            lines.append("    {")
            lines.append(f"      key: {ts(unit_key(title))},")
            lines.append(f"      n: {n},")
            lines.append(f"      title: {ts(title)},")
            lines.append(f"      covers: [{covers_ts}],")
            lines.append(f"      blurb: {ts(blurb)},")
            lines.append(f"      families: [{ts(fam)}],")
            lines.append(f"      source: {ts('Illustrative demonstration set')},")
            lines.append(
                "      caveat: "
                + ts(
                    "Illustrative demonstration data for a class that has not yet had its own "
                    "tasks authored. The items are synthetic placeholders and the scores are "
                    "seeded, not measured."
                )
                + ","
            )
            lines.append("    },")
        lines.append("  ],")
    lines.append("};")
    lines.append("")
    path.write_text("\n".join(lines))


def ts(s: str) -> str:
    """A double-quoted TS string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> int:
    tasks_dir = REPO / "tasks-dev"
    tasks_dir.mkdir(exist_ok=True)
    families = write_tasks(tasks_dir)
    write_majors_dev(REPO / "curriculum" / "majors.dev.yaml")
    write_slo_dev(REPO / "curriculum" / "slo.dev.yaml")
    write_demo_units_ts(REPO / "frontend" / "src" / "lib" / "demo-units.generated.ts")
    print(f"wrote {len(families)} demo task families under {tasks_dir}")
    print(
        "wrote curriculum/majors.dev.yaml, curriculum/slo.dev.yaml, frontend demo-units.generated.ts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
