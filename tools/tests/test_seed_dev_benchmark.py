"""The dev seeder must not be able to write rows the API cannot read back.

Every test here guards a failure that ALREADY HAPPENED on dev. The seeder writes
straight to `runs`/`results`, bypassing the harness, so nothing else checks that
what it writes satisfies the contracts the API rebuilds on read. When it did not,
`/runs/{id}` returned HTTP 500 for every seeded row -- the product's "evidence one
click away" claim, broken across the board, and invisible until someone opened a
receipt.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib

import pytest
from pydantic import ValidationError

from ida_core.contracts import RunStatus, ScorerKind, ServingConfig

REPO = pathlib.Path(__file__).resolve().parents[2]

# The seeder reads the RESOLVED registry (IDA_MODELS_FILE / --models). On dev
# that is the dev-only registry, which declares the synthetic demo models the
# seeder fills the grid with; models.yaml does not and must never (it ships to
# prod). Every test that needs serving configs or cost rates points here.
DEV_MODELS = REPO / "models.dev.yaml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "seed_dev_benchmark", REPO / "tools" / "seed_dev_benchmark.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seeder = _load()


class TestGuards:
    """It deletes rows, so pointing it at the wrong database must be impossible."""

    @pytest.mark.parametrize(
        "dsn",
        [
            "postgresql://u@h/ida_llm_prod",
            "postgresql://u@h/ida_llm_staging",
            "postgresql://u@production-host/ida",
        ],
    )
    def test_refuses_anything_that_looks_like_staging_or_prod(self, dsn):
        with pytest.raises(SystemExit):
            seeder.guard(dsn)

    def test_allows_a_dev_dsn(self):
        seeder.guard("postgresql://u@capstone-tenant-pg-rw.db-tier/ida_llm_dev")


class TestServingConfig:
    """Regression: the first seeder stored {"synthetic": true}.

    `ServingConfig` is extra="forbid" and the API validates the column on every
    read, so that value made every run receipt a 500.
    """

    def test_every_seeded_model_is_in_the_dev_registry(self):
        dev_keys = {
            e["key"] for e in __import__("yaml").safe_load(DEV_MODELS.read_text())["models"]
        }
        assert set(seeder.PROFILES) <= dev_keys, (
            "the seeder must only seed keys the resolved registry describes -- an unregistered "
            "key cannot be described honestly by the trust badges (it renders 'test stub')"
        )

    def test_demo_keys_never_leak_into_the_production_registry(self):
        """The synthetic demo keys exist ONLY in the dev registry.

        models.yaml ships inside the image promoted byte-identically to staging
        and prod. A demo key there would be a fake model in the PRODUCTION
        registry -- the exact failure the dev-only IDA_MODELS_FILE override
        exists to prevent.
        """
        prod_keys = {
            e["key"]
            for e in __import__("yaml").safe_load((REPO / "models.yaml").read_text())["models"]
        }
        demo = set(seeder.PROFILES) - {"mock"}
        assert demo, "expected at least one synthetic demo model in PROFILES"
        assert not (demo & prod_keys), (
            f"demo keys {sorted(demo & prod_keys)} are in models.yaml -- they would ship to the "
            "production registry; keep them in models.dev.yaml only"
        )

    def test_luna_is_never_seeded(self):
        """Luna has REAL rows on dev; a synthetic luna run would shadow them."""
        assert "luna" not in seeder.PROFILES

    def test_derived_configs_validate(self):
        for key, cfg in seeder.load_serving_configs(DEV_MODELS).items():
            try:
                ServingConfig.model_validate(cfg)
            except ValidationError as exc:  # pragma: no cover - failure path
                pytest.fail(f"{key} produced an invalid ServingConfig: {exc}")

    def test_the_synthetic_marker_lives_in_the_schemas_escape_hatch(self):
        for cfg in seeder.load_serving_configs(DEV_MODELS).values():
            assert cfg["extra"]["synthetic"] is True
            # ...and NOT at the top level, which is what broke it before.
            assert "synthetic" not in {k for k in cfg if k != "extra"}

    def test_a_top_level_synthetic_key_is_still_rejected(self):
        """Proves the constraint that caused the outage is real, not assumed."""
        with pytest.raises(ValidationError):
            ServingConfig.model_validate({"synthetic": True})


class TestPreflight:
    """The check that would have caught both bugs before they reached the database."""

    def _rows(self):
        from ida_harness.tasks import TaskCatalog

        specs = list(TaskCatalog.from_directory(REPO / "tasks").all())
        return seeder.build_rows(
            specs,
            seeder.load_serving_configs(DEV_MODELS),
            seeder.load_cost_rates(DEV_MODELS),
            dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )

    def test_real_rows_pass_every_coercion_the_api_applies(self):
        runs, results = self._rows()
        assert runs and results
        seeder._preflight(runs, results)
        for r in runs:
            RunStatus(r[1])
            ServingConfig.model_validate(json.loads(r[6]))
        for r in results:
            ScorerKind(r[6])
            ServingConfig.model_validate(json.loads(r[5]))

    def test_scorer_comes_from_the_task_not_invented(self):
        """Regression: scorer="synthetic" is not a ScorerKind -> 500 on the receipt."""
        _, results = self._rows()
        kinds = {r[6] for r in results}
        assert kinds, "no results built"
        assert kinds <= {k.value for k in ScorerKind}, f"invalid scorer(s): {kinds}"

    def test_preflight_rejects_a_bad_scorer(self):
        runs, results = self._rows()
        results[0][6] = "synthetic"
        with pytest.raises(ValueError):
            seeder._preflight(runs, results)

    def test_preflight_rejects_a_bad_serving_config(self):
        runs, results = self._rows()
        results[0][5] = json.dumps({"synthetic": True})
        with pytest.raises(ValidationError):
            seeder._preflight(runs, results)


def test_rows_are_deterministic():
    """Same inputs, same scores -- a re-seed must not silently change the numbers."""
    from ida_harness.tasks import TaskCatalog

    specs = list(TaskCatalog.from_directory(REPO / "tasks").all())
    cfgs = seeder.load_serving_configs(DEV_MODELS)
    when = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    rates = seeder.load_cost_rates(DEV_MODELS)
    _, a = seeder.build_rows(specs, cfgs, rates, when)
    _, b = seeder.build_rows(specs, cfgs, rates, when)
    assert [r[7] for r in a] == [r[7] for r in b]


class TestCost:
    """Regression: the seeder wrote a flat cost_usd=0.0 on every row.

    A priced model (several of the demo models carry illustrative rates, e.g.
    `vega` at $0.3/$1.5 per mtok) rendered as FREE on dev is a paid-looking
    commercial model shown at zero cost on a page that pitches value. These
    tests exist so cost can never silently become a constant again. Costs on
    seeded rows are themselves illustrative and demonstration-flagged, but the
    DERIVATION (rate card x varying tokens) must still be exercised.
    """

    def _rows(self):
        from ida_harness.tasks import TaskCatalog

        specs = list(TaskCatalog.from_directory(REPO / "tasks").all())
        return seeder.build_rows(
            specs,
            seeder.load_serving_configs(DEV_MODELS),
            seeder.load_cost_rates(DEV_MODELS),
            dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )

    def test_rates_come_from_the_registry(self):
        rates = seeder.load_cost_rates(DEV_MODELS)
        entries = {
            e["key"]: e for e in __import__("yaml").safe_load(DEV_MODELS.read_text())["models"]
        }
        for key, (inp, out) in rates.items():
            cost = entries[key].get("cost") or {}
            assert inp == cost.get("input_usd_per_mtok", 0.0)
            assert out == cost.get("output_usd_per_mtok", 0.0)

    def test_a_paid_model_never_costs_zero(self):
        """The exact defect: a priced seeded model must not write free rows."""
        rates = seeder.load_cost_rates(DEV_MODELS)
        paid = [k for k, (i, o) in rates.items() if i > 0 or o > 0]
        assert paid, "expected at least one priced model in the registry"
        _, results = self._rows()
        for key in paid:
            costs = [r[12] for r in results if r[4] == key]
            assert costs, f"no rows for {key}"
            assert all(c > 0 for c in costs), f"{key} is priced but wrote a zero cost"

    def test_genuinely_free_models_stay_free(self):
        """`mock` is a stub and `sol` is a zero-rate demo model -- 0.0 is the truth."""
        rates = seeder.load_cost_rates(DEV_MODELS)
        free = [k for k, (i, o) in rates.items() if i == 0 and o == 0]
        _, results = self._rows()
        for key in free:
            assert all(r[12] == 0.0 for r in results if r[4] == key)

    def test_cost_is_not_a_flat_constant(self):
        """Per-answer cost must mean something, not be row-count x a constant."""
        _, results = self._rows()
        paid = [k for k, (i, o) in seeder.load_cost_rates(DEV_MODELS).items() if i > 0 or o > 0]
        for key in paid:
            costs = {r[12] for r in results if r[4] == key}
            assert len(costs) > 1, f"{key} wrote one repeated cost -- tokens are not varying"

    def test_run_total_matches_the_sum_of_its_results(self):
        """The runner computes total_cost_usd as sum(r.cost_usd); so must we."""
        runs, results = self._rows()
        by_run: dict[str, float] = {}
        for r in results:
            by_run[r[1]] = by_run.get(r[1], 0.0) + r[12]
        for run in runs:
            assert run[12] == pytest.approx(by_run[run[0]]), f"run {run[0]} total disagrees"

    def test_token_counts_are_not_constant(self):
        _, results = self._rows()
        assert len({r[10] for r in results}) > 1
        assert len({r[11] for r in results}) > 1

    def test_judge_cost_stays_separate(self):
        """judge_cost_usd is its own column and must not be folded into cost."""
        _, results = self._rows()
        assert all(r[19] == 0.0 for r in results)
