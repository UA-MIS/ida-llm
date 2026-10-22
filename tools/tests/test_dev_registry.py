"""`models.dev.yaml` must be a faithful, dev-only superset of `models.yaml`.

The dev site shows ~7 models by loading a DEV-ONLY registry (`models.dev.yaml`)
via `IDA_MODELS_FILE`, set only in the dev overlay. Two things have to stay true
or the honesty of that arrangement breaks:

1. The real entries in `models.dev.yaml` are IDENTICAL to `models.yaml`. If they
   drift, dev would describe `luna` (or the mock, or the judge) differently from
   every other environment, silently. The committed dev file is hand-maintained,
   so this test is the thing that keeps it honest -- it compares PARSED entries,
   so trimming the prose comments from the dev copy is fine and a changed VALUE
   is not.
2. The synthetic demo keys exist ONLY in the dev registry. A demo key in
   `models.yaml` would ship to the production registry in the promoted image.
"""

from __future__ import annotations

import pathlib

from ida_core.registry import load_registry

REPO = pathlib.Path(__file__).resolve().parents[2]
PROD = REPO / "models.yaml"
DEV = REPO / "models.dev.yaml"

DEMO_KEYS = {"vega", "orion", "atlas", "nova", "sol"}


def test_dev_registry_parses_and_validates():
    # load_registry runs JSON-schema then pydantic validation; a malformed dev
    # registry fails here rather than crashing the dev API at startup.
    assert load_registry(DEV).models


def test_real_entries_are_identical_to_models_yaml():
    prod = {m.key: m for m in load_registry(PROD).models}
    dev = {m.key: m for m in load_registry(DEV).models}
    for key, entry in prod.items():
        assert key in dev, f"{key} is in models.yaml but missing from models.dev.yaml"
        assert entry.model_dump() == dev[key].model_dump(), (
            f"{key} differs between models.yaml and models.dev.yaml -- the dev registry has "
            "drifted from the source of truth; re-copy the entry"
        )


def test_demo_keys_are_dev_only():
    prod = {m.key for m in load_registry(PROD).models}
    dev = {m.key for m in load_registry(DEV).models}
    assert dev >= DEMO_KEYS, f"missing demo keys in dev registry: {sorted(DEMO_KEYS - dev)}"
    leaked = DEMO_KEYS & prod
    assert not leaked, f"demo keys leaked into models.yaml (the prod registry): {sorted(leaked)}"


def test_demo_models_cannot_reach_a_paid_api():
    """Every demo model routes to the mock endpoint and carries no API key, so a
    run against one on dev is deterministic and costs $0 -- it can never hit a
    real provider."""
    dev = {m.key: m for m in load_registry(DEV).models}
    for key in DEMO_KEYS:
        entry = dev[key]
        assert entry.api_key_env is None, f"{key} names an api key env -- a demo model must not"
        assert entry.base_url_env == "MOCK_MODEL_BASE_URL", (
            f"{key} must route to the mock endpoint, not {entry.base_url_env!r}"
        )
        assert entry.serving.serving_stack.value == "mock", f"{key} must use the mock serving stack"


def test_claude_versions_are_grouped_into_families_from_data():
    """Family membership is a registry field, so the grids never hardcode names."""
    from collections import defaultdict

    entries = load_registry(PROD).models
    families = defaultdict(list)
    for m in entries:
        if m.family:
            assert m.family_display_name, f"{m.key} has a family but no family_display_name"
            families[m.family].append(m)
    assert {k: len(v) for k, v in families.items()} == {
        "claude-fable": 2,
        "claude-opus": 6,
        "claude-sonnet": 4,
        "claude-haiku": 2,
    }
    for members in families.values():
        assert len({m.family_display_name for m in members}) == 1
    orders = [m.display_order for m in entries if m.display_order is not None]
    assert len(orders) == len(set(orders)), "display_order must be unique"
    by_key = {m.key: m for m in entries}
    # Luna and Qwen are their own rows, after the Claude families.
    assert by_key["luna"].family is None and by_key["qwen-local"].family is None
    assert by_key["luna"].display_order > max(
        m.display_order for m in entries if m.family
    )
