"""Run orchestration: execute one task against one model, produce one EvalLog.

This is the harness's entry point and the heart of the tracer bullet::

    log = run_task(task=spec, entry=model_entry, run_id=..., ...)

Guarantees this function makes
------------------------------
* **Every sample produces exactly one** :class:`~ida_core.contracts.ResultRecord`.
  A sample that errors gets a record with ``error`` set and ``score=None`` --
  it is never silently dropped, because a missing sample would quietly bias a
  mean score upward.  This holds for scorer failures and archival failures too,
  not only for model failures.
* **A model failure degrades one sample, not the run** -- but the run says so.
  ``status`` is derived from the error count by
  :func:`~ida_core.contracts.terminal_status`: no errors -> ``succeeded``,
  some -> ``partial``, all -> ``failed``.  A run in which every call failed is
  never reported ``succeeded``; that would claim a measurement that did not
  happen.
* **A cache hit is honest about being one.**  ``cached=True``, ``cost_usd=0``,
  ``latency_ms=0``, and the archived transcript still contains the real prompt.
* **Paid-for work is not discarded.**  If object storage refuses a transcript,
  the result is still recorded (with ``archive_error``); the completion was
  bought and scored, and only the evidence pointer is missing.
* **The serving config is stamped on every record** (D-1), including the
  *effective* sampling params after any per-run override.
* **Subjective tasks do not call a scorer.**  They yield ``scorable=False``,
  ``score=None`` records, so they appear in the UI as "not yet scorable"
  instead of as zeros that look like failures.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ida_core.artifacts import ArtifactStore, eval_log_key, sample_key
from ida_core.contracts import (
    EvalLog,
    ModelEntry,
    ResultRecord,
    SampleTranscript,
    SamplingParams,
    ServingConfig,
    TaskKind,
    TaskSpec,
    terminal_status,
)
from ida_core.db import utcnow
from ida_core.ids import new_result_id
from ida_harness import __version__ as harness_version
from ida_harness.cache import CachedCompletion, CompletionCache, NullCache, cache_key
from ida_harness.client import ModelClient
from ida_harness.errors import ModelError, ScoringError
from ida_harness.factory import build_client
from ida_harness.scoring import build_scorer
from ida_harness.solver import SingleTurnSolver, Solver

log = logging.getLogger(__name__)


def effective_serving_config(
    entry: ModelEntry, sampling_override: SamplingParams | None
) -> ServingConfig:
    """The serving config that will be stamped on results.

    Applies a per-run sampling override *into a copy*, so the registry entry is
    never mutated and the record shows the params actually used -- never the
    registry default the override replaced.
    """
    if sampling_override is None:
        return entry.serving.model_copy(deep=True)
    return entry.serving.model_copy(deep=True, update={"sampling": sampling_override})


def run_task(
    *,
    task: TaskSpec,
    entry: ModelEntry,
    run_id: str,
    api_key: str | None = None,
    task_git_sha: str | None = None,
    sweep_id: str | None = None,
    sampling_override: SamplingParams | None = None,
    artifact_store: ArtifactStore | None = None,
    solver: Solver | None = None,
    completion_cache: CompletionCache | None = None,
    client: ModelClient | None = None,
    client_factory: Callable[[], ModelClient] | None = None,
) -> EvalLog:
    """Execute ``task`` against ``entry`` and return a structured eval log.

    Parameters
    ----------
    artifact_store:
        Where transcripts and the eval log are archived.  ``None`` skips
        archival entirely and leaves ``transcript_uri`` unset -- useful in unit
        tests, never used in a deployed runner.
    client / client_factory:
        Supply a pre-built client (tests) or a factory (the runner service).
        A client passed in via ``client`` is **not** closed by this function --
        the caller owns it.  One built by ``client_factory`` is closed here.
    """
    started_at = utcnow()
    serving = effective_serving_config(entry, sampling_override)
    sampling = serving.sampling
    solver = solver or SingleTurnSolver()
    cache = completion_cache or NullCache()

    owns_client = False
    if client is None:
        if client_factory is not None:
            client = client_factory()
        else:
            # The factory, not a hardcoded class: which client answers is a
            # models.yaml decision (serving_stack), so the runner SERVICE gets
            # provider selection without knowing providers exist.
            client = build_client(entry, api_key=api_key)
        owns_client = True

    results: list[ResultRecord] = []
    transcripts: list[SampleTranscript] = []

    try:
        scorer = build_scorer(task.scorer) if task.is_scorable else None
        for sample in task.samples:
            repeat_index = 0  # repeated sampling (B7) is contract-ready, not yet emitted
            key = cache_key(
                serving=serving,
                sampling=sampling,
                task_id=task.id,
                task_content_sha=task.content_sha or None,
                sample=sample,
                repeat_index=repeat_index,
            )
            record = ResultRecord(
                id=new_result_id(),
                run_id=run_id,
                task_id=task.id,
                sample_id=sample.id,
                repeat_index=repeat_index,
                model_key=entry.key,
                serving_config=serving,
                task_content_sha=task.content_sha or None,
                scorable=task.is_scorable,
            )

            entry_from_cache = cache.get(key)
            try:
                if entry_from_cache is not None:
                    messages = list(entry_from_cache.messages)
                    completion = entry_from_cache.completion
                    record.cached = True
                else:
                    outcome = solver.solve(task, sample, client, sampling)
                    messages = outcome.messages
                    completion = outcome.completion
                    cache.put(key, CachedCompletion(messages=messages, completion=completion))
            except ModelError as exc:
                # One sample degraded, not the run -- but the run's error_count
                # records it, and terminal_status decides what to call the run.
                log.warning("run %s sample %s failed: %s", run_id, sample.id, exc)
                record.error = f"{type(exc).__name__}: {exc}"
                results.append(record)
                continue

            record.usage = completion.usage
            # A cache hit spent no money and took no time on THIS run. Reporting
            # the original call's figures would bill tokens that were never
            # purchased and show a latency that was never measured (B4).
            record.cost_usd = 0.0 if record.cached else completion.usage.cost_usd(entry.cost)
            record.latency_ms = 0.0 if record.cached else completion.latency_ms

            if scorer is not None:
                try:
                    record.score = scorer.score(completion.content, sample.target)
                except (ScoringError, ValueError) as exc:
                    # A malformed task sample must not discard the paid-for
                    # completions of its siblings (A8). Degrade this one.
                    log.warning("run %s sample %s could not be scored: %s", run_id, sample.id, exc)
                    record.error = f"{type(exc).__name__}: {exc}"

            transcript = SampleTranscript(
                run_id=run_id,
                task_id=task.id,
                sample_id=sample.id,
                model_key=entry.key,
                messages=messages,
                completion=completion.content,
                usage=completion.usage,
                latency_ms=completion.latency_ms,
                request_id=completion.request_id,
                raw_response=completion.raw,
            )
            transcripts.append(transcript)

            if artifact_store is not None:
                try:
                    record.transcript_uri = artifact_store.put_json(
                        sample_key(run_id, sample.id, repeat_index),
                        transcript.model_dump(mode="json"),
                    )
                except Exception as exc:
                    # The completion is bought and scored; only the evidence
                    # pointer is missing. Losing the result too would throw away
                    # real money because object storage blinked (A5).
                    log.exception("run %s sample %s: transcript archival failed", run_id, sample.id)
                    record.archive_error = f"{type(exc).__name__}: {exc}"

            results.append(record)
    finally:
        if owns_client:
            client.close()

    error_count = sum(1 for r in results if r.error is not None)
    eval_log = EvalLog(
        run_id=run_id,
        task_id=task.id,
        task_git_sha=task_git_sha,
        task_content_sha=task.content_sha or None,
        sweep_id=sweep_id,
        model_key=entry.key,
        serving_config=serving,
        harness_version=harness_version,
        # NOT hardcoded SUCCEEDED. A run where every sample errored measured
        # nothing and must not claim otherwise (B5).
        status=terminal_status(sample_count=len(results), error_count=error_count),
        results=results,
        transcripts=transcripts,
        started_at=started_at,
        finished_at=utcnow(),
    )
    eval_log.error = eval_log.error_summary()

    if artifact_store is not None:
        try:
            artifact_store.put_json(eval_log_key(run_id), eval_log.model_dump(mode="json"))
        except Exception:
            # Same reasoning as the per-sample archival guard: the results are
            # already in hand and about to be persisted to Postgres.
            log.exception("run %s: eval-log archival failed", run_id)

    return eval_log


def unscorable_reason(task: TaskSpec) -> str | None:
    """Human-readable reason a task cannot be scored yet, or ``None``.

    Surfaced by the API so the UI can explain a blank score instead of showing
    a zero that looks like a failing model.
    """
    if task.kind is TaskKind.SUBJECTIVE:
        return (
            "subjective task: requires LLM-as-judge scoring, which is not "
            "implemented in the walking skeleton"
        )
    return None
