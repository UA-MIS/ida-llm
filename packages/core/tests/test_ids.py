"""Ids must be unique, sortable and prefix-tagged -- the artifact paths depend on it."""

from __future__ import annotations

import pytest

from ida_core.ids import new_id, new_result_id, new_run_id


def test_prefix_and_length() -> None:
    run_id = new_run_id()
    assert run_id.startswith("run_")
    assert len(run_id) == len("run_") + 26


def test_result_prefix() -> None:
    assert new_result_id().startswith("res_")


def test_ids_are_unique() -> None:
    ids = {new_run_id() for _ in range(2000)}
    assert len(ids) == 2000


def test_ids_are_time_sortable() -> None:
    """The timestamp prefix must dominate, so ORDER BY id approximates ORDER BY time."""
    import time

    first = new_run_id()
    time.sleep(0.005)
    second = new_run_id()
    assert first < second


def test_ids_are_path_safe() -> None:
    """Ids become object-key segments; a slash would break the path convention."""
    from ida_core.artifacts import _SAFE_SEGMENT

    assert _SAFE_SEGMENT.match(new_run_id())


@pytest.mark.parametrize("bad", ["", "has_underscore"])
def test_bad_prefix_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        new_id(bad)
