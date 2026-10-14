#!/usr/bin/env python3
"""Seed a DEV database with deterministic SYNTHETIC benchmark results.

WHY THIS EXISTS
---------------
The frontend -- leaderboard, per-model report cards, the /compare grid -- only
has something to show once several models have been measured against several
outcomes. Running real models to get that costs money and time, and on dev we
want the *shape* of a populated result set, not real numbers. This writes that
shape.

WHAT IT IS NOT
--------------
It is not a benchmark, and nothing it writes is a measurement. Every row it
creates is labelled ``synthetic-dev-seed`` with ``harness_version`` set to
``0.0.0-synthetic`` so a human, a query, or a future maintainer can tell seeded
rows from measured ones without guessing. Scores come from a hash, not a model.

REGISTRY-ONLY, ON PURPOSE -- AND WHICH REGISTRY
-----------------------------------------------
It seeds ONLY keys that exist in the registry it is pointed at. An earlier
version invented ``demo-atlas`` / ``demo-vega`` / ``demo-orion`` as bare keys
with no registry entry, and the UI correctly labelled all three "test stub --
never recommended", because the trust badges are derived from the registry and
an unregistered key cannot be described honestly.

The fix is NOT to register fakes in ``models.yaml``: that file ships inside the
image promoted byte-identically to staging and prod, so a demo entry added there
would become a fake model in the PRODUCTION registry. The fix is the registry
override the rest of the system already has -- ``IDA_MODELS_FILE`` (see
``Settings.resolved_models_file``). A DEV-ONLY registry file, named by that
variable in the dev overlay ONLY, carries the real entries plus a handful of
synthetic demonstration models; staging and prod never set the variable, so they
load the committed ``models.yaml`` and never see a demo key. This seeder reads
the SAME resolved path (``--models`` / ``IDA_MODELS_FILE``), so the demo keys it
seeds are exactly the ones that registry describes -- registered, honestly
labelled, and impossible to leak into a production registry. A wider grid that
is dev-only and demonstration-flagged beats both a thinner one and a dishonest
one.

SERVING CONFIG COMES FROM THE REGISTRY
--------------------------------------
``serving_config`` is NOT hand-written here. It is read from each model's entry
in ``models.yaml`` and validated through :class:`ServingConfig` before anything
is inserted. That matters: ``ServingConfig`` is ``extra="forbid"``, and the
previous seeder stored ``{"synthetic": true}``, which is not a valid config. The
API re-validates the column on every read, so each of those rows made its run
receipt return HTTP 500 -- every "see the evidence" link in the product was
broken. Deriving the value from the registry makes an invalid config impossible
to write, and keeps it correct when the registry changes.

The synthetic marker still exists, but it lives in ``ServingConfig.extra``,
which is the schema's own escape hatch for exactly this ("recorded, never
interpreted").

IDEMPOTENT
----------
Re-running replaces only what this script created: rows are deleted by the seed
LABEL, not by model key, so a real run for a real model is never touched even
though they share a key.

USAGE
-----
    DATABASE_URL=postgres://... python3 tools/seed_dev_benchmark.py --yes

Refuses to run when ``DATABASE_URL`` looks like staging or prod. ``--yes`` is
required; there is no interactive prompt and no default database.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys

import psycopg
import yaml

from ida_core.contracts import (
    SYNTHETIC_HARNESS_VERSION,
    SYNTHETIC_MARKER,
    RunStatus,
    ScorerKind,
    ServingConfig,
)
from ida_core.ids import new_result_id, new_run_id
from ida_harness.tasks import TaskCatalog

SEED_LABEL = "synthetic-dev-seed"

# ⚠ IMPORTED, NOT RETYPED. The results API reads these same two markers to
# decide whether to label a row "illustrative" for a reader (see
# `ida_api.leaderboard.is_demonstration`). A local copy that drifted would
# fail silently and in the dangerous direction: seeded rows would start being
# presented to professors as real measurements.
SEED_HARNESS_VERSION = SYNTHETIC_HARNESS_VERSION

# Per-model character. `base` is the model's overall level; `bias` tilts it per
# SLO so that no model wins every outcome -- a leaderboard where one row is best
# at everything exercises none of the UI's comparison logic. These numbers are
# invented and mean nothing beyond producing a plausible SHAPE.
#
# ⚠ `luna` IS DELIBERATELY ABSENT. Luna has REAL measured rows on the MIS 200
# families in the dev database (ported from the real prod/staging run). Seeding a
# synthetic luna run would be newer than the real one and
# `latest_terminal_run_per_pair` would SHADOW the real number with a fabricated
# one -- the exact opposite of "keep MIS 200's Luna data real and unflagged". So
# luna is never seeded here: its column stays real, and the demo models below
# fill the rest of each grid (including MIS 200's other six columns) with
# demonstration-flagged illustration. `mock` is kept (its rows mean nothing by
# design and are correctly labelled illustrative when seeded).
#
# The five demo keys (`vega` .. `sol`) exist ONLY in the dev-only registry file
# named by IDA_MODELS_FILE -- never in the committed models.yaml -- so they can
# never appear in a staging/prod registry. Codename style (like Luna/Sparks),
# non-impersonating: no real vendor or product name.
PROFILES: dict[str, dict] = {
    "vega": {"base": 0.90, "bias": {"SLO2": +0.07, "SLO9": +0.05, "SLO6": -0.06, "SLO7": -0.04}},
    "orion": {"base": 0.83, "bias": {"SLO1": +0.09, "SLO3": +0.07, "SLO2": -0.05, "SLO4": -0.04}},
    "atlas": {"base": 0.87, "bias": {"SLO7": +0.06, "SLO4": +0.06, "SLO2": -0.05, "SLO1": -0.05}},
    "nova": {"base": 0.78, "bias": {"SLO6": +0.10, "SLO3": +0.05, "SLO2": -0.08, "SLO9": -0.04}},
    "sol": {"base": 0.81, "bias": {"SLO3": +0.08, "SLO4": +0.07, "SLO9": -0.06, "SLO7": -0.03}},
    "mock": {"base": 0.52, "bias": {}},
}


def _fail(msg: str) -> None:
    print(f"REFUSING: {msg}", file=sys.stderr)
    raise SystemExit(2)


def guard(dsn: str) -> None:
    """Refuse anything that does not look like dev.

    Deliberately a denylist on the DSN plus a required flag, not a cleverer
    check: this script DELETES rows, and the cost of being wrong about which
    database it is pointed at is unacceptable in staging or prod.
    """
    low = dsn.lower()
    for bad in ("staging", "prod", "production"):
        if bad in low:
            _fail(f"DATABASE_URL contains {bad!r}. This script is DEV ONLY.")


def det(*parts: object) -> float:
    """Deterministic pseudo-random in [0,1) -- same inputs, same score, forever."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def slo_of(tags) -> str | None:
    for t in tags or ():
        if str(t).startswith("slo:"):
            return str(t).split(":", 1)[1].upper()
    return None


def load_cost_rates(models_path: pathlib.Path) -> dict[str, tuple[float, float]]:
    """Per-model (input, output) USD per MILLION tokens, from the registry.

    Read rather than invented, so a seeded cost cannot contradict what the model
    actually charges. ``mock`` and the self-hosted demo models are genuinely 0.0
    (a stub and endpoints we do not pay per token for) and stay 0.0; that is a
    real fact about them, not a placeholder.

    ``models_path`` is the RESOLVED registry (``IDA_MODELS_FILE`` / ``--models``),
    so demo keys that exist only in the dev-only registry resolve here exactly as
    they do for the running API.
    """
    registry = yaml.safe_load(models_path.read_text())
    entries = {e["key"]: e for e in registry["models"]}
    rates: dict[str, tuple[float, float]] = {}
    for key in PROFILES:
        cost = entries[key].get("cost") or {}
        rates[key] = (
            float(cost.get("input_usd_per_mtok", 0.0)),
            float(cost.get("output_usd_per_mtok", 0.0)),
        )
    return rates


def load_serving_configs(models_path: pathlib.Path) -> dict[str, dict]:
    """Read each seeded model's serving config from the registry and VALIDATE it.

    Validating here, before any insert, is the whole point: an invalid config
    fails loudly at seed time instead of silently becoming a 500 on every run
    receipt at read time.

    ``models_path`` is the RESOLVED registry (``IDA_MODELS_FILE`` / ``--models``).
    A missing key is a hard fail: seeding a demo model that the dev registry does
    not describe would re-create the "test stub -- never recommended" labelling
    the module docstring warns about.
    """
    registry = yaml.safe_load(models_path.read_text())
    entries = {e["key"]: e for e in registry["models"]}

    missing = sorted(set(PROFILES) - set(entries))
    if missing:
        _fail(
            f"registry {models_path} has no entry for {missing}. "
            "Point --models / IDA_MODELS_FILE at the dev registry that declares the demo keys."
        )

    out: dict[str, dict] = {}
    for key in PROFILES:
        serving = dict(entries[key].get("serving") or {})
        serving["registry_key"] = key
        # The synthetic marker belongs in `extra`, the schema's own escape hatch.
        serving["extra"] = {
            **(serving.get("extra") or {}),
            SYNTHETIC_MARKER: True,
            "seed": SEED_LABEL,
        }
        out[key] = ServingConfig.model_validate(serving).model_dump(mode="json")
    return out


def _preflight(runs: list, results: list) -> None:
    """Validate rows through the SAME coercions the API applies on read.

    This exists because the failure it catches has already happened twice. The
    API rebuilds contracts from these columns on every read
    (``ida_core.repositories.result_row_to_record``), so a value the writer
    considers fine but the enum rejects does not fail here -- it fails as an
    HTTP 500 on the run receipt, for every seeded row, which is precisely the
    "evidence one click away" promise the product is built on.

    The first version of this seeder stored ``serving_config={"synthetic": true}``
    (invalid: ``ServingConfig`` is ``extra="forbid"``) AND ``scorer="synthetic"``
    (not a ``ScorerKind``). Fixing only the first left the second, and the
    receipts were still 500. Checking every coerced column together is the only
    version of this that converges.

    Cheap and total: one representative row per distinct value, before any write.
    """
    for status in {r[1] for r in runs}:
        RunStatus(status)
    for cfg in {r[6] for r in runs}:
        ServingConfig.model_validate(json.loads(cfg))
    for scorer in {r[6] for r in results}:
        ScorerKind(scorer)
    for cfg in {r[5] for r in results}:
        ServingConfig.model_validate(json.loads(cfg))
    print(
        f"  preflight OK: {len({r[1] for r in runs})} status, "
        f"{len({r[6] for r in results})} scorer, "
        f"{len({r[5] for r in results})} serving_config distinct values validated"
    )


def build_rows(
    specs, serving: dict[str, dict], rates: dict[str, tuple[float, float]], now: dt.datetime
) -> tuple[list, list]:
    """Build the (runs, results) tuples. Pure -- no database, so it is testable."""
    runs, results = [], []
    for model, profile in PROFILES.items():
        cfg = json.dumps(serving[model])
        in_rate, out_rate = rates[model]
        for spec in specs:
            slo = slo_of(getattr(spec, "tags", ()))
            # The task's OWN declared scorer, not an invented label. `scorer` is
            # read back as `ScorerKind(row.scorer)`, so anything not in that enum
            # is a 500 on the run receipt -- see _preflight below.
            scorer = str(spec.scorer.kind)
            rid = new_run_id()
            # Spread runs over the past fortnight so time-ordered views have a
            # shape to render rather than one flat timestamp.
            fin = now - dt.timedelta(hours=det("t", model, spec.id) * 336)
            rows, scores = [], []
            prompt_total = completion_total = 0
            cost_total = 0.0
            for sample in spec.samples:
                raw = profile["base"] + profile["bias"].get(slo, 0.0)
                jitter = (det(model, spec.id, sample.id) - 0.5) * 0.18
                value = max(0.0, min(1.0, raw + jitter))
                scores.append(value)
                # Token counts VARY per sample. A flat constant would make
                # cost-per-answer an artifact of the row count rather than a
                # number that means anything.
                prompt_tokens = int(300 + det("pt", model, spec.id, sample.id) * 420)
                completion_tokens = int(120 + det("ct", model, spec.id, sample.id) * 380)
                # Cost from the REGISTRY's real rates, never a constant. This is
                # what makes total_cost_usd / scored_count meaningful, and it is
                # why a paid model can no longer render as free.
                cost_usd = (prompt_tokens / 1e6) * in_rate + (completion_tokens / 1e6) * out_rate
                prompt_total += prompt_tokens
                completion_total += completion_tokens
                cost_total += cost_usd
                rows.append(
                    [
                        new_result_id(),
                        rid,
                        spec.id,
                        sample.id,
                        model,
                        cfg,
                        scorer,
                        value,
                        value >= 0.6,
                        True,
                        prompt_tokens,
                        completion_tokens,
                        cost_usd,
                        900.0 + det("l", model, sample.id) * 2600.0,
                        fin,
                        0,
                        False,
                        0,
                        0,
                        0.0,
                        0,
                    ]
                )
            mean = sum(scores) / len(scores) if scores else None
            runs.append(
                (
                    rid,
                    "succeeded",
                    spec.id,
                    model,
                    SEED_LABEL,
                    SEED_HARNESS_VERSION,
                    cfg,
                    len(spec.samples),
                    len(scores),
                    mean,
                    prompt_total,
                    completion_total,
                    # The SAME rule the runner uses (worker.py: the sum of the
                    # results' cost_usd). judge_cost_usd is a separate column and
                    # is deliberately not folded in here.
                    cost_total,
                    fin,
                    fin,
                    0,
                )
            )
            results.extend(rows)
    return runs, results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true", help="required; confirms this is a dev database")
    ap.add_argument(
        "--tasks", default=None, help="task directory (default: <repo>/tasks or /app/tasks)"
    )
    ap.add_argument(
        "--repo",
        default=None,
        help="directory holding models.yaml (default: the script's parent repo). Needed when "
        "running from a container where this file was copied outside the source tree.",
    )
    ap.add_argument(
        "--models",
        default=None,
        help="registry file to read serving configs and cost rates from "
        "(default: the IDA_MODELS_FILE setting, else <repo>/models.yaml). Point this at the "
        "DEV-ONLY registry so the synthetic demo models resolve exactly as the running API sees them.",
    )
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        _fail("DATABASE_URL is not set.")
    if not args.yes:
        _fail("refusing without --yes (this DELETES and rewrites seeded rows).")
    guard(dsn)

    repo = pathlib.Path(args.repo) if args.repo else pathlib.Path(__file__).resolve().parent.parent
    # Resolve the registry the SAME way Settings.resolved_models_file does:
    # explicit --models wins, then IDA_MODELS_FILE, then the committed
    # <repo>/models.yaml. Pointing at the dev-only registry is what makes the
    # synthetic demo keys resolve.
    models_path = (
        pathlib.Path(args.models)
        if args.models
        else (
            pathlib.Path(os.environ["IDA_MODELS_FILE"])
            if os.environ.get("IDA_MODELS_FILE")
            else repo / "models.yaml"
        )
    )
    if not models_path.is_file():
        _fail(f"registry file not found at {models_path} -- pass --models or set IDA_MODELS_FILE.")
    tasks_dir = (
        pathlib.Path(args.tasks)
        if args.tasks
        else (pathlib.Path("/app/tasks") if pathlib.Path("/app/tasks").exists() else repo / "tasks")
    )
    serving = load_serving_configs(models_path)
    specs = list(TaskCatalog.from_directory(tasks_dir).all())
    if not specs:
        _fail(f"no tasks found under {tasks_dir}")

    rates = load_cost_rates(models_path)
    runs, results = build_rows(specs, serving, rates, dt.datetime.now(dt.UTC))

    # Fail loudly HERE rather than as a 500 on every receipt page later.
    _preflight(runs, results)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # Delete by LABEL, never by model_key: these keys are real registry
        # models and may one day have real runs on dev that must survive a
        # re-seed.
        cur.execute(
            "delete from results where run_id in (select id from runs where label = %s)",
            (SEED_LABEL,),
        )
        removed = cur.rowcount
        cur.execute("delete from runs where label = %s", (SEED_LABEL,))
        print(f"  cleared {removed} seeded results / {cur.rowcount} seeded runs")

        cur.executemany(
            """insert into runs
               (id,status,task_id,model_key,label,harness_version,serving_config,
                sample_count,scored_count,mean_score,prompt_tokens,completion_tokens,
                total_cost_usd,created_at,finished_at,error_count)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            runs,
        )
        cur.executemany(
            """insert into results
               (id,run_id,task_id,sample_id,model_key,serving_config,scorer,score_value,
                passed,scorable,prompt_tokens,completion_tokens,cost_usd,latency_ms,
                created_at,repeat_index,cached,judge_prompt_tokens,judge_completion_tokens,
                judge_cost_usd,judge_attempts)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            results,
        )
        conn.commit()

        print(
            f"  seeded {len(runs)} runs / {len(results)} results "
            f"across {len(PROFILES)} models and {len(specs)} tasks"
        )
        for model in PROFILES:
            n, sc, mn = cur.execute(
                "select count(*), count(score_value), round(avg(score_value)::numeric,3) "
                "from results where model_key = %s",
                (model,),
            ).fetchone()
            print(f"    {model:<14} results={n:<5} scored={sc:<5} mean={mn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
