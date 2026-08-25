"""Shared settings.  One class, read by api, runner, sweeps and the tracer bullet.

Everything is env-driven (12-factor) because in-cluster the values arrive as env
vars: non-secret ones from the ConfigMap ``ida-llm-config``, secret ones from
Vault via ESO.  Nothing here has a secret as a *default*; secrets default to
empty and the service fails loudly if it needs one.

TWO NAMING CONVENTIONS, DELIBERATELY
------------------------------------
The platform supplies its seven values **unprefixed** -- ``DATABASE_URL``,
``REDIS_URL``, ``LOG_LEVEL``, ``MINIO_*`` -- via ``envFrom: configMapRef`` and
``secretKeyRef``.  A bare ``env_prefix="IDA_"`` would see **none** of them, and
the failure is silent: every field quietly keeps its default and the pod serves
against ``postgres:5432`` while reporting Ready.

So the seven the platform actually writes are **dual-aliased**: ``IDA_``-prefixed
first (local dev, tests, docker-compose), platform name second.  Everything else
stays ``IDA_``-only because it has no ConfigMap entry and defaults correctly
inside the image.

If you add a setting, add it in THREE places or it works locally and is missing
in the cluster: here, ``.env.example``, and the ConfigMap or the ExternalSecret.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    """Best-effort monorepo root.

    Resolution order: ``IDA_REPO_ROOT`` env (set to /app in the image) -> walk up
    from this file looking for ``models.yaml`` + ``tasks/``.  Returns the cwd as
    a last resort rather than raising, so imports never explode.
    """
    explicit = os.environ.get("IDA_REPO_ROOT")
    if explicit:
        return Path(explicit)
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "models.yaml").exists() and (candidate / "tasks").is_dir():
            return candidate
    return Path.cwd()


def normalize_database_url(database_url: str) -> str:
    """Force the psycopg3 driver onto a bare ``postgresql://`` DSN.

    ESO assembles ``DATABASE_URL`` from the Crossplane-provisioned parts and
    writes a bare ``postgresql://`` scheme.  SQLAlchemy 2.x maps that to
    **psycopg2**, which this image deliberately does not ship (the runtime pins
    ``psycopg[binary]`` so nothing ever has to compile libpq).

    ⚠ ONE HELPER, BOTH CALLERS.  The failure this prevents already happened once
    on this platform: the migration normalised the scheme and the app did not, so
    the schema migrated cleanly while the API could not connect at all.  Both
    :func:`ida_core.db.make_engine` and ``migrations/env.py`` route through here.
    """
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Settings(BaseSettings):
    """Runtime configuration for every Python service."""

    model_config = SettingsConfigDict(
        env_prefix="IDA_", env_file=".env", extra="ignore", case_sensitive=False
    )

    # ── platform-supplied (dual-aliased: IDA_ first, then the ConfigMap name) ──

    database_url: str = Field(
        "postgresql+psycopg://ida:ida@postgres:5432/ida",
        validation_alias=AliasChoices("IDA_DATABASE_URL", "DATABASE_URL"),
    )
    """SQLAlchemy URL.  Tests override with ``sqlite+pysqlite:///:memory:``."""

    redis_url: str = Field(
        "redis://redis:6379/0",
        validation_alias=AliasChoices("IDA_REDIS_URL", "REDIS_URL"),
    )

    log_level: str = Field("INFO", validation_alias=AliasChoices("IDA_LOG_LEVEL", "LOG_LEVEL"))

    s3_bucket: str = Field(
        "run-artifacts", validation_alias=AliasChoices("IDA_S3_BUCKET", "MINIO_BUCKET")
    )
    s3_access_key: str = Field(
        "", validation_alias=AliasChoices("IDA_S3_ACCESS_KEY", "MINIO_ACCESS_KEY")
    )
    s3_secret_key: str = Field(
        "", validation_alias=AliasChoices("IDA_S3_SECRET_KEY", "MINIO_SECRET_KEY")
    )

    host: str = Field("0.0.0.0", validation_alias=AliasChoices("IDA_HOST", "HOST"))  # noqa: S104
    """Bind address.  A loopback bind is invisible to kube-proxy AND to the
    kubelet's probes, so 0.0.0.0 inside a container is correct, not careless."""

    port: int = Field(8000, validation_alias=AliasChoices("IDA_PORT", "PORT"))
    """Each Deployment sets its own literal (api 8000, mock-model 8000)."""

    # ── the object store's split endpoint ──────────────────────────────────
    # The platform gives host/port/TLS as three ConfigMap keys, not one URL.
    # IDA_S3_ENDPOINT_URL still wins when set, so local dev and tests are
    # unchanged; otherwise the triple is composed.

    s3_endpoint_url_explicit: str = Field("", validation_alias=AliasChoices("IDA_S3_ENDPOINT_URL"))
    minio_endpoint: str = Field("", validation_alias=AliasChoices("MINIO_ENDPOINT"))
    minio_port: int = Field(9000, validation_alias=AliasChoices("MINIO_PORT"))
    minio_use_ssl: bool = Field(False, validation_alias=AliasChoices("MINIO_USE_SSL"))

    s3_region: str = "us-east-1"

    # ── app-internal (IDA_-only: no ConfigMap entry, correct default in-image) ──

    artifact_backend: str = "s3"
    """``s3`` (MinIO) or ``local``.  ``local`` uses :attr:`artifact_local_root`."""

    artifact_local_root: str = "/tmp/ida-artifacts"  # noqa: S108

    models_file: str = ""
    """Path to ``models.yaml``.  Empty -> ``repo_root()/models.yaml``."""

    tasks_dir: str = ""
    """Root of the task tree.  Empty -> ``repo_root()/tasks``."""

    runner_poll_timeout_s: int = 5
    """How long the runner blocks on the queue before re-checking for shutdown."""

    runner_metrics_port: int = 9100
    """The runner's /metrics listener.  9100 matches the container port the
    ServiceMonitor scrapes -- see services/runner/ida_runner/metrics.py."""

    auth_mode: str = "disabled"
    """``disabled`` today.

    **D-5: there is no auth service.**  Platform SSO/OIDC arrives later and the
    API consumes it through one dependency-injected placeholder
    (``ida_api.auth.current_principal``).  This flag is the seam.
    """

    # ── resolvers ──────────────────────────────────────────────────────────

    @property
    def s3_endpoint_url(self) -> str:
        """``IDA_S3_ENDPOINT_URL`` wins; else compose the platform's MINIO_* triple."""
        if self.s3_endpoint_url_explicit:
            return self.s3_endpoint_url_explicit
        if self.minio_endpoint:
            scheme = "https" if self.minio_use_ssl else "http"
            return f"{scheme}://{self.minio_endpoint}:{self.minio_port}"
        return "http://minio:9000"

    def sqlalchemy_url(self) -> str:
        """:attr:`database_url` with the driver forced -- for ``migrations/env.py``.

        ``env.py`` builds its engine through ``engine_from_config``, not through
        :func:`ida_core.db.make_engine`, so it needs the normalisation applied
        explicitly.  Same helper, so the two can never disagree.
        """
        return normalize_database_url(self.database_url)

    def resolved_models_file(self) -> Path:
        return Path(self.models_file) if self.models_file else repo_root() / "models.yaml"

    def resolved_tasks_dir(self) -> Path:
        return Path(self.tasks_dir) if self.tasks_dir else repo_root() / "tasks"


def get_settings() -> Settings:
    """Build settings from the environment.

    Not cached: tests monkeypatch env between cases, and building this object is
    cheap.  Services call it once at startup and hold the result.
    """
    return Settings()
