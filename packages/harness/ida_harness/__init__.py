"""``ida_harness`` -- the custom evaluation harness (**D-4**).

We wrote our own rather than adopting an eval framework.  We *studied* Inspect
AI's concepts -- the task / solver / scorer separation, structured eval logs,
sample-level caching -- and we import nothing from it.  The mapping:

======================  ==========================================
Inspect concept         Where it lives here
======================  ==========================================
Task                    :class:`ida_core.contracts.TaskSpec` (YAML-authored)
Solver                  :class:`ida_harness.solver.Solver` (one chat turn in the skeleton)
Scorer                  :mod:`ida_harness.scoring`
Eval log                :class:`ida_core.contracts.EvalLog`
Sample-level caching    :mod:`ida_harness.cache` (interface + no-op default)
======================  ==========================================

Entry point: :func:`ida_harness.runner.run_task`.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

# `__version__` is the DISTRIBUTION version, read from `packages/harness/pyproject.toml` -- NOT an answer
# to "which build is running?". See the full note in `ida_core/__init__.py`; the
# identifier that is right by construction is the git SHA
# (`ida_core.gitmeta.build_identity()`, `IDA_GIT_SHA`).
try:
    __version__ = _dist_version("ida-harness")
except PackageNotFoundError:  # pragma: no cover -- only outside an install
    __version__ = "0+unknown"

__all__ = ["__version__"]
