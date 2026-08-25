"""Console-script entry point for the task/model schema gate.

The implementation is in `validate_impl` -- inside this package, so the harness
stays standalone-installable and its schema gate does not depend on a `tools/`
directory being importable. `tools/validate_tasks.py` is a thin shim over the
same code, for running straight from a checkout with no install step.
"""

from __future__ import annotations

from ida_harness.validate_impl import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
