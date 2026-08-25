#!/usr/bin/env python3
"""Run the task/model schema gate straight from a checkout.

Thin shim. The implementation lives in `ida_harness.validate_impl` so that the
harness package stays standalone-installable -- it must work when someone
`pip install ida-harness` outside this repo, where this `tools/` directory does
not exist.

    python tools/validate_tasks.py            # from anywhere, no install needed
    ida-validate-tasks                        # the installed console script

⚠ The sibling source tree is put FIRST on sys.path, and any already-imported
`ida_harness` is dropped. Without that, a stale copy installed elsewhere on the
machine shadows the checkout you are actually editing, and this shim fails with
`No module named ida_harness.validate_impl` while the file is plainly there.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "packages" / "harness" / "src"
if (_SRC / "ida_harness" / "validate_impl.py").is_file():
    sys.path.insert(0, str(_SRC))
    for _name in [n for n in sys.modules if n == "ida_harness" or n.startswith("ida_harness.")]:
        del sys.modules[_name]

from ida_harness.validate_impl import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
