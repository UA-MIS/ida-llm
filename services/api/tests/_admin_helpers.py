"""Shared fixtures for the admin API tests: a db-mode app, seeded from the real
YAML, with an admin token and a KEK.

Not a conftest, for the reason ``_dashboard_helpers`` gives."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from ida_api.app import create_app
from ida_api.deps import AppContext
from ida_core.artifacts import LocalArtifactStore
from ida_core.config import Settings
from ida_core.db import create_all, make_engine, make_session_factory
from ida_core.queue import InMemoryQueue
from ida_harness.config_provider import build_provider

ADMIN_TOKEN = "admin-token-not-a-real-secret-01"  # noqa: S105 - fixture
KEK = "k1:" + base64.urlsafe_b64encode(b"admin-test-kek-0123456789abcdef!").decode()
ACTOR = "octo-prof"
HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}", "X-IDA-Actor": ACTOR}


def _database_url(tmp_path) -> str:
    """SQLite by default. Set ``IDA_ADMIN_TEST_PG_URL`` (a Postgres server URL,
    e.g. ``postgresql://ida:pw@127.0.0.1:55432/ida``) to run the admin suite
    against a FRESH Postgres database per test instead -- SQLite does not
    enforce foreign keys, and the unit invariants are FK-backed on Postgres."""
    import os
    import uuid

    server = os.environ.get("IDA_ADMIN_TEST_PG_URL")
    if not server:
        return f"sqlite+pysqlite:///{tmp_path / 'admin.db'}"
    import psycopg

    name = f"admin_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(server, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    return server.rsplit("/", 1)[0] + f"/{name}"


def admin_settings(tmp_path, **overrides) -> Settings:
    values = {
        "database_url": _database_url(tmp_path),
        "artifact_backend": "local",
        "artifact_local_root": str(tmp_path / "artifacts"),
        "config_source": "db",
        "admin_tokens": f"admin-console:{ADMIN_TOKEN}",
        "credentials_kek": KEK,
    }
    values.update(overrides)
    return Settings(**values)


def admin_context(tmp_path, **overrides) -> AppContext:
    settings = admin_settings(tmp_path, **overrides)
    engine = make_engine(settings.database_url)
    create_all(engine)
    factory = make_session_factory(engine)
    store = LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    store.ensure_bucket()
    return AppContext(
        settings=settings,
        session_factory=factory,
        queue=InMemoryQueue(),
        artifact_store=store,
        config=build_provider(settings, factory),
    )


def admin_client(context: AppContext) -> TestClient:
    return TestClient(create_app(context))


def if_match(version: int) -> dict[str, str]:
    return {**HEADERS, "If-Match": f'"{version}"'}
