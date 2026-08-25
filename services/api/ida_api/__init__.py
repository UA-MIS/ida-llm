"""``ida_api`` -- the FastAPI service.

Responsibilities, and deliberately nothing else:

* serve the **model registry** (parsed ``models.yaml``) and the **task catalog**
* **enqueue** runs (mint ids, insert ``queued`` rows, push queue messages)
* **read** runs and results for the UI

It never calls a model.  It never scores anything.  That is the runner's job,
and keeping the split sharp is what lets the runner scale independently (D-5).
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

# `__version__` is the DISTRIBUTION version, read from `services/api/pyproject.toml` -- NOT an answer
# to "which build is running?". See the full note in `ida_core/__init__.py`; the
# identifier that is right by construction is the git SHA
# (`ida_core.gitmeta.build_identity()`, `IDA_GIT_SHA`).
try:
    __version__ = _dist_version("ida-api")
except PackageNotFoundError:  # pragma: no cover -- only outside an install
    __version__ = "0+unknown"

__all__ = ["__version__"]
