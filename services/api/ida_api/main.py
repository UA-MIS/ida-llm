"""Uvicorn entrypoint: ``uvicorn ida_api.main:app``.

Kept separate from :mod:`ida_api.app` so that importing the app factory in a
test never triggers the production composition root (which would try to reach
Postgres and Redis at import time).
"""

from __future__ import annotations

import logging

from ida_api.app import create_app
from ida_core.config import get_settings

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = create_app()


def main() -> int:
    """Console entrypoint: the chart runs `command: ["ida-api"]`.

    Reads HOST and PORT from settings, which dual-alias the platform's unprefixed
    ConfigMap keys. Binding 0.0.0.0 inside a container is correct, not careless:
    a loopback bind is invisible to kube-proxy AND to the kubelet's probes.
    """
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=None)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
