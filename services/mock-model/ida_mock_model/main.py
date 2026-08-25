"""Console entrypoint: ``ida-mock-model``.

The chart's `ida-llm-mock-model` Deployment runs `command: ["ida-mock-model"]`
against the SHARED ida-llm-python-app image, so this script has to exist there --
which is why services/mock-model is installed into Dockerfile.python alongside
the api and runner, and why docker-compose runs the same command rather than a
bare `uvicorn` invocation. Local dev and the cluster exercise one entry point.

HOST and PORT come from the environment: the ConfigMap sets ``HOST: "0.0.0.0"``
and the Deployment sets ``PORT: "8000"``.
"""

from __future__ import annotations

import os

from ida_mock_model.app import app


def main() -> int:
    """Serve until killed. Returns a process exit code."""
    import uvicorn

    # Read straight from the environment rather than through ida_core.Settings:
    # this distribution deliberately does not depend on ida-core (it is the
    # stub every other component is tested against, and a dependency edge from
    # it back into the platform's settings would make that circular).
    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104 - see below
    # 0.0.0.0 in a container is correct, not careless: a loopback bind is
    # invisible to kube-proxy AND to the kubelet's probes.
    port = int(os.environ.get("PORT", "8000"))

    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
