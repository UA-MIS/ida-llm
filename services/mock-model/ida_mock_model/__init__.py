"""``ida_mock_model`` -- a deterministic OpenAI-compatible endpoint.

It exists so that the entire pipeline (api -> queue -> runner -> harness ->
Postgres -> MinIO -> UI) can be exercised end-to-end with **no** API key, **no**
GPU and **no** network egress -- in CI, on a laptop, and in the dev cluster.

It is deterministic on purpose: given the same prompt it returns the same
answer, so a tracer-bullet assertion on a score is a real assertion and not a
flake.  See :mod:`ida_mock_model.responder` for the answering rules.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

# `__version__` is the DISTRIBUTION version, read from
# `services/mock-model/pyproject.toml` -- NOT an answer to "which build is
# running?". This service deliberately depends on nothing from the platform (see
# the module docstring), so it cannot reuse `ida_core/__init__.py`'s note; the
# short version is that a pyproject version is a number a human types at release
# time and every branch between two releases shares it. `/healthz` reports the
# baked-in git SHA instead, which is right by construction.
try:
    __version__ = _dist_version("ida-mock-model")
except PackageNotFoundError:  # pragma: no cover -- only outside an install
    __version__ = "0+unknown"

__all__ = ["__version__"]
