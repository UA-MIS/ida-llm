"""``ida_core`` -- the frozen contracts of Capstone-IDA.

Start at :mod:`ida_core.contracts`.  Everything else here is the machinery that
makes those contracts durable (:mod:`ida_core.db`), transportable
(:mod:`ida_core.queue`), archivable (:mod:`ida_core.artifacts`) and checkable
(:mod:`ida_core.validation`).

Nothing in this package talks to a model.  That is :mod:`ida_harness`.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

# ── `__version__` IS THE DISTRIBUTION VERSION. IT IS NOT WHAT IS DEPLOYED. ────
#
# It is read from the installed distribution metadata -- i.e. from the `version`
# field of `packages/core/pyproject.toml` -- rather than being typed out a second
# time here. Five packages in this repo each carried their own hand-written
# `__version__ = "0.1.0"`, so "bump the version" meant editing ten places and
# nobody ever did: the 0.1.1 image still introduced itself as 0.1.0, and
# `ida_harness.__version__` was recorded as the provenance of every benchmark row
# in the database. A constant that only one of its two copies ever updates is not
# a version; deriving it means there is exactly one copy to update.
#
# ⚠ DO NOT USE THIS TO ANSWER "WHICH BUILD IS RUNNING?". A pyproject version is a
# number a human types when cutting a release; it says nothing about the commit,
# and every branch between two releases shares it. The identifier that IS right by
# construction is the git SHA baked into the image at build time -- see
# `ida_core.gitmeta.build_identity()` (persisted as `runs.harness_version`) and
# `IDA_GIT_SHA` / `IDA_VERSION` in `Dockerfile.python`. Health endpoints and
# provenance fields use those. This constant exists for packaging.
#
# `0+unknown` (a valid PEP 440 local version, and unmistakably not a release) is
# the answer when the distribution is not installed -- running from a bare
# checkout with only PYTHONPATH set. Honest absence, never a placeholder that
# looks real.
try:
    __version__ = _dist_version("ida-core")
except PackageNotFoundError:  # pragma: no cover -- only outside an install
    __version__ = "0+unknown"

__all__ = ["__version__"]
