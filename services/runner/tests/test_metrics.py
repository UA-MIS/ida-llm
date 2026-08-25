"""The runner's scrape surface.

The runner has no API and no probes, so this listener is the ONLY thing standing
between a silently-idle fleet and someone noticing. Every assertion here maps to
a line in `.devops/chart/base/` that would otherwise depend on untested
behaviour.
"""

from __future__ import annotations

import urllib.request

from _runner_helpers import job_message as _message
from prometheus_client import REGISTRY

from ida_core.queue import InMemoryQueue
from ida_runner import metrics


class TestQueueDepth:
    """`ida_llm_runner_queue_depth` is named in autoscaling.yaml as "now
    exported". If it stops being emitted, that comment becomes a lie and the
    switch to an external-metrics HPA silently has nothing to scale on."""

    def test_reports_the_live_depth(self) -> None:
        queue = InMemoryQueue()
        metrics.bind_queue_depth(queue)
        assert REGISTRY.get_sample_value("ida_llm_runner_queue_depth") == 0.0

    def test_tracks_the_queue_it_was_bound_to(self) -> None:
        """Bound to the worker's OWN queue object, not a second connection built
        from settings -- which could point elsewhere after a config change and
        report a depth nobody is draining."""
        queue = InMemoryQueue()
        metrics.bind_queue_depth(queue)
        queue.enqueue(_message("run_metrics_probe"))
        assert REGISTRY.get_sample_value("ida_llm_runner_queue_depth") == 1.0

    def test_an_unreachable_queue_reports_minus_one_not_zero(self) -> None:
        """THE important one.

        Zero is a real value meaning "nothing to do, do not scale up". Publishing
        it during a Redis outage tells the autoscaler exactly the wrong thing at
        exactly the wrong moment. -1 is outside the metric's natural range, so
        "idle" and "blind" stay distinguishable.
        """

        class DeadQueue:
            def depth(self):
                raise ConnectionError("redis is gone")

        metrics.bind_queue_depth(DeadQueue())
        assert REGISTRY.get_sample_value("ida_llm_runner_queue_depth") == -1.0


class TestListener:
    def test_serves_metrics_on_the_configured_port(self) -> None:
        port = _free_port()
        metrics.serve(port=port, addr="127.0.0.1")
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
        assert "ida_llm_runner_up" in body
        assert "ida_llm_runner_queue_depth" in body

    def test_a_taken_port_does_not_kill_the_runner(self, caplog) -> None:
        """Losing observability must not stop a pod draining the queue.

        The port is occupied by a socket this test HOLDS, rather than by a
        previous serve() call, so the bind failure is deterministic instead of
        depending on listener teardown order.
        """
        import socket

        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]

            with caplog.at_level("ERROR"):
                metrics.serve(port=port, addr="127.0.0.1")  # must not raise

        assert "could not start the metrics listener" in caplog.text


class TestJobOutcomes:
    def test_outcomes_are_labelled_not_collapsed(self) -> None:
        """A succeeded run and a partial one are different operational facts;
        a single `jobs_total` would hide a fleet erroring on every sample."""
        before = (
            REGISTRY.get_sample_value("ida_llm_runner_jobs_total", {"outcome": "succeeded"}) or 0.0
        )
        metrics.JOBS.labels(outcome="succeeded").inc()
        after = REGISTRY.get_sample_value("ida_llm_runner_jobs_total", {"outcome": "succeeded"})
        assert after == before + 1


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
