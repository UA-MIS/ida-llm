"""In-process transport for driving the mock model without a socket.

Why this exists: the harness client is **synchronous**, so ``httpx.ASGITransport``
(async-only) cannot be used to reach an ASGI app from it. This module provides a
synchronous :class:`httpx.BaseTransport` that dispatches into the real
mock-model app, so tests and the in-process tracer bullet exercise the genuine
service code -- routing, validation, response shaping and all -- with no port,
no container and no flakiness.

This is a *test transport*, not a test double: the code answering the request is
exactly the code that answers it in docker-compose and in the cluster.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ida_mock_model.app import create_app

_HOP_BY_HOP = {"content-length", "transfer-encoding", "connection"}


class InProcessTransport(httpx.BaseTransport):
    """Synchronous transport that routes requests into an ASGI app.

    Only the URL *path* and query are used; the host is ignored, so a client
    configured with ``http://mock-model:8000/v1`` reaches the in-process app
    without any DNS or port being involved.
    """

    def __init__(self, app: FastAPI) -> None:
        self._client = TestClient(app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        upstream = self._client.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.read(),
            headers={k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP},
        )
        return httpx.Response(
            status_code=upstream.status_code,
            content=upstream.content,
            headers={k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP},
            request=request,
        )

    def close(self) -> None:
        """No-op, deliberately.

        ``httpx.Client.close()`` closes its transport, and one transport is
        commonly shared by several short-lived clients (the harness builds one
        client per run). Closing the underlying ASGI test client here would make
        the second run fail. There are no sockets to release, so there is
        nothing to close -- use :meth:`shutdown` if you really want to tear the
        app down.
        """

    def shutdown(self) -> None:
        """Release the underlying test client. Rarely needed."""
        self._client.close()


def make_transport(app: FastAPI | None = None) -> InProcessTransport:
    """Build a transport over ``app``, or over a fresh mock-model app."""
    return InProcessTransport(app or create_app())
