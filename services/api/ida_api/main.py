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
