"""The ONE place environment configuration is read.

Every value here has a matching entry in `.env.example` and, for the cluster, in
`.devops/chart/base/configmap.yaml` (non-secret) or the env overlay's
ExternalSecret (secret). If you add a setting, add it in all three or it will work
locally and be missing in the cluster.

⚠ NOTHING HERE HAS A SECRET DEFAULT. `database_url` and the provider API keys
default to None and the app fails LOUDLY when a code path needs one. That is
deliberate: a default that silently works is how a pod boots, reports Ready, and
serves wrong results (the env-injection race -- a pod that starts before ESO
writes its Secret keeps the unresolved env for the life of the container).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- process ---
    log_level: str = "info"
    host: str = "0.0.0.0"  # noqa: S104 -- a loopback bind is invisible to kubelet probes
    port: int = 8000

    # --- datastores ---
    # postgresql://... assembled by ESO from the Crossplane-provisioned parts.
    database_url: str | None = None
    redis_url: str = "redis://ida-llm-redis:6379/0"

    # --- object store (per-tenant MinIO) ---
    minio_endpoint: str = "ida-llm-object-store"
    minio_port: int = 9000
    minio_use_ssl: bool = False
    minio_bucket: str = "run-artifacts"
    minio_access_key: str | None = None
    minio_secret_key: str | None = None

    # --- model providers ---
    # MOCK_MODEL_BASE_URL is populated in dev, CI and PR previews and points at
    # the in-repo stub, so no pull request can burn credits or touch campus
    # hardware. Unset in staging/prod, where real providers are used.
    mock_model_base_url: str | None = None
    mock_model_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    # Campus vLLM ("Sparks"). Wired but intentionally unset -- the cluster egress
    # policy does not open a route to it yet (deferred by owner decision; see
    # .devops/README.md). Selecting the `sparks-local` model with this unset
    # fails fast instead of hanging on a dropped connection.
    sparks_base_url: str | None = None
    sparks_api_key: str | None = None

    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. In the cluster it is materialized by ESO from "
                "Vault (tenants/ida-llm/<env>/database); locally, copy .env.example to .env."
            )
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
