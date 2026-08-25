"""Harness error taxonomy.

Two axes matter to callers: **is it worth retrying**, and **whose fault is it**.

* :class:`TransientModelError`   -- retry (429, 5xx, timeout, connection reset)
* :class:`PermanentModelError`   -- do not retry (4xx other than 429, bad JSON)
* :class:`TaskLoadError`         -- our authored content is wrong
* :class:`ScoringError`          -- the completion could not be scored

The retry loop in :mod:`ida_harness.client` branches on exactly this split, so
adding a status code to the wrong bucket changes production behaviour --
``tests/test_client.py`` pins the classification.
"""

from __future__ import annotations


class HarnessError(Exception):
    """Base class for everything this package raises deliberately."""


class ModelError(HarnessError):
    """A call to a model endpoint failed."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TransientModelError(ModelError):
    """Retryable: rate limit, server error, timeout, connection failure."""


class PermanentModelError(ModelError):
    """Not retryable: auth failure, bad request, unparseable response body."""


class TaskLoadError(HarnessError):
    """A task YAML file is missing, unparseable, or fails validation."""


class ScoringError(HarnessError):
    """A scorer could not produce a verdict.

    Reserved for *misconfiguration*, not for bad model output: a completion
    containing no number scores 0.0 with an explanation (see
    :mod:`ida_harness.scoring` rule 1).  This is raised when the task itself is
    incoherent -- a ``numeric_match`` target with no number in it, a missing
    target, an unregistered scorer kind.

    The runner catches it per sample, so one broken task sample degrades that
    sample rather than discarding every already-paid-for sibling completion.
    """
