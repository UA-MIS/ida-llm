"""Harness error taxonomy.

Two axes matter to callers: **is it worth retrying**, and **whose fault is it**.

* :class:`TransientModelError`   -- retry (429, 5xx, timeout, connection reset)
* :class:`PermanentModelError`   -- do not retry (4xx other than 429, bad JSON)
* :class:`TaskLoadError`         -- our authored content is wrong
* :class:`ScoringError`          -- the completion could not be scored
* :class:`JudgeConfigurationError` -- the judge is mis-set-up; nothing was asked
* :class:`JudgeResponseError`    -- the judge answered, unusably

The retry loop in :mod:`ida_harness.client` branches on exactly this split, so
adding a status code to the wrong bucket changes production behaviour --
``tests/test_client.py`` pins the classification.
"""

from __future__ import annotations


class HarnessError(Exception):
    """Base class for everything this package raises deliberately."""


class ModelError(HarnessError):
    """A call to a model endpoint failed."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_s = retry_after_s
        """Seconds the provider asked us to wait, parsed from ``Retry-After``.

        ``None`` when the header was absent or not expressed in seconds.  The
        retry loop in :mod:`ida_harness.client` uses it as a FLOOR on the next
        delay -- a provider that says "wait 30s" is telling us something our
        exponential backoff cannot know.
        """


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


class JudgeError(HarnessError):
    """Base for the LLM-as-judge failures.  See :mod:`ida_harness.judge`."""


class JudgeConfigurationError(JudgeError):
    """The judge cannot be *asked* -- a setup problem, before any money is spent.

    Unknown or disabled judge model key, a rubric with no criteria, a degenerate
    rubric scale.  Distinct from :class:`JudgeResponseError` because the remedy
    is different: this is fixed in ``models.yaml`` or a task file, not by
    re-running.
    """


class JudgeResponseError(JudgeError):
    """The judge answered, and the answer cannot be read as a grade.

    Malformed JSON, no ``score`` key, a non-numeric score, a score outside the
    rubric's scale.  **Never recovered by guessing.**  The sample degrades to
    ``score=None`` with this text as its error; clamping an out-of-range score or
    regexing a number out of prose would record a grade nobody made.
    """
