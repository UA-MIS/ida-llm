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

__version__ = "0.1.0"

__all__ = ["__version__"]
