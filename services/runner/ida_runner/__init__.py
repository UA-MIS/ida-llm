"""``ida_runner`` -- the queue worker.

Per **D-5** the runner shares the Python image with the API and differs only by
entrypoint.  It is also where the LLM judge will live when it lands: a judge is
a harness code path invoked by this worker, **not** a separate service.

Loop: ``BLPOP`` a :class:`~ida_core.contracts.RunJobMessage` -> claim the run ->
:func:`ida_harness.runner.run_task` -> persist results + rollup -> repeat.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

# `__version__` is the DISTRIBUTION version, read from `services/runner/pyproject.toml` -- NOT an answer
# to "which build is running?". See the full note in `ida_core/__init__.py`; the
# identifier that is right by construction is the git SHA
# (`ida_core.gitmeta.build_identity()`, `IDA_GIT_SHA`).
try:
    __version__ = _dist_version("ida-runner")
except PackageNotFoundError:  # pragma: no cover -- only outside an install
    __version__ = "0+unknown"

__all__ = ["__version__"]
