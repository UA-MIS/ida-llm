"""pytest bootstrap for the tracer bullet.

The shared assertions live in `_tracer_assertions.py`, not here -- see that
file's header for why a module named `conftest` cannot be imported by name when
CI runs a single root `pytest`.

All this file does is make `_tracer_assertions` importable regardless of the
directory pytest was invoked from. `--import-mode=importlib` (root pyproject)
deliberately puts nothing on sys.path, so without this line the e2e suite passes
from `cd e2e` and fails from the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
