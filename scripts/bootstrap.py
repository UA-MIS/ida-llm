#!/usr/bin/env python3
"""One-shot bootstrap for the local docker-compose stack.

Waits for Postgres, creates the schema, creates the MinIO bucket, then exits 0.
Everything downstream in ``docker-compose.yml`` waits on
``service_completed_successfully``, which removes the usual "API crashed because
Postgres was not up yet" startup race.

In a cluster this job is replaced by an Alembic migration Job -- see
the `migrate` initContainer on the api Deployment (`.devops/chart/base/deployments.yaml`)
and the note in ``ida_core.bootstrap``.
"""

from __future__ import annotations

import logging
import sys

from ida_core.artifacts import LocalArtifactStore, S3ArtifactStore
from ida_core.bootstrap import bootstrap_schema, wait_for_database
from ida_core.config import get_settings

logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
log = logging.getLogger("bootstrap")


def main() -> int:
    settings = get_settings()

    log.info("waiting for database at %s", settings.database_url.split("@")[-1])
    wait_for_database(settings.database_url)
    bootstrap_schema(settings.database_url)

    if settings.artifact_backend == "local":
        store = LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    else:
        log.info("ensuring bucket %s at %s", settings.s3_bucket, settings.s3_endpoint_url)
        store = S3ArtifactStore.from_settings(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )
    store.ensure_bucket()

    log.info("bootstrap complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
