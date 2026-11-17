"""The admin-console contract additions (design 3.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ida_core.contracts import TERMINAL_RUN_STATUSES, ModelEntry, RunStatus
from ida_core.registry import load_registry
from ida_core.repositories import TERMINAL_RUN_STATUSES as LEADERBOARD_STATUSES

REPO = Path(__file__).resolve().parents[3]
BASE = {
    "key": "m",
    "display_name": "M",
    "base_url": "http://x/v1",
    "serving": {"model_id": "m", "serving_stack": "mock"},
}


def test_cancelled_is_terminal() -> None:
    assert RunStatus.CANCELLED.value == "cancelled"
    assert RunStatus.CANCELLED in TERMINAL_RUN_STATUSES


def test_cancelled_is_never_leaderboard_evidence() -> None:
    """A cancelled re-run must not shadow the pair's last real score."""
    assert RunStatus.CANCELLED not in LEADERBOARD_STATUSES


def test_hidden_defaults_to_false_and_credential_ref_to_none() -> None:
    entry = ModelEntry.model_validate(BASE)
    assert entry.hidden is False
    assert entry.credential_ref is None


def test_credential_ref_and_api_key_env_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="both api_key_env and credential_ref"):
        ModelEntry.model_validate({**BASE, "api_key_env": "X_KEY", "credential_ref": "x"})
    assert ModelEntry.model_validate({**BASE, "credential_ref": "x"}).credential_ref == "x"


@pytest.mark.parametrize("name", ["models.yaml", "models.dev.yaml"])
def test_the_shipped_registries_still_validate(name) -> None:
    registry = load_registry(REPO / name)
    assert not any(m.hidden or m.credential_ref for m in registry.models)
