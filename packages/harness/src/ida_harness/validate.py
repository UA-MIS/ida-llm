"""Console-script entry point for the task/model schema gate.

The implementation lives in tools/validate_tasks.py so it can also be run
directly from a checkout with no install step (`python tools/validate_tasks.py`).
This wrapper is what `ida-validate-tasks` resolves to inside the container image,
where tools/ is not on the path.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    # Repo layout: packages/harness/src/ida_harness/validate.py -> repo root is 4 up.
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root / "tools"))
    from validate_tasks import main as validate_main  # noqa: PLC0415

    return validate_main(["--root", str(repo_root)])


if __name__ == "__main__":
    raise SystemExit(main())
