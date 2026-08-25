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
from ida_core.db import make_engine, make_session_factory
from ida_core.gitmeta import current_git_sha
from ida_core.queue import RedisQueue
from ida_core.registry import load_registry
from ida_harness.tasks import TaskCatalog
from ida_runner import metrics
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

    return Worker(
        queue=RedisQueue.from_url(settings.redis_url),
        session_factory=make_session_factory(engine),
        registry=load_registry(settings.resolved_models_file()),
        catalog=TaskCatalog.from_directory(settings.resolved_tasks_dir()),
        artifact_store=store,
        git_sha=current_git_sha(settings.resolved_tasks_dir()),
        poll_timeout_s=settings.runner_poll_timeout_s,
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
