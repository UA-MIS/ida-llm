#!/usr/bin/env python3
"""Print the THIRD-PARTY dependencies declared by this repo's distributions.

Why this exists: `Dockerfile.python` wants to install the dependencies BEFORE it
copies the source, so that editing a `.py` file does not invalidate the layer
that downloads thirteen wheels. `pip install ./packages/core` cannot do that --
it needs the package to exist on disk, which means the source has to be there
first, which is exactly the ordering that defeats the cache.

So the manifests are copied on their own, this reads the dependency lists out of
them, and pip installs those. The source arrives afterwards and its packages are
installed with `--no-deps`, because their dependencies are already present.

The local distributions are excluded by name: `ida-core` depending on
`ida-harness` is an internal edge, not something to fetch from an index.

READ, NOT HARDCODED. A hardcoded list is a list that drifts from the manifests
the moment somebody adds a dependency, and the drift shows up as a runtime
ImportError in a deployed container. `Dockerfile.python` runs `pip check` after
installing, so a dependency this misses fails the BUILD instead.
"""

from __future__ import annotations

import glob
import sys
import tomllib


def dist_name(spec: str) -> str:
    """The bare distribution name from a PEP 508 requirement string."""
    head = spec.split(";", 1)[0].strip()
    for sep in ("[", ">", "<", "=", "~", "!", " "):
        head = head.split(sep, 1)[0]
    return head.strip().lower().replace("_", "-")


def main() -> int:
    manifests = sorted(
        glob.glob("packages/*/pyproject.toml") + glob.glob("services/*/pyproject.toml")
    )
    if not manifests:
        print("no pyproject.toml found -- wrong working directory?", file=sys.stderr)
        return 1

    local: set[str] = set()
    for path in manifests:
        with open(path, "rb") as fh:
            local.add(dist_name(tomllib.load(fh)["project"]["name"]))

    external: set[str] = set()
    for path in manifests:
        with open(path, "rb") as fh:
            project = tomllib.load(fh)["project"]
        for spec in project.get("dependencies", []):
            if dist_name(spec) not in local:
                external.add(spec.strip())

    if not external:
        print("no third-party dependencies found -- that cannot be right", file=sys.stderr)
        return 1

    for spec in sorted(external):
        print(spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
