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

from ida_core.settings import get_settings

log = logging.getLogger("ida.runner")

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

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    # Fail fast and loudly if the broker is unreachable: a worker that silently
    # spins on a dead queue looks healthy and does nothing, which is worse than
    # a CrashLoopBackOff somebody can see.
    client.ping()
    log.info("connected to redis at %s", settings.redis_url)

    while not _shutdown:
        item = client.blpop(["ida:runs"], timeout=5)
        if item is None:
            continue
        _queue, payload = item
        log.info("claimed job %s (SCAFFOLD: not executed yet)", payload)
        # TODO(project): load the suite with ida_harness.load_tasks, build the
        # client with ida_harness.clients.build_client, score with
        # score_response, write results + push the transcript to MinIO.
        time.sleep(0.1)

    log.info("shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
