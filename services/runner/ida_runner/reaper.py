"""Reconciling the queue with the database after a runner dies.

WHY THIS LIVES IN THE RUNNER, NOT IN A CRONJOB
----------------------------------------------
The obvious alternative was a fourth ``ida-sweep`` entry point on its own
schedule.  This is a periodic pass inside the runner loop instead, for three
reasons:

1. **It needs exactly what a runner already holds** -- the *same* queue object
   (so recovery and consumption cannot disagree about which Redis they mean, the
   same argument :attr:`ida_runner.worker.Worker.queue` makes for the depth
   metric) and a session factory.  A CronJob would rebuild both from settings.
2. **It needs no new deployment surface.**  No CronJob, no chart change, no
   schedule to keep in sync with ``reaper_interval_s``.  The runner Deployment
   is already always-on, which is the availability a recovery pass wants.
3. **``ida_runner.sweeps`` is about benchmark work**, not housekeeping.  Putting
   an operational reconciler behind ``ida-sweep`` would mean the CronJob that
   re-benchmarks models and the pass that fixes a crashed pod share a failure
   mode and a name.  They should not.

The cost is that **every replica runs it**.  That is affordable because the pass
is idempotent and lock-free: claims are taken with an atomic ``LMOVE`` before
they are inspected, so two reapers racing cannot both requeue one message (see
:mod:`ida_core.queue`), and the row writes are all "only if still non-terminal".

WHAT IT FIXES, IN ORDER
-----------------------
1. **Claim recovery (authoritative).**  A dead runner's processing list is
   drained: each claim is re-queued with ``attempt + 1``, or dead-lettered once
   attempts run out.  The rows follow -- back to ``queued``, or ``failed`` with
   a reason.  This is knowledge, not inference: the claim record says which
   runner held the job and the missing heartbeat says that runner is gone.
2. **Stale-run backstop (inference, last resort).**  A run can be stuck
   ``running`` with *no* claim anywhere -- Redis flushed, the key evicted, or a
   crash between ``mark_run_running`` and the ack bookkeeping.  Nothing can
   recover the work, but leaving the row ``running`` forever is a lie the UI
   repeats.  So a run older than ``stale_run_ttl_s`` **that no live consumer
   claims** is closed out as ``failed``.

The ``live_claims()`` check is what keeps step 2 honest.  Reaping on age alone
would mark a healthy, long-running eval as failed -- exactly the sort of false
statement about a measurement this platform exists to avoid.

⚠ THIS IS NOT A SWEEP BODY.  It performs no benchmark work and schedules no
runs; ``ida_runner.sweeps`` remains the home for that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from ida_core.db import session_scope, utcnow
from ida_core.queue import RecoveryReport, RunQueue
from ida_core.repositories import fail_run, list_stale_running_runs, requeue_run

log = logging.getLogger(__name__)

DEFAULT_STALE_RUN_TTL_S = 21600
"""Six hours.  See :attr:`ida_core.config.Settings.stale_run_ttl_s` for why long."""

DEFAULT_BATCH_LIMIT = 200
"""Rows one stale-run pass will close out.  Bounded so a pathological backlog
cannot turn a housekeeping pass into a long transaction; the overflow is
**logged**, never silently dropped -- a truncated pass that says nothing reads
as "there was nothing else"."""


@dataclass(frozen=True)
class ReaperReport:
    """What one :meth:`Reaper.sweep` did.  Returned rather than only logged so
    the worker can turn it into metrics and the tests can assert on it."""

    recovery: RecoveryReport = field(default_factory=RecoveryReport)
    """The transport half: claims taken off dead consumers."""

    requeued_runs: list[str] = field(default_factory=list)
    """Run rows put back to ``queued`` because their message is queued again."""

    failed_runs: list[str] = field(default_factory=list)
    """Run rows closed out ``failed`` after their message was dead-lettered."""

    zombie_runs: list[str] = field(default_factory=list)
    """Run rows closed out ``failed`` by the age backstop -- no claim, no runner."""

    truncated: bool = False
    """The stale-run pass hit its batch limit and there is more to do."""

    @property
    def changed(self) -> int:
        return len(self.requeued_runs) + len(self.failed_runs) + len(self.zombie_runs)


class Reaper:
    """Reconciles abandoned claims and zombie ``running`` rows.

    Holds the *same* queue instance the worker consumes from; see the module
    docstring.  Stateless between passes, so a replica restarting loses nothing.
    """

    def __init__(
        self,
        *,
        queue: RunQueue,
        session_factory,
        stale_run_ttl_s: int = DEFAULT_STALE_RUN_TTL_S,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
    ) -> None:
        self._queue = queue
        self._session_factory = session_factory
        self._stale_run_ttl_s = int(stale_run_ttl_s)
        self._batch_limit = int(batch_limit)

    def sweep(self) -> ReaperReport:
        """Run both passes once.  Safe to call concurrently from every replica."""
        recovery = self._queue.recover_abandoned()
        requeued, failed = self._reconcile(recovery)
        zombies, truncated = self._close_out_zombies()
        report = ReaperReport(
            recovery=recovery,
            requeued_runs=requeued,
            failed_runs=failed,
            zombie_runs=zombies,
            truncated=truncated,
        )
        if report.changed or recovery.total:
            log.warning(
                "reaper: %d claim(s) recovered from %s, %d run(s) requeued, "
                "%d failed after exhausting attempts, %d zombie(s) closed out",
                recovery.total,
                recovery.consumers_reaped or "-",
                len(requeued),
                len(failed),
                len(zombies),
            )
        return report

    # ------------------------------------------------------------ passes --

    def _reconcile(self, recovery: RecoveryReport) -> tuple[list[str], list[str]]:
        """Make the run rows agree with what recovery did to their messages."""
        requeued: list[str] = []
        failed: list[str] = []
        if not recovery.requeued and not recovery.dead_lettered:
            return requeued, failed

        with session_scope(self._session_factory) as session:
            for run_id in recovery.requeued:
                # None means the row is gone or already terminal -- the runner
                # finished and acked between its heartbeat lapsing and this
                # call. A normal race, and the queue's at-least-once contract
                # already covers the duplicate delivery it implies.
                if requeue_run(session, run_id) is not None:
                    requeued.append(run_id)
            for run_id, reason in recovery.dead_lettered:
                if fail_run(session, run_id, f"queue gave up: {reason}") is not None:
                    failed.append(run_id)
        return requeued, failed

    def _close_out_zombies(self) -> tuple[list[str], bool]:
        """Fail ``running`` rows that are old AND unclaimed by any live runner."""
        cutoff = utcnow() - timedelta(seconds=self._stale_run_ttl_s)
        live = self._queue.live_claims()
        closed: list[str] = []

        with session_scope(self._session_factory) as session:
            rows = list_stale_running_runs(session, started_before=cutoff, limit=self._batch_limit)
            truncated = len(rows) >= self._batch_limit
            for row in rows:
                if row.id in live:
                    # Old is not the same as abandoned. A live runner still
                    # holds this claim, so the run is slow, not stuck, and
                    # saying otherwise would be a false statement about a
                    # measurement in progress.
                    continue
                started = row.started_at.isoformat() if row.started_at else "never"
                if (
                    fail_run(
                        session,
                        row.id,
                        "abandoned: no runner has claimed this run and it has been "
                        f"'running' since {started} "
                        f"(longer than the {self._stale_run_ttl_s}s stale-run limit). "
                        "No results were recorded.",
                    )
                    is not None
                ):
                    closed.append(row.id)

        if truncated:
            log.warning(
                "reaper: stale-run pass stopped at its batch limit of %d; more remain "
                "and will be closed out on the next pass",
                self._batch_limit,
            )
        return closed, truncated
