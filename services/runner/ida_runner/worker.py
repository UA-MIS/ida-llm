"""The worker loop and the single-job execution path.

Split into :class:`Worker` (the loop, shutdown, error containment) and
:func:`execute_job` (one job, pure-ish and directly testable).  The e2e tracer
test drives :class:`Worker` on a thread; the unit tests drive
:func:`execute_job` directly.

Failure policy
--------------
* A job whose task/model cannot be resolved -> run ``failed`` with the reason.
  Nothing is retried; the message is gone.  See the known gap documented in
  :mod:`ida_core.queue`.
* A job that raises unexpectedly -> the run is marked ``failed`` with the
  exception text, and the **loop keeps going**.  A single poisonous job must
  never take a runner pod down; a crash-looping pod is how you lose a whole
  sweep.
* A payload that cannot be *decoded* -> dead-lettered by the queue
  (:data:`ida_core.queue.DEAD_LETTER_KEY`) and skipped, with the loop's own
  ``try`` around ``dequeue`` as a second line of defence.  This is the path a
  ``schema_version`` bump takes while old replicas are still rolling, so it has
  to be survivable rather than merely documented.
"""

from __future__ import annotations

import logging
import threading

from ida_core.artifacts import ArtifactStore
from ida_core.contracts import (
    ModelRegistry,
    RunJobMessage,
    RunRecord,
    RunStatus,
)
from ida_core.db import session_scope, utcnow
from ida_core.queue import RunQueue
from ida_core.registry import resolve_api_key
from ida_core.repositories import (
    finish_run,
    get_run,
    insert_results,
    mark_run_running,
    run_row_to_record,
)
from ida_harness import __version__ as harness_version
from ida_harness.cache import CompletionCache
from ida_harness.runner import effective_serving_config, run_task
from ida_harness.tasks import TaskCatalog
from ida_runner import metrics

log = logging.getLogger(__name__)


def execute_job(
    message: RunJobMessage,
    *,
    session_factory,
    registry: ModelRegistry,
    catalog: TaskCatalog,
    artifact_store: ArtifactStore | None,
    git_sha: str | None = None,
    completion_cache: CompletionCache | None = None,
    client_factory=None,
) -> RunRecord:
    """Execute one queue message end to end and return the finished run record.

    Never raises for an *expected* failure (unknown task, unknown model, missing
    API key, endpoint down): those become a ``failed`` run with a readable
    ``error``.  It does propagate genuinely unexpected exceptions so that
    :class:`Worker` can log them with a stack trace -- but the worker still
    marks the run failed before continuing.
    """
    with session_scope(session_factory) as session:
        row = get_run(session, message.run_id)
        if row is None:
            raise KeyError(
                f"queue message references unknown run {message.run_id!r}; "
                "the API commits the row before enqueueing, so this means data loss"
            )
        record = run_row_to_record(row)

    try:
        spec = catalog.get(message.task_id)
        entry = registry.get(message.model_key)
        api_key = resolve_api_key(entry)
    except Exception as exc:
        return _fail_run(session_factory, record, f"{type(exc).__name__}: {exc}")

    serving = effective_serving_config(entry, message.sampling_override)
    with session_scope(session_factory) as session:
        mark_run_running(session, record.id, serving)
    record.status = RunStatus.RUNNING
    record.started_at = utcnow()
    record.serving_config = serving

    try:
        eval_log = run_task(
            task=spec,
            entry=entry,
            run_id=record.id,
            api_key=api_key,
            task_git_sha=git_sha or record.task_git_sha,
            sweep_id=message.sweep_id or record.sweep_id,
            sampling_override=message.sampling_override,
            artifact_store=artifact_store,
            completion_cache=completion_cache,
            client_factory=client_factory,
        )
    except Exception as exc:  # setup-level failure: the whole run is bad
        log.exception("run %s failed during execution", record.id)
        return _fail_run(session_factory, record, f"{type(exc).__name__}: {exc}")

    total_usage = eval_log.total_usage
    # The harness already decided succeeded/partial/failed from the error count
    # (terminal_status). The worker copies that verdict rather than re-deriving
    # it -- and must never overwrite it with an unconditional SUCCEEDED, which
    # is what reported a run of four failed API calls as a success (B5).
    record.status = eval_log.status
    record.serving_config = eval_log.serving_config
    record.harness_version = eval_log.harness_version or harness_version
    record.task_content_sha = eval_log.task_content_sha or record.task_content_sha
    record.sample_count = len(eval_log.results)
    record.scored_count = eval_log.scored_count
    record.error_count = eval_log.error_count
    record.mean_score = eval_log.mean_score
    record.total_usage = total_usage
    record.total_cost_usd = sum(r.cost_usd for r in eval_log.results)
    record.error = eval_log.error
    record.started_at = eval_log.started_at
    record.finished_at = eval_log.finished_at

    with session_scope(session_factory) as session:
        insert_results(session, eval_log.results)
        finish_run(session, record)

    log.info(
        "run %s %s: %d/%d scored, %d errored, mean=%s",
        record.id,
        record.status.value,
        record.scored_count,
        record.sample_count,
        record.error_count,
        record.mean_score,
    )
    return record


def _fail_run(session_factory, record: RunRecord, error: str) -> RunRecord:
    """Persist a terminal ``failed`` state with a readable reason.

    Used for *setup* failures -- unknown task, unknown model, missing key, an
    unexpected exception. Per-sample failures never come through here; they are
    counted into ``error_count`` and let :func:`terminal_status` decide.
    """
    record.status = RunStatus.FAILED
    record.error = error
    record.finished_at = utcnow()
    with session_scope(session_factory) as session:
        finish_run(session, record)
    log.error("run %s failed: %s", record.id, error)
    return record


class Worker:
    """Long-lived queue consumer.

    Not thread-safe in itself; run one per thread/process.  :meth:`stop` is
    safe to call from another thread (and from a signal handler) -- it sets an
    ``Event`` that the loop checks between blocking dequeues.
    """

    def __init__(
        self,
        *,
        queue: RunQueue,
        session_factory,
        registry: ModelRegistry,
        catalog: TaskCatalog,
        artifact_store: ArtifactStore | None,
        git_sha: str | None = None,
        poll_timeout_s: int = 5,
        completion_cache: CompletionCache | None = None,
        client_factory=None,
    ) -> None:
        self._queue = queue
        self._session_factory = session_factory
        self._registry = registry
        self._catalog = catalog
        self._artifact_store = artifact_store
        self._git_sha = git_sha
        self._poll_timeout_s = poll_timeout_s
        self._completion_cache = completion_cache
        self._client_factory = client_factory
        self._stop = threading.Event()
        self.jobs_processed = 0
        """Count of messages consumed, successful or not.  Handy in tests."""

        self.dequeue_failures = 0
        """Times a queue read raised.  Should be 0; non-zero means the queue
        implementation broke its no-raise contract and is worth alerting on."""

    @property
    def queue(self) -> RunQueue:
        """The queue this worker consumes.

        Exposed so the metrics exporter can report `ida_llm_runner_queue_depth`
        from the SAME queue object the loop reads -- a second connection built
        from settings could point somewhere else after a config change and
        report a depth nobody is draining.
        """
        return self._queue

    def stop(self) -> None:
        """Ask the loop to exit after its current job.  Idempotent."""
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def run_forever(self, max_jobs: int | None = None) -> int:
        """Consume until :meth:`stop` is called or ``max_jobs`` are processed.

        ``max_jobs`` exists for tests and for a future "drain and exit" mode; a
        deployed runner passes ``None``.
        """
        log.info("runner started; polling every %ss", self._poll_timeout_s)
        while not self._stop.is_set():
            if max_jobs is not None and self.jobs_processed >= max_jobs:
                break

            # Defence in depth. RunQueue implementations are contracted not to
            # raise on a malformed payload (they dead-letter it), but this call
            # previously sat OUTSIDE any handler, so one unparseable message
            # took the whole process down -- exactly the failure this class's
            # docstring promises cannot happen. A long-lived consumer loop must
            # never let a transport-layer surprise become a process exit.
            try:
                message = self._queue.dequeue(timeout_s=self._poll_timeout_s)
            except Exception:
                log.exception("queue read failed; discarding and continuing")
                self.dequeue_failures += 1
                metrics.DEQUEUE_FAILURES.inc()
                continue

            if message is None:
                continue
            self.jobs_processed += 1
            self._process(message)
        log.info("runner stopped after %d job(s)", self.jobs_processed)
        return self.jobs_processed

    def _process(self, message: RunJobMessage) -> None:
        """Run one job, containing any exception so the loop survives it."""
        try:
            record = execute_job(
                message,
                session_factory=self._session_factory,
                registry=self._registry,
                catalog=self._catalog,
                artifact_store=self._artifact_store,
                git_sha=self._git_sha,
                completion_cache=self._completion_cache,
                client_factory=self._client_factory,
            )
        except Exception:
            metrics.JOBS.labels(outcome="crashed").inc()
            log.exception("unhandled error processing run %s", message.run_id)
        else:
            metrics.JOBS.labels(outcome=record.status.value).inc()
