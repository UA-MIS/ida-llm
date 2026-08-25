"""Shared settings.  One class, read by api, runner and the tracer bullet.

Everything is env-driven (12-factor) because in-cluster the values arrive as
env vars projected from Vault by the platform.  Nothing here has a secret as a
*default*; secrets default to empty and the service fails loudly if it needs one.

Env prefix: ``IDA_``.  So ``database_url`` <- ``IDA_DATABASE_URL``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    """Best-effort monorepo root.

    Resolution order: ``IDA_REPO_ROOT`` env (set explicitly in containers) ->
    walk up from this file looking for ``models.yaml``.  Returns the cwd as a
    last resort rather than raising, so imports never explode.
    """
    import os

    explicit = os.environ.get("IDA_REPO_ROOT")
    if explicit:
        return Path(explicit)
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "models.yaml").exists() and (candidate / "tasks").is_dir():
            return candidate
    return Path.cwd()


class Settings(BaseSettings):
    """Runtime configuration for every Python service."""

    model_config = SettingsConfigDict(
        env_prefix="IDA_", env_file=".env", extra="ignore", case_sensitive=False
    )

    database_url: str = "postgresql+psycopg://ida:ida@postgres:5432/ida"
    """SQLAlchemy URL.  Tests override with ``sqlite+pysqlite:///:memory:``."""

    redis_url: str = "redis://redis:6379/0"

    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "ida-artifacts"
    s3_region: str = "us-east-1"

    artifact_backend: str = "s3"
    """``s3`` (MinIO) or ``local``.  ``local`` uses :attr:`artifact_local_root`."""

    artifact_local_root: str = "/tmp/ida-artifacts"

    models_file: str = ""
    """Path to ``models.yaml``.  Empty -> ``repo_root()/models.yaml``."""

    tasks_dir: str = ""
    """Root of the task tree.  Empty -> ``repo_root()/tasks``."""

    runner_poll_timeout_s: int = 5
    """How long the runner blocks on the queue before re-checking for shutdown."""

    log_level: str = "INFO"

    auth_mode: str = "disabled"
    """``disabled`` in the skeleton.

    **D-5: there is no auth service.**  Platform SSO/OIDC arrives later and the
    API consumes it through one dependency-injected placeholder
    (``ida_api.auth.current_principal``).  This flag is the seam.
    """

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
