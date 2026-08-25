"""The settings half of the platform's runtime contract.

The cluster hands this app its configuration under names our own `IDA_` prefix
does not cover, and every one of these failures is SILENT: a field quietly keeps
its default, the pod reports Ready, and it serves against the wrong database, the
wrong bucket, or no object store at all. That is why each of these is pinned by a
test rather than left to a code comment.

Ground truth for the names: `.devops/chart/base/configmap.yaml` (ConfigMap keys)
and the `secretKeyRef`s on each workload in `.devops/chart/base/deployments.yaml`.
"""

from __future__ import annotations

import pytest

from ida_core.config import Settings, normalize_database_url
from ida_core.db import make_engine


class TestUnprefixedPlatformNames:
    """`envFrom: configMapRef` writes DATABASE_URL, not IDA_DATABASE_URL."""

    @pytest.mark.parametrize(
        ("env_name", "attribute", "value"),
        [
            ("DATABASE_URL", "database_url", "postgresql://u:p@db:5432/x"),
            ("REDIS_URL", "redis_url", "redis://ida-llm-redis:6379/0"),
            ("LOG_LEVEL", "log_level", "debug"),
            ("MINIO_BUCKET", "s3_bucket", "run-artifacts"),
            ("MINIO_ACCESS_KEY", "s3_access_key", "platform-access"),
            ("MINIO_SECRET_KEY", "s3_secret_key", "platform-secret"),
            ("HOST", "host", "127.0.0.1"),
        ],
    )
    def test_the_platform_name_is_read(
        self, monkeypatch, env_name: str, attribute: str, value: str
    ) -> None:
        monkeypatch.setenv(env_name, value)
        assert getattr(Settings(_env_file=None), attribute) == value

    def test_port_is_read_from_the_platform_name(self, monkeypatch) -> None:
        monkeypatch.setenv("PORT", "8000")
        assert Settings(_env_file=None).port == 8000

    def test_the_ida_prefixed_name_still_wins(self, monkeypatch) -> None:
        """Precedence is not cosmetic.

        docker-compose, .env and the test suite all set IDA_-prefixed names, and
        a developer with a stray DATABASE_URL exported in their shell must not
        have it silently override the stack they just brought up.
        """
        monkeypatch.setenv("IDA_DATABASE_URL", "sqlite+pysqlite:///ours.db")
        monkeypatch.setenv("DATABASE_URL", "postgresql://theirs/x")
        assert Settings(_env_file=None).database_url == "sqlite+pysqlite:///ours.db"

    def test_app_internal_settings_stay_ida_only(self, monkeypatch) -> None:
        """These have NO ConfigMap entry, so an unprefixed name must not bind.

        If `AUTH_MODE` ever started working here it would look harmless -- right
        up until some unrelated component in the same namespace exported one.
        """
        monkeypatch.setenv("AUTH_MODE", "token")
        assert Settings(_env_file=None).auth_mode == "disabled"

        monkeypatch.setenv("IDA_AUTH_MODE", "token")
        assert Settings(_env_file=None).auth_mode == "token"


class TestObjectStoreEndpoint:
    """The platform supplies host/port/TLS as three keys, not one URL."""

    def test_composed_from_the_minio_triple(self, monkeypatch) -> None:
        monkeypatch.setenv("MINIO_ENDPOINT", "ida-llm-object-store")
        monkeypatch.setenv("MINIO_PORT", "9000")
        settings = Settings(_env_file=None)
        assert settings.s3_endpoint_url == "http://ida-llm-object-store:9000"

    def test_tls_flag_selects_the_scheme(self, monkeypatch) -> None:
        monkeypatch.setenv("MINIO_ENDPOINT", "objects.example")
        monkeypatch.setenv("MINIO_PORT", "443")
        monkeypatch.setenv("MINIO_USE_SSL", "true")
        assert Settings(_env_file=None).s3_endpoint_url == "https://objects.example:443"

    def test_explicit_url_wins_over_the_triple(self, monkeypatch) -> None:
        monkeypatch.setenv("IDA_S3_ENDPOINT_URL", "http://localhost:9000")
        monkeypatch.setenv("MINIO_ENDPOINT", "ida-llm-object-store")
        assert Settings(_env_file=None).s3_endpoint_url == "http://localhost:9000"

    def test_falls_back_to_the_compose_hostname(self) -> None:
        assert Settings(_env_file=None).s3_endpoint_url == "http://minio:9000"


class TestDsnNormalisation:
    """ESO writes a BARE `postgresql://` DSN.

    SQLAlchemy 2.x maps that scheme to psycopg2, which this image deliberately
    does not ship -- it pins `psycopg[binary]` so nothing ever compiles libpq.

    ⚠ This already went wrong once on this platform, in the worst possible shape:
    the migration normalised the scheme and the app did not, so the schema
    migrated cleanly while the API could not connect at all. ONE helper, BOTH
    callers -- that is what these tests hold in place.
    """

    def test_bare_scheme_gets_the_psycopg_driver(self) -> None:
        assert (
            normalize_database_url("postgresql://ida:pw@host:5432/db")
            == "postgresql+psycopg://ida:pw@host:5432/db"
        )

    def test_an_explicit_driver_is_left_alone(self) -> None:
        url = "postgresql+psycopg://ida:pw@host:5432/db"
        assert normalize_database_url(url) == url

    def test_only_the_scheme_is_rewritten(self) -> None:
        """A password or database name containing the scheme text must survive."""
        url = "postgresql://ida:postgresql://@host:5432/db"
        assert normalize_database_url(url) == (
            "postgresql+psycopg://ida:postgresql://@host:5432/db"
        )

    def test_other_dialects_are_untouched(self) -> None:
        for url in ("sqlite+pysqlite:///:memory:", "mysql://h/d"):
            assert normalize_database_url(url) == url

    def test_the_app_path_normalises(self) -> None:
        """`make_engine` is the single funnel for engine creation."""
        engine = make_engine("postgresql://ida:pw@host:5432/db")
        assert engine.url.drivername == "postgresql+psycopg"

    def test_the_migration_path_normalises(self, monkeypatch) -> None:
        """`migrations/env.py` builds its engine through `engine_from_config`,
        not `make_engine`, so it calls this helper explicitly."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://ida:pw@host:5432/db")
        settings = Settings(_env_file=None)
        assert settings.sqlalchemy_url() == "postgresql+psycopg://ida:pw@host:5432/db"

    def test_both_paths_agree(self, monkeypatch) -> None:
        """The actual invariant -- not that either is right, but that they match."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://ida:pw@host:5432/db")
        settings = Settings(_env_file=None)
        assert (
            make_engine(settings.database_url).url.render_as_string(hide_password=False)
            == settings.sqlalchemy_url()
        )
