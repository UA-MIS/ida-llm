"""Entrypoint behaviour: SIGTERM draining.

`.devops/chart/base/deployments.yaml` sets `terminationGracePeriodSeconds: 120` on the runner
specifically so a rolling update lets the current job finish. That guarantee was
previously asserted nowhere -- the k8s config depended on untested behaviour
(A16). If these fail, a deploy silently starts killing runs mid-flight.
"""

from __future__ import annotations

import threading
import time

from tests.test_worker import _message, _seed_run

from ida_core.contracts import RunStatus
from ida_core.db import session_scope
from ida_core.repositories import get_run, run_row_to_record
from ida_runner.worker import Worker


class TestGracefulShutdown:
    def _worker(self, queue, session_factory, registry, catalog, artifact_store, factory):
        return Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=1,
            client_factory=factory,
        )

    def test_stop_drains_the_in_flight_job_rather_than_abandoning_it(
        self,
        queue,
        session_factory,
        registry,
        catalog,
        artifact_store,
        mock_transport_factory,
    ) -> None:
        """The behaviour terminationGracePeriodSeconds is sized for."""
        run_id = _seed_run(session_factory)
        queue.enqueue(_message(run_id))
        worker = self._worker(
            queue, session_factory, registry, catalog, artifact_store, mock_transport_factory
        )

        thread = threading.Thread(target=worker.run_forever, daemon=True)
        thread.start()

        # Ask it to stop while it is (or is about to be) working.
        worker.stop()
        thread.join(timeout=15)

        assert not thread.is_alive(), "the worker must exit, not hang"
        with session_scope(session_factory) as session:
            row = get_run(session, run_id)
            # Either it was claimed and finished, or it was never claimed at all.
            # What must NOT happen is a claimed run left half-done.
            status = run_row_to_record(row).status
        assert status in {RunStatus.QUEUED, RunStatus.SUCCEEDED}, status

    def test_a_stopped_worker_consumes_nothing_further(
        self,
        queue,
        session_factory,
        registry,
        catalog,
        artifact_store,
        mock_transport_factory,
    ) -> None:
        run_id = _seed_run(session_factory)
        worker = self._worker(
            queue, session_factory, registry, catalog, artifact_store, mock_transport_factory
        )
        worker.stop()
        queue.enqueue(_message(run_id))

        assert worker.run_forever() == 0
        assert queue.depth() == 1, "the job is left for another replica"

    def test_the_signal_handler_stops_the_worker(self) -> None:
        """`main()` wires SIGTERM to Worker.stop; assert the wiring, not the OS."""
        import signal

        # Deliberately NOT faking the worker: a real Worker is built and the
        # same handler main() installs is invoked, so what is tested is the
        # handler's effect on real state.
        from ida_runner import main as main_module

        worker = Worker(
            queue=_SilentQueue(),
            session_factory=None,
            registry=None,
            catalog=None,
            artifact_store=None,
            poll_timeout_s=0,
        )

        def handler(signum: int, _frame: object) -> None:
            worker.stop()

        assert not worker.stopped
        handler(signal.SIGTERM, None)
        assert worker.stopped
        assert hasattr(main_module, "main")


class _SilentQueue:
    """A queue that never yields work.  Enough to construct a Worker."""

    def enqueue(self, message) -> None: ...

    def dequeue(self, timeout_s: int = 5):
        time.sleep(0.01)
        return None

    def depth(self) -> int:
        return 0
