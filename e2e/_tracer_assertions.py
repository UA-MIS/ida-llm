"""Shared assertions for both tracer-bullet modes.

The two modes differ only in how they build the stack; what they *assert* is
identical and lives here, so the in-process test can never drift into checking
something weaker than the containerised one.

⚠ THIS IS NOT `conftest.py`, AND THE NAME IS THE REASON. CI runs ONE `pytest`
from the repo root across five distributions plus e2e, all of which own a
`conftest.py`. A test module doing `from conftest import ...` therefore imports
whichever conftest was loaded first -- which is a different file depending on
collection order. `_tracer_assertions` can only ever mean this file.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

TERMINAL_STATUSES = {"succeeded", "partial", "failed"}
"""Every state a finished run can be in.

Derived from :class:`ida_core.contracts.RunStatus` and asserted against it below,
because both tracer modes poll on this set: a hand-maintained copy that missed
``partial`` would make a partial run poll forever and time out, which is a
confusing way to learn that a new status exists.
"""


def _assert_terminal_statuses_match_the_contract() -> None:
    from ida_core.contracts import RunStatus

    non_terminal = {RunStatus.QUEUED.value, RunStatus.RUNNING.value}
    contract = {s.value for s in RunStatus} - non_terminal
    assert contract == TERMINAL_STATUSES, (
        f"RunStatus gained or lost a terminal state: {contract ^ TERMINAL_STATUSES}"
    )


_assert_terminal_statuses_match_the_contract()

VERIFIABLE_TASK = "demo/arithmetic-quiz-check"
SUBJECTIVE_TASK = "demo/essay-feedback"
EXPECTED_SAMPLES = {"add-simple", "mul-simple", "sub-negative", "div-decimal"}


def wait_until(
    predicate: Callable[[], Any], *, timeout_s: float = 60.0, interval_s: float = 0.25
) -> Any:
    """Poll ``predicate`` until it returns something truthy, or fail with context."""
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval_s)
    raise AssertionError(f"condition not met within {timeout_s}s; last value: {last!r}")


def assert_tracer_run_is_complete(detail: dict) -> None:
    """Every assertion the tracer bullet makes about a finished verifiable run.

    Called by BOTH modes. If you weaken this, you weaken the in-process gate and
    the containerised gate at the same time -- which is the point.
    """
    run = detail["run"]
    results = detail["results"]

    # --- the run finished, and finished successfully -----------------------
    assert run["status"] == "succeeded", f"run did not succeed: {run.get('error')}"
    assert run["error_count"] == 0
    assert run["task_id"] == VERIFIABLE_TASK
    assert run["model_key"] == "mock"
    assert run["error"] is None
    assert run["started_at"] is not None and run["finished_at"] is not None

    # --- every sample was scored, and scored correctly ----------------------
    assert run["sample_count"] == 4
    assert run["scored_count"] == 4
    assert run["mean_score"] == 1.0, "the mock answers arithmetic correctly"
    assert len(results) == 4
    assert {r["sample_id"] for r in results} == EXPECTED_SAMPLES

    for result in results:
        assert result["error"] is None
        assert result["archive_error"] is None
        assert result["scorable"] is True
        assert result["cached"] is False, "the tracer runs with NullCache, so nothing is cached"
        assert result["repeat_index"] == 0
        score = result["score"]
        assert score is not None, f"sample {result['sample_id']} was not scored"
        assert score["scorer"] == "numeric_match"
        assert score["value"] == 1.0 and score["passed"] is True
        assert score["explanation"], "a reviewer must see WHY without opening the transcript"

    # --- D-1: full serving config on the run AND on every result ------------
    for config in [run["serving_config"], *(r["serving_config"] for r in results)]:
        assert config is not None
        assert config["model_id"] == "mock-echo-1"
        assert config["registry_key"] == "mock"
        assert config["serving_stack"] == "mock"
        assert config["quantization"] == "none"
        assert config["sampling"]["temperature"] == 0.0
        assert config["sampling"]["max_tokens"] == 256
        assert config["sampling"]["seed"] == 20260101

    # --- D-1: reproducibility provenance -----------------------------------
    assert run["harness_version"], "the harness version that produced this must be recorded"
    assert len(run["task_content_sha"]) == 64, "per-task comparability key (B8)"
    assert all(r["task_content_sha"] == run["task_content_sha"] for r in results)
    assert run["sweep_id"], "every run belongs to a sweep (B9)"

    # --- accounting flowed end to end ---------------------------------------
    assert run["total_usage"]["prompt_tokens"] > 0
    assert run["total_usage"]["completion_tokens"] > 0
    assert run["total_cost_usd"] == 0.0, "the mock is free"
    per_sample_prompt = sum(r["usage"]["prompt_tokens"] for r in results)
    assert per_sample_prompt == run["total_usage"]["prompt_tokens"], "rollup must add up"
    assert all(r["latency_ms"] >= 0 for r in results)

    # --- D-3: every score points at its evidence ----------------------------
    #
    # The BUCKET is read off the first URI rather than hard-coded: it is
    # deployment configuration (MINIO_BUCKET / IDA_S3_BUCKET), and the compose
    # mode and the cluster legitimately differ. The KEY SHAPE is what this
    # asserts, and it is pinned exactly -- it is the artifact-path contract in
    # ida_core.artifacts, and a drift there orphans every stored transcript.
    first = results[0]["transcript_uri"]
    assert first is not None, "a score with no traceable evidence is not citable"
    assert first.startswith("s3://"), first
    bucket = first.removeprefix("s3://").split("/", 1)[0]
    assert bucket, "the transcript URI must name a bucket"

    for result in results:
        uri = result["transcript_uri"]
        assert uri is not None, "a score with no traceable evidence is not citable"
        assert uri == (f"s3://{bucket}/runs/{run['id']}/transcripts/{result['sample_id']}.json")


def assert_transcript_is_faithful(transcript: dict, run_id: str, sample_id: str) -> None:
    """The archived bytes must contain what actually happened."""
    assert transcript["run_id"] == run_id
    assert transcript["sample_id"] == sample_id
    assert transcript["task_id"] == VERIFIABLE_TASK
    assert transcript["model_key"] == "mock"
    roles = [m["role"] for m in transcript["messages"]]
    assert roles == ["system", "user"], "the task has a system prompt; it must be recorded"
    assert transcript["completion"], "the model's answer must be archived verbatim"
    assert transcript["usage"]["prompt_tokens"] > 0
    assert transcript["raw_response"]["model"] == "mock-echo-1"


def assert_subjective_run_is_unscored_not_zeroed(detail: dict) -> None:
    """A subjective run completes, captures transcripts, and scores nothing."""
    run = detail["run"]
    results = detail["results"]
    assert run["status"] == "succeeded", "not-yet-scorable is NOT a failure"
    assert run["scored_count"] == 0
    assert run["error_count"] == 0, "nothing failed; there was simply nothing to score"
    assert run["mean_score"] is None, "a null mean, never a misleading 0.0"
    assert len(results) == 2
    for result in results:
        assert result["scorable"] is False
        assert result["score"] is None
        assert result["error"] is None, "not-yet-scorable is not an error"
        assert result["transcript_uri"] is not None, "the judge will need this later"


def assert_all_errored_run_is_marked_failed(detail: dict) -> None:
    """A run whose every call failed must say so -- the B1/B5 inversion, pinned.

    Reproduced before the fix: with the model endpoint unreachable, a
    ``verifiable`` task returned ``status: succeeded``, ``error: null``, and the
    UI rendered "Not yet scorable. This is a subjective task...". Every clause of
    that was false, and it is what a professor would have seen.

    The three signals below are exactly what the frontend classifies on
    (``lib/outcome.ts``). If any of them stops being present or precise, the UI
    loses its ability to tell "this model was not measured" from "this task
    cannot be graded yet".
    """
    run = detail["run"]
    results = detail["results"]

    assert run["status"] == "failed", "a run that measured nothing is not a success"
    assert run["scored_count"] == 0
    assert run["mean_score"] is None
    assert run["sample_count"] > 0
    assert run["error_count"] == run["sample_count"], "every sample failed"
    assert run["error"], "a failed run must say why"

    for result in results:
        # The distinguishing pair. A subjective sample is the exact inverse:
        # scorable=False, error=None.
        assert result["scorable"] is True, "this is a verifiable task"
        assert result["error"] is not None, "and every sample of it failed"
        assert result["score"] is None
        assert result["transcript_uri"] is None, "no exchange happened to archive"


def assert_partial_run_is_marked_partial(detail: dict) -> None:
    """Some failed, some did not: the mean covers only the survivors."""
    run = detail["run"]
    assert run["status"] == "partial"
    assert 0 < run["error_count"] < run["sample_count"]
    assert run["scored_count"] == run["sample_count"] - run["error_count"]
    assert run["mean_score"] is not None, "the surviving samples were still scored"
