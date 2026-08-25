"""``ida_core`` -- the frozen contracts of Capstone-IDA.

Start at :mod:`ida_core.contracts`.  Everything else here is the machinery that
makes those contracts durable (:mod:`ida_core.db`), transportable
(:mod:`ida_core.queue`), archivable (:mod:`ida_core.artifacts`) and checkable
(:mod:`ida_core.validation`).

Nothing in this package talks to a model.  That is :mod:`ida_harness`.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
