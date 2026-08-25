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
``ida_llm_runner_job_retries_total``
                                 Jobs handed back for another attempt. A steady
                                 low rate is the durability machinery working; a
                                 SPIKE is a dependency failing under everyone.
``ida_llm_runner_dead_lettered_total``
                                 Jobs that exhausted their attempts. Every one is
                                 a run a human should look at -- this is the
                                 metric that says work was given up on, so it is
                                 the one worth paging nobody but alerting someone.
``ida_llm_runner_recovered_claims_total``
                                 Claims taken back from runners that died. Non-zero
                                 means pods are being lost; the jobs survived,
                                 which is the whole point, but the pods did not.
``ida_llm_runner_zombie_runs_total``
                                 Runs closed out by the age backstop -- stuck
                                 `running` with no claim anywhere. Should be rare;
                                 a rising count means claim records are being lost
                                 (Redis eviction?), not just pods.
``ida_llm_runner_duplicate_deliveries_total``
                                 Re-deliveries of an ALREADY-FINISHED run -- a
                                 runner committed its results and died before
                                 acking. Small and non-zero is at-least-once
                                 working; the job was not re-run, so the results
                                 were not duplicated.
``ida_llm_runner_ack_failures_total``
                                 Acks that raised. Each one is a finished job that
                                 will be re-delivered and re-run: wasteful, not
                                 lost. Non-zero means Redis is unhealthy.
``ida_llm_runner_reaper_failures_total``
                                 Recovery passes that raised. Housekeeping failing
                                 is survivable, but a persistently failing reaper
                                 means crashed runners' jobs are NOT coming back.
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

RETRIES = Counter(
    "ida_llm_runner_job_retries_total",
    "Run jobs returned to the queue for another attempt.",
)

DEAD_LETTERED = Counter(
    "ida_llm_runner_dead_lettered_total",
    "Run jobs parked after exhausting their attempts. Each one was given up on.",
)

RECOVERED_CLAIMS = Counter(
    "ida_llm_runner_recovered_claims_total",
    "Claims recovered from runners whose heartbeat lapsed.",
)

ZOMBIE_RUNS = Counter(
    "ida_llm_runner_zombie_runs_total",
    "Runs closed out as failed because nothing was claiming them any more.",
)

DUPLICATE_DELIVERIES = Counter(
    "ida_llm_runner_duplicate_deliveries_total",
    "Messages re-delivered for a run that had already finished. Expected to be "
    "small and non-zero: it is at-least-once delivery working as designed.",
)

ACK_FAILURES = Counter(
    "ida_llm_runner_ack_failures_total",
    "Acks that raised. Each one means a finished job will be re-delivered.",
)

REAPER_FAILURES = Counter(
    "ida_llm_runner_reaper_failures_total",
    "Recovery passes that raised. Persistent non-zero means crashed jobs are stuck.",
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
