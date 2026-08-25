"""Queue worker.

SCAFFOLDING. The loop below claims a job from Redis and does nothing useful with
it yet -- the point at this stage is that the Deployment starts, stays up, is
observable, and shuts down cleanly, so the deploy path can be proven end to end
before the real work exists.

⚠ SIGTERM HANDLING IS NOT SCAFFOLDING. Kubernetes sends SIGTERM and waits
terminationGracePeriodSeconds before SIGKILL. A worker that ignores it gets killed
mid-task on every rollout, which for a benchmark run means a half-written result.
Keep the handler when you replace the body.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from types import FrameType

import redis
from prometheus_client import Counter, Gauge, start_http_server

from ida_core.settings import get_settings

log = logging.getLogger("ida.runner")

# ── METRICS ──────────────────────────────────────────────────────────────────
# The runner has no HTTP API, so before this it was INVISIBLE to Prometheus: the
# only signal that every worker had died was that the queue stopped draining,
# which nobody watches at 03:00. `ida_llm_runner_up` exists so an alert can say
# "no workers are alive" -- deliberately a plain Gauge set to 1 at startup rather
# than anything cleverer, because the useful query is `sum(...) == 0` / absent(),
# and a metric that STOPS BEING REPORTED is exactly the signal wanted.
METRICS_PORT = 9100

RUNNER_UP = Gauge(
    "ida_llm_runner_up",
    "1 while this runner process is claiming work. Absent or 0 means the worker is gone.",
)
JOBS_CLAIMED = Counter(
    "ida_llm_runner_jobs_claimed_total",
    "Jobs claimed from the queue by this runner.",
)
QUEUE_DEPTH = Gauge(
    "ida_llm_runner_queue_depth",
    "Items waiting in the run queue, as observed by this runner.",
)

_shutdown = False


def _handle_sigterm(signum: int, frame: FrameType | None) -> None:
    global _shutdown  # noqa: PLW0603
    log.info("received signal %s -- finishing current item then exiting", signum)
    _shutdown = True


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    # Metrics listener BEFORE the redis connect: if the broker is unreachable the
    # process exits, and the scrape target should still have existed so the gap is
    # visible rather than looking like the pod was never scheduled.
    start_http_server(METRICS_PORT)
    log.info("metrics listening on :%s/metrics", METRICS_PORT)

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    # Fail fast and loudly if the broker is unreachable: a worker that silently
    # spins on a dead queue looks healthy and does nothing, which is worse than
    # a CrashLoopBackOff somebody can see.
    client.ping()
    log.info("connected to redis at %s", settings.redis_url)
    RUNNER_UP.set(1)

    while not _shutdown:
        try:
            QUEUE_DEPTH.set(client.llen("ida:runs"))
        except Exception:  # noqa: BLE001 -- a metrics read must never kill the worker
            log.debug("could not read queue depth", exc_info=True)

        item = client.blpop(["ida:runs"], timeout=5)
        if item is None:
            continue
        _queue, payload = item
        JOBS_CLAIMED.inc()
        log.info("claimed job %s (SCAFFOLD: not executed yet)", payload)
        # TODO(project): load the suite with ida_harness.load_tasks, build the
        # client with ida_harness.clients.build_client, score with
        # score_response, write results + push the transcript to MinIO.
        time.sleep(0.1)

    # Drop to 0 on a CLEAN shutdown so a rolling deploy does not read as a crash
    # to the alert -- a scrape may well catch this before the pod disappears.
    RUNNER_UP.set(0)
    log.info("shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
