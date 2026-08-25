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

from pathlib import Path

import pytest
from pydantic import ValidationError

from ida_core.config import Settings, normalize_database_url
from ida_core.db import make_engine

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestUnprefixedPlatformNames:
    """`envFrom: configMapRef` writes DATABASE_URL, not IDA_DATABASE_URL."""

    @pytest.mark.parametrize(
        ("env_name", "attribute", "value"),
        [
            ("DATABASE_URL", "database_url", "postgresql://u:p@db:5432/x"),
            ("REDIS_URL", "redis_url", "redis://ida-llm-redis:6379/0"),
            # An already-canonical value, because this row tests NAME BINDING.
            # Case normalisation has its own class below -- and the earlier
            # version of this row asserted `debug` -> `debug`, which is precisely
            # the bug that crash-looped the first deploy. A test can encode the
            # defect it was meant to catch; this one did.
            ("LOG_LEVEL", "log_level", "WARNING"),
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


class TestLogLevelCase:
    """The platform writes LOWER CASE; `logging` accepts only UPPER CASE.

    ⚠ This crash-looped every api and runner pod on the first deploy of the port:
    `ValueError: Unknown level: 'info'`, raised at IMPORT time -- before any
    logging existed to report it, so the only evidence was a CrashLoopBackOff and
    a stack trace six frames deep in the stdlib.

    Nothing local or in CI caught it. Our default was already `"INFO"`, and every
    test that set the value invented an upper-case one. THAT is the lesson worth
    keeping: the fixture has to be the string the platform actually writes.
    Ground truth here is `.devops/chart/base/configmap.yaml` (`LOG_LEVEL: info`)
    and `.env.example`, which documents "one of: debug, info, warning, error".
    """

    def test_the_configmaps_actual_value_is_usable_by_logging(self, monkeypatch) -> None:
        """THE regression test. `info` is the literal value in the ConfigMap."""
        import logging

        monkeypatch.setenv("LOG_LEVEL", "info")
        level = Settings(_env_file=None).log_level
        assert level == "INFO"
        logging.getLogger("probe").setLevel(level)  # would raise on 'info'

    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [
            # every value .env.example documents, verbatim
            ("debug", "DEBUG"),
            ("info", "INFO"),
            ("warning", "WARNING"),
            ("error", "ERROR"),
            # already upper, and mixed, and padded
            ("INFO", "INFO"),
            ("Warning", "WARNING"),
            ("  info  ", "INFO"),
        ],
    )
    def test_case_and_whitespace_are_normalised(
        self, monkeypatch, supplied: str, expected: str
    ) -> None:
        monkeypatch.setenv("LOG_LEVEL", supplied)
        assert Settings(_env_file=None).log_level == expected

    def test_every_accepted_level_is_one_logging_accepts(self, monkeypatch) -> None:
        """Guards the allow-list itself against drifting from the stdlib."""
        import logging

        for name in ("critical", "fatal", "error", "warn", "warning", "info", "debug"):
            monkeypatch.setenv("LOG_LEVEL", name)
            logging.getLogger("probe").setLevel(Settings(_env_file=None).log_level)

    def test_a_nonsense_level_is_refused_where_it_enters(self, monkeypatch) -> None:
        """`basicConfig` would raise anyway; the value of failing here is the
        message. A typo in a ConfigMap should not be diagnosed from a stdlib
        traceback."""
        monkeypatch.setenv("LOG_LEVEL", "verbose")
        with pytest.raises(ValidationError, match="not a logging level"):
            Settings(_env_file=None)

    def test_the_ida_prefixed_name_is_normalised_too(self, monkeypatch) -> None:
        monkeypatch.setenv("IDA_LOG_LEVEL", "debug")
        assert Settings(_env_file=None).log_level == "DEBUG"


class TestTheRealConfigMapIsUsable:
    """Drive the ACTUAL chart ConfigMap through Settings.

    Every platform-contract bug this port hit -- unprefixed names, the bare
    `postgresql://` DSN, `MOCK_MODEL_BASE_URL` being an origin, `LOG_LEVEL: info`
    -- had the same shape: a value the cluster really writes, that nothing local
    ever fed to the code, discovered in a CrashLoopBackOff.

    Individually testing each one only ever closes the case somebody already
    found the hard way. This closes the CLASS: it reads
    `.devops/chart/base/configmap.yaml` -- the file the platform actually
    applies -- and asserts the app can be configured from it. Add a key there
    that this code cannot consume and the failure arrives here, in a unit test,
    instead of in a rollout.

    Read-only, and the coupling is deliberate: that file IS the contract.
    """

    @staticmethod
    def _configmap_data() -> dict[str, str]:
        import yaml

        path = REPO_ROOT / ".devops" / "chart" / "base" / "configmap.yaml"
        assert path.is_file(), f"the deploy contract moved: {path}"
        document = yaml.safe_load(path.read_text())
        assert document["kind"] == "ConfigMap", document.get("kind")
        return {str(k): str(v) for k, v in document["data"].items()}

    def test_settings_builds_from_it(self, monkeypatch) -> None:
        for key, value in self._configmap_data().items():
            monkeypatch.setenv(key, value)
        # The one value the ConfigMap does NOT carry: it is a Secret, injected
        # by ESO from Vault. Everything else here is the real thing.
        monkeypatch.setenv("DATABASE_URL", "postgresql://ida:pw@ida-llm-db:5432/ida")

        settings = Settings(_env_file=None)

        assert settings.sqlalchemy_url().startswith("postgresql+psycopg://")
        assert settings.s3_endpoint_url == "http://ida-llm-object-store:9000"
        assert settings.s3_bucket == "run-artifacts"
        assert settings.redis_url.startswith("redis://")
        assert settings.host == "0.0.0.0"  # noqa: S104 - the ConfigMap's own value

    def test_its_log_level_is_one_logging_accepts(self, monkeypatch) -> None:
        """The exact failure: `LOG_LEVEL: info` raised at import, before any
        logging existed to report it."""
        import logging

        data = self._configmap_data()
        assert "LOG_LEVEL" in data, "the ConfigMap stopped setting LOG_LEVEL"
        monkeypatch.setenv("LOG_LEVEL", data["LOG_LEVEL"])
        logging.getLogger("probe").setLevel(Settings(_env_file=None).log_level)

    def test_its_mock_url_resolves_to_a_callable_openai_base(self, monkeypatch) -> None:
        """Base carries prod's value (empty). The dev/preview overlays patch it to
        `http://ida-llm-mock-model` -- an ORIGIN -- so both must resolve to a base
        the harness can actually append `/chat/completions` to."""
        from ida_core.registry import load_registry, resolve_base_url

        entry = load_registry(REPO_ROOT / "models.yaml").get("mock")

        # prod/staging: empty -> falls back to the committed literal
        assert resolve_base_url(entry, env={"MOCK_MODEL_BASE_URL": ""}).endswith("/v1")
        # dev/preview: the overlay's origin -> gains /v1
        assert (
            resolve_base_url(entry, env={"MOCK_MODEL_BASE_URL": "http://ida-llm-mock-model"})
            == "http://ida-llm-mock-model/v1"
        )

    def test_every_key_it_sets_is_either_consumed_or_known_to_be_someone_elses(self) -> None:
        """A key the ConfigMap sets that nothing reads is either dead config or a
        setting somebody thinks is live and is not. Both are worth knowing about,
        so new keys must be classified here deliberately."""
        consumed = {
            "LOG_LEVEL", "HOST", "PORT", "REDIS_URL",
            "MINIO_ENDPOINT", "MINIO_PORT", "MINIO_USE_SSL", "MINIO_BUCKET",
            "MOCK_MODEL_BASE_URL",
        }
        not_ours = {
            "API_URL",          # the frontend reads this, server-side (Node, not Python)
            "SPARKS_BASE_URL",  # read via models.yaml's base_url_env, not Settings
        }
        unclassified = set(self._configmap_data()) - consumed - not_ours
        assert not unclassified, (
            f"the ConfigMap gained key(s) {sorted(unclassified)}; consume them or "
            "classify them here"
        )
