"""The worker loop and the single-job execution path.

Split into :class:`Worker` (the loop, shutdown, error containment) and
:func:`execute_job` (one job, pure-ish and directly testable).  The e2e tracer
test drives :class:`Worker` on a thread; the unit tests drive
:func:`execute_job` directly.

Failure policy
--------------
* A job whose task/model cannot be resolved -> run ``failed`` with the reason,
  and the message is **acked**.  A verdict is a finished job: re-delivering it
  would produce the same verdict three times over.
* A job that raises unexpectedly -> the message is **nacked**.  The queue either
  returns it for another attempt or, once ``queue_max_attempts`` deliveries are
  spent, dead-letters it -- at which point the run is marked ``failed`` with an
  honest "gave up after N attempts" reason rather than left ``running``.  The
  **loop keeps going** either way: a single poisonous job must never take a
  runner pod down; a crash-looping pod is how you lose a whole sweep.
* A payload that cannot be *decoded* -> dead-lettered by the queue
  (:data:`ida_core.queue.DEAD_LETTER_KEY`) and skipped, with the loop's own
  ``try`` around ``dequeue`` as a second line of defence.  This is the path a
  ``schema_version`` bump takes while old replicas are still rolling, so it has
  to be survivable rather than merely documented.
* **The process dies mid-job** -> nothing here runs at all, which is the point.
  The message is still on this consumer's processing list, and once the
  heartbeat below lapses another replica's :class:`~ida_runner.reaper.Reaper`
  recovers it.  This is the failure the old ``BLPOP`` loop could not survive.

Liveness
--------
:meth:`Worker.run_forever` keeps a daemon thread refreshing the queue's
heartbeat.  The idle loop would heartbeat on its own (every ``dequeue`` does),
but a runner is *least* idle exactly when it most needs to look alive: a job
that takes longer than the heartbeat TTL would otherwise be recovered and run
a second time by a replica that thinks this pod is dead.  Distinguishing "slow"
from "gone" is what the thread buys.

⚠ RETRY IS INDISCRIMINATE, ON PURPOSE. An unexpected exception is retried
whether or not it can ever succeed, because the loop cannot tell a transient
transport failure from a permanent one -- and guessing wrong in the direction of
"permanent" silently drops work. A genuinely hopeless job (an unknown ``run_id``,
say) therefore burns its attempts and lands on the dead-letter list with the
reason attached, which is bounded, visible, and self-explaining.
"""

from __future__ import annotations

import logging
import threading
import time

from ida_core.artifacts import ArtifactStore
from ida_core.contracts import (
    TERMINAL_RUN_STATUSES,
    ModelRegistry,
    RunJobMessage,
    RunRecord,
    RunStatus,
)
from ida_core.db import session_scope, utcnow
from ida_core.gitmeta import build_identity
from ida_core.queue import NackOutcome, RunQueue
from ida_core.registry import resolve_api_key
from ida_core.repositories import (
    fail_run,
    finish_run,
    get_run,
    insert_results,
    mark_run_running,
    requeue_run,
    run_row_to_record,
)
from ida_harness.cache import CompletionCache
from ida_harness.runner import effective_serving_config, run_task
from ida_harness.tasks import TaskCatalog
from ida_runner import metrics
from ida_runner.reaper import Reaper

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

    # AT-LEAST-ONCE'S ONE SHARP EDGE, BLUNTED HERE.
    # A runner that commits a finished run and dies before acking will see this
    # message again. Re-running it would append a SECOND full set of result rows
    # for the same run -- and results are the citable evidence a recommendation
    # is built on (D-3), so duplicating them corrupts the thing the platform
    # exists to produce, quietly and permanently. A terminal run is work already
    # done: report it and let the caller ack.
    if record.status in TERMINAL_RUN_STATUSES:
        log.info(
            "run %s is already %s (attempt %d); ignoring the re-delivery",
            record.id,
            record.status.value,
            message.attempt,
        )
        metrics.DUPLICATE_DELIVERIES.inc()
        return record

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
    record.harness_version = eval_log.harness_version or build_identity()
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

    Not thread-safe in itself; run one per thread/process -- the queue's claim
    bookkeeping is per-consumer and assumes exactly that.  :meth:`stop` is safe
    to call from another thread (and from a signal handler): it sets an
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
        reaper: Reaper | None = None,
        reaper_interval_s: float = 60.0,
        heartbeat_interval_s: float = 30.0,
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
        self._reaper = reaper
        self._reaper_interval_s = reaper_interval_s
        self._heartbeat_interval_s = heartbeat_interval_s
        self._stop = threading.Event()
        self._heartbeat_stop: threading.Event | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._last_reap_at: float | None = None

        self.jobs_processed = 0
        """Count of messages consumed, successful or not.  Handy in tests."""

        self.dequeue_failures = 0
        """Times a queue read raised.  Should be 0; non-zero means the queue
        implementation broke its no-raise contract and is worth alerting on."""

        self.jobs_retried = 0
        """Messages handed back for another attempt after an unexpected error."""

        self.jobs_dead_lettered = 0
        """Messages that ran out of attempts and were parked with a reason."""

        self.ack_failures = 0
        """Acks that raised.  Each one means a finished job stays claimed and is
        eventually re-delivered -- wasteful, but never lost, and never fatal."""

        self.reaper_failures = 0
        """Reaper passes that raised.  Housekeeping failing must not stop work."""

    @property
    def queue(self) -> RunQueue:
        """The queue this worker consumes.

        Exposed so the metrics exporter can report `ida_llm_runner_queue_depth`
        from the SAME queue object the loop reads -- a second connection built
        from settings could point somewhere else after a config change and
        report a depth nobody is draining.  The reaper is handed this same
        object for the same reason.
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
        self._start_heartbeat()
        try:
            while not self._stop.is_set():
                if max_jobs is not None and self.jobs_processed >= max_jobs:
                    break

                self._maybe_reap()

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
        finally:
            self._stop_heartbeat()
        log.info("runner stopped after %d job(s)", self.jobs_processed)
        return self.jobs_processed

    # --------------------------------------------------------- one job ----

    def _process(self, message: RunJobMessage) -> None:
        """Run one job, containing any exception so the loop survives it.

        Terminal verdict -> ack.  Unexpected explosion -> nack, which is what
        turns "this pod fell over" into "another pod picks it up" instead of
        "that run is gone and its row says ``running`` forever".
        """
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
        except Exception as exc:
            metrics.JOBS.labels(outcome="crashed").inc()
            log.exception("unhandled error processing run %s", message.run_id)
            self._return_to_queue(message, f"{type(exc).__name__}: {exc}")
        else:
            metrics.JOBS.labels(outcome=record.status.value).inc()
            self._ack(message)

    def _ack(self, message: RunJobMessage) -> None:
        """Drop the claim.  A failure here is wasteful, never destructive."""
        ack = getattr(self._queue, "ack", None)
        if ack is None:
            return  # a queue without claims: nothing to release
        try:
            ack(message)
        except Exception:
            # The claim stays; recovery re-delivers the job later and it runs a
            # second time. At-least-once already promises that, and raising here
            # would trade a duplicate for a dead runner.
            self.ack_failures += 1
            metrics.ACK_FAILURES.inc()
            log.exception("could not ack run %s; it may be re-delivered", message.run_id)

    def _return_to_queue(self, message: RunJobMessage, reason: str) -> None:
        """Nack, then make the run row agree with what the queue decided."""
        nack = getattr(self._queue, "nack", None)
        if nack is None:
            # A queue with no retry support. Say so, and still close the run out
            # honestly rather than leaving it 'running' with nobody on it.
            log.error(
                "queue %s cannot retry; run %s is closed out instead",
                type(self._queue).__name__,
                message.run_id,
            )
            self._close_out(message.run_id, reason)
            return

        try:
            outcome = nack(message, reason)
        except Exception:
            log.exception("could not return run %s to the queue", message.run_id)
            return

        if outcome is NackOutcome.DEAD_LETTERED:
            self.jobs_dead_lettered += 1
            metrics.DEAD_LETTERED.inc()
            self._close_out(
                message.run_id,
                f"gave up after {message.attempt} attempt(s): {reason}",
            )
        else:
            self.jobs_retried += 1
            metrics.RETRIES.inc()
            self._reset_to_queued(message.run_id)

    def _close_out(self, run_id: str, error: str) -> None:
        """Persist ``failed`` for a run nobody is going to finish.

        The whole point of the durability pass: a run whose message is gone must
        never be left saying ``running``.
        """
        try:
            with session_scope(self._session_factory) as session:
                if fail_run(session, run_id, error) is None:
                    log.warning("run %s is missing or already terminal; not overwriting", run_id)
        except Exception:
            log.exception("could not mark run %s failed", run_id)

    def _reset_to_queued(self, run_id: str) -> None:
        """A retried run is waiting, not running.  Say so."""
        try:
            with session_scope(self._session_factory) as session:
                requeue_run(session, run_id)
        except Exception:
            log.exception("could not return run %s to 'queued'", run_id)

    # ------------------------------------------------------ housekeeping ----

    def _maybe_reap(self) -> None:
        """Run the recovery pass if one is configured and due.

        Time-driven inside the consume loop rather than on its own thread: a
        reaper pass and a job never overlap in one replica, so the pass cannot
        compete with work for the runner's connection or its GIL.
        """
        if self._reaper is None or self._reaper_interval_s < 0:
            return
        now = time.monotonic()
        if self._last_reap_at is not None and now - self._last_reap_at < self._reaper_interval_s:
            return
        self._last_reap_at = now
        try:
            report = self._reaper.sweep()
        except Exception:
            # Housekeeping is not the job. A reaper that cannot reach Redis or
            # the database must not stop this replica from draining the queue.
            self.reaper_failures += 1
            metrics.REAPER_FAILURES.inc()
            log.exception("reaper pass failed; continuing to consume")
            return
        metrics.RECOVERED_CLAIMS.inc(report.recovery.total)
        metrics.ZOMBIE_RUNS.inc(len(report.zombie_runs))

    def _start_heartbeat(self) -> None:
        """Keep this consumer visibly alive while a long job is in flight.

        Without it a job that outlives the heartbeat TTL makes a healthy runner
        look dead, and its claim gets recovered and run twice.
        """
        heartbeat = getattr(self._queue, "heartbeat", None)
        if heartbeat is None or self._heartbeat_interval_s <= 0:
            return
        stop = threading.Event()

        def _beat() -> None:
            while not stop.wait(self._heartbeat_interval_s):
                try:
                    heartbeat()
                except Exception:
                    log.warning("heartbeat failed; claims may be recovered early", exc_info=True)

        self._heartbeat_stop = stop
        self._heartbeat_thread = threading.Thread(target=_beat, name="queue-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
        self._heartbeat_stop = None
        self._heartbeat_thread = None
