"""FastAPI application.

⚠ /healthz AND /readyz ARE THE DEPLOYMENT CONTRACT -- do not collapse them.

  /healthz  liveness. Answers "this process is alive". It MUST NOT touch any
            dependency. A liveness probe that checks a dependency turns a brief
            outage in that dependency into a rolling restart of every replica,
            which is how a small outage becomes a large one.
  /readyz   readiness. Answers "this process can serve traffic", which DOES mean
            its dependencies are reachable. A failing readiness probe pulls one
            pod out of the Service and leaves it running -- the correct response.

⚠ /readyz REPORTS EACH DEPENDENCY SEPARATELY, and that is deliberate. An earlier
version returned one opaque string; when the Postgres driver was missing it said
`No module named 'psycopg2'` with no indication of WHICH check produced it, and
that turned a glance into a diagnosis. Every check now names itself, reports
ok/failed independently, and the others still run when one fails -- so a single
readout tells you the whole dependency picture rather than just the first thing
that broke.

Everything below the health and metrics endpoints is a starting point. Replace it.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import create_engine, text
from starlette.requests import Request

from ida_core.settings import get_settings

app = FastAPI(title="IDA-LLM API", version="0.1.0")

_settings = get_settings()
# Lazily created so the process can start (and answer /healthz) even when a
# dependency is unreachable -- which is exactly the state a fresh pod is in while
# ESO is still writing its Secrets.
_engine = None

REQUESTS = Counter(
    "ida_llm_http_requests_total",
    "HTTP requests handled by the api.",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "ida_llm_http_request_duration_seconds",
    "HTTP request duration handled by the api.",
    ["method", "path"],
)


def _get_engine():
    global _engine  # noqa: PLW0603
    if _engine is None:
        # sqlalchemy_url(), NOT require_database_url() -- see that helper's docstring.
        _engine = create_engine(_settings.sqlalchemy_url(), pool_pre_ping=True)
    return _engine


@app.middleware("http")
async def _record_metrics(request: Request, call_next):
    # `route.path` (the TEMPLATE, e.g. /api/runs/{id}) rather than the raw URL --
    # labelling by raw path would mint a new time series per id and blow up
    # Prometheus cardinality. Unmatched paths collapse to a single bucket for the
    # same reason: a 404 scan must not be able to create series.
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", None) or "<unmatched>"
    REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness. Deliberately dependency-free -- see the module docstring."""
    return {"status": "ok"}


def _check_database() -> tuple[bool, str]:
    try:
        with _get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 -- any failure means "not ready"
        return False, f"{type(exc).__name__}: {exc}"[:200]
    return True, "ok"


def _check_redis() -> tuple[bool, str]:
    try:
        import redis  # noqa: PLC0415 -- optional at import time, required here

        redis.Redis.from_url(_settings.redis_url, socket_timeout=3).ping()
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:200]
    return True, "ok"


def _check_object_store() -> tuple[bool, str]:
    try:
        import httpx  # noqa: PLC0415

        scheme = "https" if _settings.minio_use_ssl else "http"
        url = f"{scheme}://{_settings.minio_endpoint}:{_settings.minio_port}/minio/health/ready"
        status = httpx.get(url, timeout=3).status_code
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:200]
    if status != 200:
        return False, f"HTTP {status}"
    return True, "ok"


@app.get("/readyz")
def readyz(response: Response) -> dict[str, Any]:
    """Readiness, reported PER DEPENDENCY.

    Every check runs even when an earlier one fails -- the point is to hand back
    the whole picture in one readout, not the first thing that broke.
    """
    checks = {
        "database": _check_database(),
        "redis": _check_redis(),
        "object_store": _check_object_store(),
    }
    detail = {name: {"ok": ok, "detail": message} for name, (ok, message) in checks.items()}
    failed = sorted(name for name, (ok, _) in checks.items() if not ok)

    if failed:
        response.status_code = 503
        return {"status": "not-ready", "failed": failed, "checks": detail}
    return {"status": "ready", "checks": detail}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus exposition. Scraped by the ServiceMonitor in the chart.

    Served on the app port rather than a separate one: this endpoint has no
    Ingress rule, so it is reachable only from inside the namespace (and from the
    `monitoring` namespace, which the tenant netpol explicitly allows).
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/runs")
def list_runs() -> dict[str, list]:
    """STUB. Returns an empty list so the frontend has a shape to code against."""
    return {"runs": []}
