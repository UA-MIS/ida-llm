"""FastAPI application.

⚠ /healthz AND /readyz ARE THE DEPLOYMENT CONTRACT -- do not collapse them.

  /healthz  liveness. Answers "this process is alive". It MUST NOT touch the
            database. A liveness probe that checks a dependency turns a brief DB
            blip into a rolling restart of every replica, which is how a small
            outage becomes a large one.
  /readyz   readiness. Answers "this process can serve traffic", which DOES mean
            the database is reachable. A failing readiness probe pulls one pod out
            of the Service and leaves it running, which is the correct response.

Everything below the health endpoints is a starting point. Replace it.
"""

from __future__ import annotations

from fastapi import FastAPI, Response
from sqlalchemy import create_engine, text

from ida_core.settings import get_settings

app = FastAPI(title="IDA-LLM API", version="0.1.0")

_settings = get_settings()
# Lazily created so the process can start (and answer /healthz) even when the
# database is not yet reachable -- which is exactly the state a fresh pod is in
# while ESO is still writing the DATABASE_URL Secret.
_engine = None


def _get_engine():
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = create_engine(_settings.require_database_url(), pool_pre_ping=True)
    return _engine


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness. Deliberately dependency-free -- see the module docstring."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> dict[str, str]:
    """Readiness. Reports NOT ready until the database actually answers."""
    try:
        with _get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 -- any failure means "not ready"
        response.status_code = 503
        return {"status": "not-ready", "detail": str(exc)[:200]}
    return {"status": "ready"}


@app.get("/api/runs")
def list_runs() -> dict[str, list]:
    """STUB. Returns an empty list so the frontend has a shape to code against."""
    return {"runs": []}
