"""The runner's Prometheus surface.

⚠ THE RUNNER HAS NO API AND NO PROBES. This listener exists for exactly one
consumer: the scrape. It is a Deployment that would otherwise expose no port at
all, and everything below follows from that.

THE PORT NAME IS LOAD-BEARING
-----------------------------
The container port in `.devops/chart/base/deployments.yaml` is named **http**,
not `metrics`, and renaming it blackholes the scrape. The Composition-owned
NetworkPolicy `allow-ingress-traefik-and-intra-ns` admits traffic from the
`monitoring` namespace on `port: http`, and a NetworkPolicy port name resolves
against the CONTAINER port name on the target pod. A port named `metrics` is
therefore not covered, and Prometheus reports the target DOWN with `context
deadline exceeded` -- which reads like a broken exporter rather than a firewall.
The SERVICE port is still called `metrics`, which is what the ServiceMonitor
selects on, so the readable name survives everywhere a human looks.

WHAT IS EMITTED, AND WHY EACH ONE
---------------------------------
``ida_llm_runner_up``            1 while this process is serving. Prometheus gets
                                 one target per pod, so `sum(...)` is a real
                                 replica count -- see servicemonitor.yaml.
``ida_llm_runner_queue_depth``   Pending jobs on the run queue. The HPA scales on
                                 CPU today because the platform runs neither
                                 prometheus-adapter nor KEDA, but CPU
                                 UNDER-scales this workload precisely when the
                                 queue is deepest: the runner blocks on remote
                                 LLM APIs, so a worker saturated with in-flight
                                 requests sits at low CPU. Queue depth is the
                                 honest signal, and autoscaling.yaml states it is
                                 already exported -- so emitting it keeps that
                                 comment true and makes the switch a chart edit
                                 rather than an app change.
``ida_llm_runner_jobs_total``    Messages consumed, by outcome.
``ida_llm_runner_dequeue_failures_total``
                                 Queue reads that raised. Should be 0 forever: a
                                 RunQueue is contracted not to raise on a
                                 malformed payload (it dead-letters), so any
                                 value here means an implementation broke its
                                 contract. Worth alerting on.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge, start_http_server

log = logging.getLogger(__name__)

UP = Gauge("ida_llm_runner_up", "1 while this runner process is serving.")

QUEUE_DEPTH = Gauge(
    "ida_llm_runner_queue_depth",
    "Jobs waiting on the run queue, as seen by this replica.",
)

JOBS = Counter(
    "ida_llm_runner_jobs_total",
    "Run jobs consumed by this replica, by outcome.",
    ["outcome"],
)

DEQUEUE_FAILURES = Counter(
    "ida_llm_runner_dequeue_failures_total",
    "Queue reads that raised. Non-zero means a RunQueue broke its no-raise contract.",
)


def bind_queue_depth(queue) -> None:
    """Report :attr:`QUEUE_DEPTH` by asking the queue at scrape time.

    A callback rather than a poll loop: the depth is only interesting when
    someone looks, and a background poller would hold a Redis connection open
    per replica for no benefit.

    A queue that cannot answer reports **-1**, not 0. Zero is a real, meaningful
    value ("nothing to do, do not scale up") and publishing it during a Redis
    outage would tell the autoscaler exactly the wrong thing at exactly the
    wrong moment. -1 is outside the metric's natural range, so a dashboard or
    rule can tell "idle" from "blind".
    """

    def _depth() -> float:
        try:
            return float(queue.depth())
        except Exception:
            log.warning("queue depth unavailable; reporting -1", exc_info=True)
            return -1.0

    QUEUE_DEPTH.set_function(_depth)


def serve(port: int = 9100, addr: str = "0.0.0.0") -> None:  # noqa: S104
    """Start the scrape listener on a daemon thread.

    0.0.0.0 is correct inside a container, not careless: a loopback bind is
    invisible to kube-proxy and the metric would never be scraped.

    Failure to bind is logged and swallowed. Losing observability must not take
    down a runner -- the pod's job is to drain the queue, and a metrics port
    that is already in use is not a reason to stop doing it.
    """
    try:
        start_http_server(port, addr=addr)
    except OSError:
        log.exception("could not start the metrics listener on %s:%s", addr, port)
        return
    UP.set(1)
    log.info("metrics listening on %s:%s/metrics", addr, port)
