"""Runner entrypoint: ``python -m ida_runner.main`` (or the ``ida-runner`` script).

Shares the Python image with the API (D-5); only the container command differs.
Handles SIGTERM so a k8s rolling update drains the current job instead of
killing it mid-flight.
"""

from __future__ import annotations

import logging
import signal
import sys

from ida_core.artifacts import LocalArtifactStore, S3ArtifactStore
from ida_core.config import get_settings
from ida_core.configdb.crypto import DbCredentialResolver, parse_kek
from ida_core.db import make_engine, make_session_factory
from ida_core.queue import RedisQueue
from ida_harness.config_provider import build_provider
from ida_runner import metrics
from ida_runner.judging import build_judge_from_settings
from ida_runner.reaper import Reaper
from ida_runner.worker import Worker

log = logging.getLogger("ida_runner")


def build_worker() -> Worker:
    """Assemble the production worker from environment settings."""
    settings = get_settings()
    engine = make_engine(settings.database_url)

    if settings.artifact_backend == "local":
        store = LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    else:
        store = S3ArtifactStore.from_settings(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
    store.ensure_bucket()

    # ONE queue object, shared by the loop, the depth metric and the reaper.
    # Building a second connection from the same settings would look equivalent
    # and would silently stop being equivalent the moment anything reconfigures
    # one of them -- and a reaper pointed at a different Redis than the loop it
    # is reconciling would "recover" nothing while reporting success.
    queue = RedisQueue.from_url(
        settings.redis_url,
        max_attempts=settings.queue_max_attempts,
        heartbeat_ttl_s=settings.runner_heartbeat_ttl_s,
    )
    session_factory = make_session_factory(engine)
    # yaml mode: today's files, loaded once. db mode: seed-if-never-seeded, then
    # the live tables -- the worker re-reads a snapshot per job (see Worker).
    config = build_provider(settings, session_factory)
    snapshot = config.snapshot()
    registry = snapshot.registry

    # BUILT BEFORE THE WORKER, AND ALLOWED TO RAISE. A judge that cannot be
    # constructed is an operator who asked for grading and would not get it; the
    # runner must not come up healthy, grade nothing, and write blanks that read
    # exactly like "no judge configured". See ida_runner.judging.
    #
    # One judge for the process: it owns an HTTP client, and every job reuses it.
    # Nothing closes it, deliberately -- the worker loop's lifetime is the
    # process's, and the OS reclaims the socket at exit.
    # Admin-entered provider keys (credential_ref): decrypted at use time with
    # IDA_CREDENTIALS_KEK. parse_kek raises on a malformed KEK, so a runner that
    # cannot decrypt never comes up looking healthy.
    credentials = DbCredentialResolver(session_factory, parse_kek(settings.credentials_kek))
    judge = build_judge_from_settings(settings, registry, credentials)

    return Worker(
        queue=queue,
        session_factory=session_factory,
        registry=registry,
        catalog=snapshot.catalog,
        artifact_store=store,
        git_sha=snapshot.task_git_sha,
        config=config if settings.config_source == "db" else None,
        credentials=credentials,
        poll_timeout_s=settings.runner_poll_timeout_s,
        judge=judge,
        reaper=Reaper(
            queue=queue,
            session_factory=session_factory,
            stale_run_ttl_s=settings.stale_run_ttl_s,
        ),
        reaper_interval_s=settings.reaper_interval_s,
        heartbeat_interval_s=settings.runner_heartbeat_interval_s,
    )


def main() -> int:
    """Run the worker until SIGTERM/SIGINT.  Returns a process exit code."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    worker = build_worker()

    # The runner's ONLY listening socket. It serves the ServiceMonitor scrape and
    # nothing else -- no probes, no API. Started AFTER build_worker() so a
    # misconfigured runner crashes on its real problem rather than answering
    # scrapes while unable to work. See ida_runner.metrics for why port 9100 and
    # why the container port is named `http`.
    metrics.bind_queue_depth(worker.queue)
    metrics.serve(port=settings.runner_metrics_port)

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("received signal %s; finishing current job then exiting", signum)
        worker.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    worker.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
