"""Write (or check) ``docs/admin-api.openapi.json``: the admin API contract.

    python -m ida_api.admin.dump_openapi           # regenerate the file
    python -m ida_api.admin.dump_openapi --check   # exit 1 if it is stale

The frontend builds against this file (``frontend/src/lib/admin/types.ts`` and
``admin-contract.test.ts``), so it is committed, and ``test_admin_contract``
fails when it disagrees with :mod:`ida_api.admin.schemas`.

Built from a bare app holding ONLY the admin router: no settings, database,
queue or task tree is needed to describe the contract, and nothing outside
``/admin`` can leak into it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi import FastAPI

from ida_core.config import repo_root

OUTPUT = Path("docs") / "admin-api.openapi.json"


def build_spec() -> dict:
    from ida_api.admin import admin_router

    app = FastAPI(
        title="IDA-LLM admin API",
        version="1",
        description=(
            "Everything under /admin. Called only by the frontend's BFF with an "
            "admin bearer token and X-IDA-Actor; see ida_api.admin."
        ),
    )
    app.include_router(admin_router, prefix="/admin")
    spec = app.openapi()
    spec["paths"] = {p: v for p, v in spec["paths"].items() if p.startswith("/admin/")}
    return spec


def render() -> str:
    return json.dumps(build_spec(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args(argv)
    path = repo_root() / OUTPUT
    rendered = render()
    if args.check:
        if not path.exists() or path.read_text() != rendered:
            print(f"{OUTPUT} is stale; run: python -m ida_api.admin.dump_openapi", file=sys.stderr)
            return 1
        return 0
    path.write_text(rendered)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
