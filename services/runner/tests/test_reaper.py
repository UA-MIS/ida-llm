"""The reaper: making run rows agree with reality after a runner dies.

The queue's own recovery is tested in ``packages/core/tests/test_queue.py``.
What is tested HERE is the half that queue cannot do -- the database.  A message
put back on the queue while its row still says ``running`` is only half a fix,
and the half that is missing is the half a human looks at.

Failure paths first (L-1/L-2). The happy path here is "nothing to do", and it is
asserted mainly to prove a quiet pass really is quiet.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from _runner_helpers import job_message as _message
from _runner_helpers import seed_run as _seed_run

from ida_core.contracts import RunStatus
from ida_core.db import session_scope, utcnow
from ida_core.queue import InMemoryQueue
from ida_core.repositories import get_run, run_row_to_record
from ida_runner.reaper import Reaper

AN_HOUR = 3600


@pytest.fixture
def dying() -> InMemoryQueue:
    """The runner that is about to be killed."""
    return InMemoryQueue(consumer_id="runner-a", max_attempts=3)


@pytest.fixture
def survivor(dying: InMemoryQueue) -> InMemoryQueue:
    """A second replica on the same queue -- the one that runs the pass."""
    return dying.for_consumer("runner-b")


def _status(session_factory, run_id: str) -> RunStatus:
    with session_scope(session_factory) as session:
        return run_row_to_record(get_run(session, run_id)).status


def _record(session_factory, run_id: str):
    with session_scope(session_factory) as session:
        return run_row_to_record(get_run(session, run_id))


def _reaper(queue, session_factory, **kwargs) -> Reaper:
    kwargs.setdefault("stale_run_ttl_s", 6 * AN_HOUR)
    return Reaper(queue=queue, session_factory=session_factory, **kwargs)


class TestClaimRecovery:
    """A runner died holding a claim.  The message comes back; so must the row."""

    def test_a_recovered_run_goes_back_to_queued_not_left_running(
        self, session_factory, dying, survivor
    ) -> None:
        """THE bug this story exists to fix, at the row level.

        Under the old BLPOP loop the message was gone and the row said
        `running` for ever -- a status the UI faithfully repeated to a human who
        had no way to know it was false.
        """
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        dying.enqueue(_message(run_id))
        dying.dequeue(timeout_s=0)
        dying.simulate_consumer_death()

        report = _reaper(survivor, session_factory).sweep()

        assert report.requeued_runs == [run_id]
        assert _status(session_factory, run_id) is RunStatus.QUEUED
        assert _record(session_factory, run_id).started_at is None, "it is not running now"
        assert survivor.depth() == 1, "and the message is waiting for whoever is next"

    def test_an_exhausted_claim_fails_the_run_with_a_reason_a_human_can_act_on(
        self, session_factory, dying
    ) -> None:
        """Bounded retry has to end SOMEWHERE, and the ending must be honest."""
        survivor = dying.for_consumer("runner-b")
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        dying.enqueue(_message(run_id, attempt=3))  # its last life
        dying.dequeue(timeout_s=0)
        dying.simulate_consumer_death()

        report = _reaper(survivor, session_factory).sweep()

        assert report.failed_runs == [run_id]
        record = _record(session_factory, run_id)
        assert record.status is RunStatus.FAILED, "never left 'running'"
        assert record.error and "gave up" in record.error
        assert record.finished_at is not None
        assert survivor.depth() == 0, "not going round again"
        assert len(survivor.dead_letters) == 1, "parked where a human can find it"

    def test_a_run_that_finished_during_the_race_is_not_clobbered(
        self, session_factory, dying, survivor
    ) -> None:
        """The runner may have finished and acked between its heartbeat lapsing
        and this pass.  Overwriting a real, measured verdict with a guess is
        exactly the false statement this platform exists to avoid."""
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        dying.enqueue(_message(run_id))
        dying.dequeue(timeout_s=0)
        dying.simulate_consumer_death()
        # ... and only now does the truth arrive: it actually succeeded.
        with session_scope(session_factory) as session:
            get_run(session, run_id).status = RunStatus.SUCCEEDED.value

        report = _reaper(survivor, session_factory).sweep()

        assert report.requeued_runs == [], "the row was already terminal"
        assert _status(session_factory, run_id) is RunStatus.SUCCEEDED

    def test_a_live_runners_claim_is_never_recovered(
        self, session_factory, dying, survivor
    ) -> None:
        """A slow runner is not a dead one."""
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        dying.enqueue(_message(run_id))
        dying.dequeue(timeout_s=0)  # still heartbeating

        report = _reaper(survivor, session_factory).sweep()

        assert report.changed == 0
        assert _status(session_factory, run_id) is RunStatus.RUNNING


class TestStaleRunBackstop:
    """For runs whose claim record is gone entirely -- Redis flushed, key evicted."""

    def test_a_zombie_running_run_is_closed_out_honestly(self, session_factory, survivor) -> None:
        run_id = _seed_run(
            session_factory,
            status=RunStatus.RUNNING,
            started_at=utcnow() - timedelta(hours=9),
        )

        report = _reaper(survivor, session_factory).sweep()

        assert report.zombie_runs == [run_id]
        record = _record(session_factory, run_id)
        assert record.status is RunStatus.FAILED
        assert record.error is not None
        assert "abandoned" in record.error
        assert "No results were recorded" in record.error, (
            "a failed run with no results must not read as a measurement of zero"
        )

    def test_a_run_marked_running_that_never_started_is_a_zombie_too(
        self, session_factory, survivor
    ) -> None:
        """A partially-applied claim is stuck in exactly the same way."""
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=None)

        report = _reaper(survivor, session_factory).sweep()

        assert report.zombie_runs == [run_id]

    def test_a_recent_running_run_is_left_alone(self, session_factory, survivor) -> None:
        run_id = _seed_run(
            session_factory, status=RunStatus.RUNNING, started_at=utcnow() - timedelta(minutes=2)
        )

        report = _reaper(survivor, session_factory).sweep()

        assert report.zombie_runs == []
        assert _status(session_factory, run_id) is RunStatus.RUNNING

    def test_an_OLD_run_a_live_runner_still_holds_is_left_alone(
        self, session_factory, dying, survivor
    ) -> None:
        """The single assertion that keeps the age backstop from lying.

        An LLM eval can legitimately run for hours. Reaping on age alone would
        report a healthy, in-progress measurement as failed -- and the runner
        doing it would then write a real verdict over the top, so the run's
        history would contain both.
        """
        run_id = _seed_run(
            session_factory,
            status=RunStatus.RUNNING,
            started_at=utcnow() - timedelta(hours=9),
        )
        dying.enqueue(_message(run_id))
        dying.dequeue(timeout_s=0)  # claimed by a LIVE runner, and very old

        report = _reaper(survivor, session_factory, stale_run_ttl_s=AN_HOUR).sweep()

        assert report.zombie_runs == []
        assert _status(session_factory, run_id) is RunStatus.RUNNING

    def test_a_queued_run_is_not_a_zombie_however_old(self, session_factory, survivor) -> None:
        """`queued` means nobody has claimed it yet, which is not the same as
        stuck -- a backlog is a capacity problem, not a data-integrity one."""
        run_id = _seed_run(session_factory, status=RunStatus.QUEUED)

        report = _reaper(survivor, session_factory).sweep()

        assert report.zombie_runs == []
        assert _status(session_factory, run_id) is RunStatus.QUEUED

    def test_the_pass_is_bounded_and_SAYS_it_was_bounded(self, session_factory, survivor) -> None:
        """A truncated pass that says nothing reads as "there was nothing else"."""
        old = utcnow() - timedelta(hours=9)
        ids = [
            _seed_run(session_factory, status=RunStatus.RUNNING, started_at=old) for _ in range(3)
        ]

        reaper = _reaper(survivor, session_factory, batch_limit=2)
        first = reaper.sweep()

        assert len(first.zombie_runs) == 2
        assert first.truncated is True, "the caller can tell there is more"

        second = reaper.sweep()
        assert len(second.zombie_runs) == 1
        assert second.truncated is False
        assert {_status(session_factory, i) for i in ids} == {RunStatus.FAILED}


class TestSweepBehaviour:
    def test_a_quiet_pass_changes_nothing(self, session_factory, survivor) -> None:
        report = _reaper(survivor, session_factory).sweep()
        assert report.changed == 0
        assert report.recovery.total == 0
        assert report.truncated is False

    def test_the_sweep_is_idempotent(self, session_factory, dying, survivor) -> None:
        """Every replica runs this pass; running it twice must not double-count."""
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        dying.enqueue(_message(run_id))
        dying.dequeue(timeout_s=0)
        dying.simulate_consumer_death()
        reaper = _reaper(survivor, session_factory)

        first = reaper.sweep()
        second = reaper.sweep()

        assert first.requeued_runs == [run_id]
        assert second.changed == 0
        assert survivor.depth() == 1, "requeued exactly once, not twice"

    def test_two_reapers_racing_requeue_the_message_only_once(self, session_factory, dying) -> None:
        """The lock-free claim: whoever LMOVEs it first owns the decision."""
        first_reaper = dying.for_consumer("runner-b")
        second_reaper = dying.for_consumer("runner-c")
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        dying.enqueue(_message(run_id))
        dying.dequeue(timeout_s=0)
        dying.simulate_consumer_death()

        a = _reaper(first_reaper, session_factory).sweep()
        b = _reaper(second_reaper, session_factory).sweep()

        assert len(a.requeued_runs) + len(b.requeued_runs) == 1
        assert first_reaper.depth() == 1
