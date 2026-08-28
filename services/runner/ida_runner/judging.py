"""Turning ``IDA_JUDGE_MODEL_KEY`` into a judge, for both paths that need one.

Two callers, one policy: :func:`ida_runner.main.build_worker` builds the judge
that grades during a normal run, and :func:`ida_runner.sweeps.run_judge_calibration`
builds the one that grades retroactively.  They must agree about what "no judge
configured" means and about what a *bad* configuration does, because a
deployment where live grading is on and nightly grading is off (or vice versa)
produces a results table whose blanks mean two different things with nothing to
tell them apart.

THE TWO ANSWERS, AND WHY THEY DIFFER
------------------------------------
* **No key set** -> ``None``, quietly.  Judging is off by default and that
  default is a decision (see ``Settings.judge_model_key``): a judge is a second
  model call per criterion per sample, so it starts costing money when an
  operator asks for it, never because a feature merged.  Subjective samples stay
  archived and honestly unscored, which is exactly the pre-existing behaviour.
* **A key set but unusable** -> raise.  An unknown key, a disabled entry, a
  missing API key: these are an operator who asked for grading and did not get
  it.  Degrading to ``None`` would be the expensive kind of helpful -- the
  runner would come up healthy, grade nothing, and write blanks that are
  indistinguishable from "no judge configured", so the misconfiguration would be
  invisible until someone asked why a month of subjective runs is empty.
  Failing at startup costs one crash-looping pod with the reason in its logs.

That asymmetry is the whole content of this module, which is why it is a module
and not four lines inlined twice.
"""

from __future__ import annotations

import logging

from ida_core.config import Settings
from ida_core.contracts import ModelRegistry
from ida_harness.judge import LLMJudge, build_judge

log = logging.getLogger(__name__)


def build_judge_from_settings(settings: Settings, registry: ModelRegistry) -> LLMJudge | None:
    """The configured judge, or ``None`` when none is configured.

    Raises :class:`~ida_harness.errors.JudgeConfigurationError` (unknown key,
    disabled entry) or :class:`~ida_core.registry.MissingApiKeyError` (the entry
    names an env var that is unset) when a key IS set and cannot be honoured --
    see the module docstring for why that is not softened to ``None``.

    The caller owns the returned judge and must close it, or -- as both callers
    here do -- keep it for the process's lifetime.
    """
    key = settings.judge_model_key
    if not key:
        log.info(
            "no judge configured (IDA_JUDGE_MODEL_KEY is unset); subjective samples "
            "will be archived unscored and can be graded later by the judge-calibration "
            "sweep or `python -m ida_harness.regrade`"
        )
        return None

    judge = build_judge(registry, key)
    log.info("judge configured: %s", key)
    return judge
