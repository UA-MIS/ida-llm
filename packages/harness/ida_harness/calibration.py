"""Calibration slices: is OUR harness measuring what the FIELD measures?

The question this answers
------------------------
Run a small slice of a public benchmark through this harness, against a model
whose score on that benchmark has been **published by somebody else**, and
compare the two numbers.  If they agree, our plumbing -- prompt assembly,
sampling params, normalisation, scorer, aggregation -- is not skewing results.
If they disagree by more than the slice's stated tolerance, something between
the task YAML and :func:`~ida_harness.runner.run_task` is bending the number,
and every score this platform publishes is suspect until it is found.

It is a **sanity check on the measuring instrument**, not a benchmark result.
Nothing here produces a number worth citing about a model.

⚠ THIS IS NOT JUDGE CALIBRATION.  ``ida_runner.sweeps.run_judge_calibration``
(and ``docs/llm-judge.md``) calibrate the LLM *judge*: they ask whether a judge
model's grades agree with a human's on subjective tasks.  This module never
involves a judge, never grades anything subjective, and asks an unrelated
question -- whether the harness that carries a *verifiable* task from YAML to a
score reproduces a number the outside world already knows.  The two share a word
and nothing else.  Do not wire one into the other.

What "honestly" means here, concretely
--------------------------------------
Four rules, each of which exists because the obvious shortcut produces a
confident false statement:

1. **A run with errors never reports "calibrated".**  A partial mean computed
   over the samples that happened to survive can land anywhere, including
   plausibly close to the published number.  ``error_count > 0`` sets the
   verdict to :data:`VERDICT_ERRORS` and forces
   :attr:`CalibrationOutcome.within_tolerance` to ``False``, whatever the
   arithmetic says.  An :class:`~ida_core.contracts.EvalLog` whose status is
   ``failed`` contributes **no** measured score at all -- never ``0.0``, because
   "we measured zero" and "we measured nothing" are different claims and only
   one of them is about the model.
2. **Aggregation is weighted by SCORED SAMPLES, not by task.**  A reference
   spanning a 7-sample task and a 5-sample task is one 12-sample measurement, and
   the mean is the sum of the individual scores over the number of samples that
   actually produced one.  Averaging the two task means would silently give each
   sample of the smaller task 1.4x the weight of a sample in the larger one --
   a different statistic from the one the benchmark published.  Samples that
   errored or were unscorable are excluded from the mean and counted separately,
   exactly as :attr:`EvalLog.mean_score` does within one task.
3. **The comparison is never nudged.**  ``delta = measured - published``,
   ``within_tolerance`` is ``abs(delta) <= tolerance``, and neither is rounded
   or clamped before that test.  Rounding is a presentation concern and happens
   only in :meth:`CalibrationReport.table`.
4. **A published number with no citation is not evidence.**  Every reference
   must carry a non-empty ``published_source`` URL and a ``published_retrieved``
   date, or it fails validation.  A reference whose source is still a
   ``TODO-PLACEHOLDER`` loads (so a slice can be drafted and dry-run) but is
   **refused at run time** unless ``allow_placeholder=True``, and a placeholder
   outcome can never be ``within_tolerance``.

And one category error worth naming: comparing a number published for model A
against a run of model B is not a weak measurement, it is a measurement of
nothing.  :func:`run_calibration` refuses it unless ``allow_model_mismatch=True``
is passed -- which exists for the real case where ``models.yaml`` names an entry
``luna`` and the benchmark names the same underlying model something else -- and
every outcome produced that way carries :attr:`CalibrationOutcome.cross_model`
so the table says ``CROSS-MODEL`` in the reader's face.

Dataset hygiene
---------------
Slice files under ``calibration/`` reference task ids that already live in
``tasks/``.  **No benchmark item text is ever copied into this repository** --
see ``tasks/SCHEMA.md`` -> "Dataset hygiene".  A slice is a list of ids, a
published number, and a citation; if you find yourself pasting GSM8K questions
into a YAML file, stop.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ida_core.artifacts import ArtifactStore
from ida_core.contracts import EvalLog, ModelEntry, RunStatus
from ida_core.ids import new_run_id
from ida_harness.client import ModelClient
from ida_harness.errors import HarnessError
from ida_harness.runner import run_task
from ida_harness.tasks import TaskCatalog

log = logging.getLogger(__name__)

PLACEHOLDER_MARKER = "TODO-PLACEHOLDER"
"""The repo-wide marker for a value that is authored but not yet real.

Spelled the same way ``models.yaml`` spells it, deliberately: one token to grep
for when asking "what in this repository is still a stub?".
"""

_PLACEHOLDER_RE = re.compile(re.escape(PLACEHOLDER_MARKER))


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class CalibrationSliceError(HarnessError):
    """A calibration slice file is missing, unparseable, or fails validation.

    The mirror of :class:`~ida_harness.errors.TaskLoadError` for the other kind
    of authored file this module reads.  Defined here rather than in
    ``errors.py`` because it is raised by exactly one module.
    """


class CalibrationRefusal(HarnessError):
    """The comparison asked for would not mean anything, so it was not made.

    Raised *before* any model is called, so a refusal costs nothing.  The two
    causes are a model-key mismatch (a published number for A vs a run of B) and
    a reference whose citation is still a ``TODO-PLACEHOLDER``.  Both have an
    explicit opt-in; neither has a silent one.
    """


# --------------------------------------------------------------------------
# The authored file: calibration/<name>.yaml
# --------------------------------------------------------------------------


class CalibrationReference(BaseModel):
    """One published number, and the local tasks we will compare against it.

    Every field except ``description`` and ``tolerance`` is load-bearing for the
    claim "our harness agrees with the field": drop the citation and there is no
    claim, drop ``model_key`` and there is no telling whose score it was.
    """

    benchmark: Annotated[str, Field(min_length=1)]
    """The public benchmark this number comes from, e.g. ``gsm8k``, ``mmlu``."""

    slice_id: Annotated[str, Field(min_length=1)]
    """Names THIS slice within the benchmark.  Unique inside a slice file.

    A slice is not the whole benchmark -- it is the handful of local tasks we can
    afford to run -- so the id has to say which handful, or two runs of
    "gsm8k" would be incomparable while looking identical.
    """

    description: str = ""

    model_key: Annotated[str, Field(min_length=1)]
    """The ``models.yaml`` key this published number is claimed for.

    Checked against the entry actually being run.  See ``allow_model_mismatch``
    on :func:`run_calibration` for the one legitimate reason they differ.
    """

    published_score: Annotated[float, Field(ge=0.0, le=1.0)]
    """The score the source reports, normalised to 0..1.

    A benchmark quoted as "82.4%" is authored here as ``0.824``.  Converting at
    authoring time rather than at comparison time keeps one representation in
    play: :attr:`CalibrationOutcome.delta` is then in the same units as the
    scores this harness produces, which are all 0..1.
    """

    published_source: Annotated[str, Field(min_length=1)]
    """A URL where the number can be checked by somebody who does not trust us.

    Required.  A published number with no citation is not evidence -- it is a
    number somebody remembered.  A ``TODO-PLACEHOLDER`` value is accepted by the
    parser so a slice can be drafted and dry-run, and refused by
    :func:`run_calibration`; anything else must be an ``http(s)`` URL.
    """

    published_retrieved: date
    """When the number was read off that source.

    Required, and required *separately* from the URL: leaderboards are edited in
    place, so a URL alone does not say which version of the page was read.  A
    delta that appears next year is then attributable to a moved goalpost rather
    than blamed on the harness.
    """

    tolerance: Annotated[float, Field(ge=0.0, le=1.0)] = 0.05
    """How far ``measured`` may sit from ``published`` and still agree.

    Authored per reference, not global: the honest tolerance for a 12-sample
    slice of a 1319-item benchmark is wide (sampling error alone is several
    points) and pretending otherwise would make every run fail or every run pass
    depending on which way the number was fudged.  Choose it from the slice's
    size and state the reasoning in ``description``.

    ⚠ The comparison is made on raw IEEE-754 floats, deliberately: nothing is
    rounded or nudged before the verdict (module docstring, rule 3).  A tolerance
    a measurement sits EXACTLY on can therefore fall either way by one ULP --
    ``0.75 - 0.80`` is ``-0.050000000000000044``, not ``-0.05``.  That is a
    reason to choose a tolerance you are not balanced on, not a reason to add an
    epsilon here: an epsilon is a rounding rule that flips verdicts, which is the
    thing this module refuses to do.
    """

    task_ids: Annotated[list[str], Field(min_length=1)]
    """Ids of tasks that ALREADY EXIST under ``tasks/``.

    Ids, never content: benchmark items are not copied into this repository
    (``tasks/SCHEMA.md`` -> "Dataset hygiene").  Every id is resolved against the
    catalog before anything runs, so a typo is a startup failure rather than a
    short measurement nobody notices.
    """

    @field_validator("published_source")
    @classmethod
    def _citation_is_checkable(cls, value: str) -> str:
        """A citation has to be something a stranger can open."""
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "published_source is required: a published number with no citation is not evidence"
            )
        if _PLACEHOLDER_RE.search(stripped):
            return stripped
        if not stripped.startswith(("http://", "https://")):
            raise ValueError(
                f"published_source must be a URL (or a {PLACEHOLDER_MARKER}(...) marker "
                f"while the slice is still a draft); got {stripped!r}"
            )
        return stripped

    @field_validator("task_ids")
    @classmethod
    def _task_ids_are_unique(cls, value: list[str]) -> list[str]:
        """A repeated id would weight that task's samples twice over."""
        if len(set(value)) != len(value):
            duplicates = sorted({i for i in value if value.count(i) > 1})
            raise ValueError(f"task_ids contains duplicates: {duplicates}")
        return value

    @property
    def is_placeholder(self) -> bool:
        """True while the citation is still a ``TODO-PLACEHOLDER`` marker."""
        return bool(_PLACEHOLDER_RE.search(self.published_source))

    @property
    def label(self) -> str:
        """``benchmark/slice_id`` -- how a reference is named in output."""
        return f"{self.benchmark}/{self.slice_id}"


class CalibrationSlice(BaseModel):
    """One authored file under ``calibration/``: a versioned set of references."""

    version: Literal[1] = 1
    description: str = ""
    references: Annotated[list[CalibrationReference], Field(min_length=1)]

    @model_validator(mode="after")
    def _labels_unique(self) -> CalibrationSlice:
        """Two references with the same label are indistinguishable in a report."""
        labels = [r.label for r in self.references]
        if len(set(labels)) != len(labels):
            duplicates = sorted({label for label in labels if labels.count(label) > 1})
            raise ValueError(f"duplicate benchmark/slice_id: {duplicates}")
        return self

    @property
    def placeholder_labels(self) -> list[str]:
        """Labels of references whose citation is still a draft marker."""
        return [r.label for r in self.references if r.is_placeholder]


def load_calibration_slice(path: Path | str) -> CalibrationSlice:
    """Load and validate one slice file.

    Raises :class:`CalibrationSliceError` for anything wrong with the file:
    missing, unparseable YAML, not a mapping, or a semantic rule (no citation,
    no retrieval date, empty ``task_ids``).  One error type, because the caller's
    remedy is the same in every case -- fix the file -- and a run must never
    proceed on a slice we are guessing at.
    """
    from ida_core.validation import load_yaml

    path = Path(path)
    if not path.is_file():
        raise CalibrationSliceError(f"calibration slice not found: {path}")
    try:
        document = load_yaml(path)
    except Exception as exc:
        raise CalibrationSliceError(f"{path}: could not parse YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise CalibrationSliceError(
            f"{path}: top level must be a mapping, got {type(document).__name__}"
        )
    try:
        return CalibrationSlice.model_validate(document)
    except Exception as exc:
        raise CalibrationSliceError(f"{path}: {exc}") from exc


# --------------------------------------------------------------------------
# The result
# --------------------------------------------------------------------------


VERDICT_WITHIN = "within_tolerance"
"""Measured and published agree to within the reference's tolerance."""

VERDICT_OUTSIDE = "outside_tolerance"
"""Both numbers exist and they disagree.  The interesting failure."""

VERDICT_ERRORS = "errors_in_run"
"""Something was measured, but not all of it -- so none of it is reportable.

Distinct from ``outside_tolerance`` on purpose: one says the harness disagrees
with the field, the other says we do not know whether it does.  Collapsing them
would turn a plumbing outage into a false claim about the harness.
"""

VERDICT_NO_MEASUREMENT = "no_measurement"
"""Nothing scored: every sample errored, or nothing in the slice was scorable."""

VERDICT_PLACEHOLDER = "placeholder"
"""The reference's citation is still a ``TODO-PLACEHOLDER``.

Whatever ran, it was not compared against a published number, because there is
no published number here yet.
"""


class CalibrationOutcome(BaseModel):
    """The comparison for ONE reference.  Never rounded before the verdict."""

    benchmark: str
    slice_id: str
    reference_model_key: str
    """The key the published number was claimed for."""

    model_key: str
    """The key we actually ran.  Equal to the above unless ``cross_model``."""

    cross_model: bool = False
    """True when the two keys differ and the caller allowed it anyway.

    Never silently set: :func:`run_calibration` raises unless
    ``allow_model_mismatch=True``.  Printed as ``CROSS-MODEL`` because a reader
    skimming a table of deltas has to be stopped, not footnoted.
    """

    measured_score: float | None
    """Mean over SCORED samples across the reference's tasks, or ``None``.

    ``None`` -- not ``0.0`` -- when nothing scored.  See rule 1 in the module
    docstring: a zero is a claim about the model, an absence is a claim about the
    run.
    """

    published_score: float
    tolerance: float

    delta: float | None
    """``measured - published``.  ``None`` when there is no measurement.

    Signed, so the direction is readable: positive means our harness scores the
    model HIGHER than the field does, which usually means we are being generous
    somewhere (a lenient normalisation, a scorer tolerance set too wide).
    """

    within_tolerance: bool
    """``abs(delta) <= tolerance`` **and** nothing disqualified the measurement.

    The extra conjunct is the whole point.  A run with errors, a run that scored
    nothing, or a reference with no real citation can all produce arithmetic that
    happens to land inside the tolerance, and none of them is evidence that this
    harness measures what the field measures.  ``cross_model`` is deliberately
    NOT a disqualifier -- see :attr:`cross_model`; it is a labelling problem, not
    a measurement problem, and forcing it to fail would make the escape hatch
    useless for the case it exists for.
    """

    verdict: str
    """One of the ``VERDICT_*`` constants above, most severe first."""

    explanation: str = ""
    """Prose a reader can act on, including the arithmetic when it was overruled."""

    sample_count: int = 0
    scored_count: int = 0
    """Samples that produced a score.  The denominator of :attr:`measured_score`."""

    error_count: int = 0
    total_cost_usd: float = 0.0
    run_ids: list[str] = Field(default_factory=list)
    """One run id per task in the reference, so the evidence is retrievable."""

    task_statuses: dict[str, str] = Field(default_factory=dict)
    """``task_id -> RunStatus`` for every task in the reference."""

    @property
    def label(self) -> str:
        return f"{self.benchmark}/{self.slice_id}"


class CalibrationPlanItem(BaseModel):
    """What a ``--dry-run`` would have executed.  No measurement, no claim."""

    benchmark: str
    slice_id: str
    reference_model_key: str
    model_key: str
    cross_model: bool
    is_placeholder: bool
    task_ids: list[str]
    sample_count: int

    @property
    def label(self) -> str:
        return f"{self.benchmark}/{self.slice_id}"


class CalibrationReport(BaseModel):
    """Every outcome in a slice, plus the aggregate an operator reads.

    A dry run carries :attr:`planned` and **no** outcomes: "here is what would
    run" and "here is what was measured" must not be the same list, or a preview
    would be indistinguishable from a result.  Same reasoning as
    ``RegradeReport.dry_run`` and ``SweepReport.planned``.
    """

    model_key: str
    slice_path: str | None = None
    outcomes: list[CalibrationOutcome] = Field(default_factory=list)
    planned: list[CalibrationPlanItem] = Field(default_factory=list)
    dry_run: bool = False
    notes: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True only when every reference was measured and agreed.

        An empty outcome list is **not** ok: a calibration that compared nothing
        must not read as a calibration that passed.  A dry run is not ok either
        -- it measured nothing by design -- which is why :attr:`exit_code`, not
        this property, is what the CLI returns.
        """
        return bool(self.outcomes) and all(o.within_tolerance for o in self.outcomes)

    @property
    def exit_code(self) -> int:
        """0 when the run said something true and good, non-zero otherwise.

        A dry run exits 0 on a slice that parses and whose task ids all resolve:
        it did what it was asked to do.  It prints ``DRY RUN`` on every line so
        the 0 cannot be mistaken for a passing calibration.
        """
        if self.dry_run:
            return 0
        return 0 if self.ok else 1

    @property
    def total_sample_count(self) -> int:
        return sum(o.sample_count for o in self.outcomes)

    @property
    def total_scored_count(self) -> int:
        return sum(o.scored_count for o in self.outcomes)

    @property
    def total_error_count(self) -> int:
        return sum(o.error_count for o in self.outcomes)

    @property
    def total_cost_usd(self) -> float:
        return sum(o.total_cost_usd for o in self.outcomes)

    @property
    def worst_abs_delta(self) -> float | None:
        """Largest ``|delta|`` over outcomes that HAVE one.

        Deliberately skips unmeasured outcomes rather than treating them as a
        delta of zero, which would let a slice where nothing ran report the best
        agreement in the file.
        """
        deltas = [abs(o.delta) for o in self.outcomes if o.delta is not None]
        return max(deltas) if deltas else None

    def summary(self) -> str:
        """The one line a CI log keeps."""
        if self.dry_run:
            return (
                f"model={self.model_key} DRY RUN -- planned {len(self.planned)} reference(s), "
                f"{sum(p.sample_count for p in self.planned)} sample(s); nothing was measured"
            )
        agreed = sum(1 for o in self.outcomes if o.within_tolerance)
        worst = self.worst_abs_delta
        worst_text = "n/a" if worst is None else f"{worst:.4f}"
        return (
            f"model={self.model_key} references={len(self.outcomes)} agreed={agreed} "
            f"samples={self.total_sample_count} scored={self.total_scored_count} "
            f"errors={self.total_error_count} worst_abs_delta={worst_text} "
            f"cost=${self.total_cost_usd:.6f} ok={self.ok}"
        )

    def table(self) -> str:
        """A fixed-width table.  **The only place anything is rounded.**

        Verdicts are computed on unrounded floats (module docstring, rule 3);
        display rounding here can therefore never flip one, which is why it is
        confined to this method.
        """
        if self.dry_run:
            header = f"{'REFERENCE':<34} {'MODEL':<14} {'TASKS':>5} {'SAMPLES':>7}  NOTE"
            lines = [header, "-" * len(header)]
            for item in self.planned:
                notes = []
                if item.cross_model:
                    notes.append(f"CROSS-MODEL (published for {item.reference_model_key!r})")
                if item.is_placeholder:
                    notes.append(f"{PLACEHOLDER_MARKER} citation -- no number to compare against")
                lines.append(
                    f"{item.label:<34} {item.model_key:<14} {len(item.task_ids):>5} "
                    f"{item.sample_count:>7}  {'; '.join(notes) or 'would run'}"
                )
            return "\n".join(lines)

        header = (
            f"{'REFERENCE':<34} {'PUBLISHED':>9} {'MEASURED':>9} {'DELTA':>8} "
            f"{'TOL':>6} {'SCORED':>7} {'ERR':>4}  VERDICT"
        )
        lines = [header, "-" * len(header)]
        for outcome in self.outcomes:
            measured = (
                "     --  " if outcome.measured_score is None else f"{outcome.measured_score:>9.4f}"
            )
            delta = "      --" if outcome.delta is None else f"{outcome.delta:>+8.4f}"
            verdict = outcome.verdict.upper()
            if outcome.cross_model:
                verdict = f"{verdict} [CROSS-MODEL]"
            lines.append(
                f"{outcome.label:<34} {outcome.published_score:>9.4f} {measured} {delta} "
                f"{outcome.tolerance:>6.3f} "
                f"{outcome.scored_count:>3}/{outcome.sample_count:<3} {outcome.error_count:>4}  "
                f"{verdict}"
            )
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Running one
# --------------------------------------------------------------------------


RunTaskFn = Callable[..., EvalLog]


def _resolve_tasks(catalog: TaskCatalog, reference: CalibrationReference) -> list:
    """Every task the reference names, or a hard error naming the missing id.

    Resolved for the WHOLE slice before anything executes, so a typo costs
    nothing instead of surfacing three references and two provider invoices in.
    """
    specs = []
    for task_id in reference.task_ids:
        try:
            specs.append(catalog.get(task_id))
        except KeyError as exc:
            raise CalibrationSliceError(
                f"{reference.label}: {exc}. Calibration slices reference tasks that "
                "already exist under tasks/ -- benchmark items are never copied into "
                "this repository (tasks/SCHEMA.md -> Dataset hygiene)."
            ) from None
    return specs


def _mismatch_refusal(reference: CalibrationReference, entry: ModelEntry) -> str:
    """Why a published-A-vs-measured-B comparison would mean nothing."""
    return (
        f"{reference.label}: this number is published for model "
        f"{reference.model_key!r}, but the run would use {entry.key!r}. Comparing "
        "them measures nothing about either model. Pass allow_model_mismatch=True "
        "(--allow-model-mismatch) only when the two keys genuinely name the same "
        "underlying model under different names."
    )


def _placeholder_refusal(reference: CalibrationReference) -> str:
    """Why a citation that does not exist yet cannot be compared against."""
    return (
        f"{reference.label}: published_source is still a {PLACEHOLDER_MARKER} "
        f"({reference.published_source!r}), so there is no published number to "
        "calibrate against. Fill in a real citation, or pass allow_placeholder=True "
        "(--allow-placeholder) to measure the slice anyway -- that run reports "
        f"verdict={VERDICT_PLACEHOLDER!r} and can never be within tolerance."
    )


def _aggregate(logs: Sequence[EvalLog]) -> tuple[float | None, int, int, int, float]:
    """Fold N eval logs into ``(mean, samples, scored, errors, cost)``.

    **Weighted by scored samples, never by task.**  The mean is the sum of the
    individual sample scores divided by the number of samples that produced one,
    so a 7-sample task and a 5-sample task contribute 7 and 5 votes rather than
    one each.  Averaging the per-task means instead would give each sample of the
    smaller task 1.4x the weight -- a different statistic from the one every
    published benchmark number reports.

    A log whose status is ``failed`` contributes **nothing** to the numerator or
    the denominator: it measured nothing, and folding it in as a run of zeros
    would state that the model got those items wrong.  Its samples and errors are
    still counted, so the caller can see how much of the slice is missing.
    """
    score_total = 0.0
    scored = 0
    samples = 0
    errors = 0
    cost = 0.0
    for eval_log in logs:
        samples += len(eval_log.results)
        errors += eval_log.error_count
        cost += sum(r.cost_usd for r in eval_log.results)
        if eval_log.status is RunStatus.FAILED:
            continue
        for record in eval_log.results:
            if record.score is None:
                continue
            score_total += record.score.value
            scored += 1
    mean = score_total / scored if scored else None
    return mean, samples, scored, errors, cost


def _decide(
    *,
    reference: CalibrationReference,
    measured: float | None,
    error_count: int,
    scored_count: int,
    cross_model: bool,
    is_placeholder: bool,
) -> tuple[str, bool, str]:
    """``(verdict, within_tolerance, explanation)`` -- the whole judgement, once.

    Written as one function so the disqualification rules cannot drift between
    the value the report carries and the sentence the operator reads.  Severity
    order: placeholder > no measurement > errors > the arithmetic.
    """
    delta = None if measured is None else measured - reference.published_score
    arithmetic_ok = delta is not None and abs(delta) <= reference.tolerance
    arithmetic_text = (
        "no measurement, so no delta"
        if delta is None
        else (
            f"delta {delta:+.4f} vs tolerance {reference.tolerance:.4f} "
            f"({'inside' if arithmetic_ok else 'outside'})"
        )
    )
    prefix = ""
    if cross_model:
        prefix = (
            f"CROSS-MODEL: published for {reference.model_key!r}, measured on a "
            "different registry key. "
        )

    if is_placeholder:
        return (
            VERDICT_PLACEHOLDER,
            False,
            f"{prefix}published_source is still a {PLACEHOLDER_MARKER}, so this was "
            f"compared against a number nobody published. {arithmetic_text}, and that "
            "arithmetic means nothing.",
        )
    if measured is None:
        return (
            VERDICT_NO_MEASUREMENT,
            False,
            f"{prefix}nothing scored ({scored_count} scored sample(s), {error_count} "
            "error(s)): the slice measured nothing, which is not the same as measuring "
            "zero.",
        )
    if error_count:
        return (
            VERDICT_ERRORS,
            False,
            f"{prefix}{error_count} sample(s) errored, so the mean covers only the "
            f"{scored_count} that survived and is not comparable to a published number "
            f"over the full slice. For the record: {arithmetic_text}.",
        )
    verdict = VERDICT_WITHIN if arithmetic_ok else VERDICT_OUTSIDE
    return verdict, arithmetic_ok, f"{prefix}{arithmetic_text}."


def run_calibration(
    *,
    slice_: CalibrationSlice,
    catalog: TaskCatalog,
    entry: ModelEntry,
    api_key: str | None = None,
    client: ModelClient | None = None,
    client_factory: Callable[[], ModelClient] | None = None,
    artifact_store: ArtifactStore | None = None,
    run_id_factory: Callable[[], str] = new_run_id,
    task_git_sha: str | None = None,
    sweep_id: str | None = None,
    allow_model_mismatch: bool = False,
    allow_placeholder: bool = False,
    dry_run: bool = False,
    slice_path: Path | str | None = None,
    run_task_fn: RunTaskFn | None = None,
) -> CalibrationReport:
    """Measure every reference in ``slice_`` against ``entry`` and compare.

    One :func:`~ida_harness.runner.run_task` call per (reference, task).  The
    harness is used exactly as a normal benchmark run uses it -- same solver,
    same scorer, same aggregation -- because a calibration that took a shortcut
    would be calibrating a code path nobody else runs.

    Every refusal happens **before** the first model call: task ids are resolved,
    model keys are checked and placeholder citations are caught up front, so a
    bad slice costs nothing.

    Parameters
    ----------
    client / client_factory:
        As :func:`~ida_harness.runner.run_task`.  A ``client`` passed here is
        reused across every task and is **not** closed -- the caller owns it.
    run_id_factory:
        Injected so tests get deterministic ids.  Defaults to
        :func:`~ida_core.ids.new_run_id`.
    allow_model_mismatch:
        Permit ``reference.model_key != entry.key``.  For the real case where
        ``models.yaml`` calls an entry ``luna`` and the benchmark calls the same
        underlying model something else.  Every outcome is then flagged
        :attr:`CalibrationOutcome.cross_model` and printed ``CROSS-MODEL``.
    allow_placeholder:
        Measure a reference whose citation is still a draft.  Useful exactly
        once -- to learn the number you are about to write down -- and the
        outcome can never be ``within_tolerance``.
    dry_run:
        Resolve and validate everything, call nothing.  Returns a report with
        :attr:`CalibrationReport.planned` and no outcomes.  Refusals become
        :attr:`CalibrationReport.notes` rather than exceptions, so one pass
        reports every problem in a slice; an unresolvable task id is still fatal,
        because there is then nothing to preview.
    run_task_fn:
        Seam for tests.  ``None`` -- the default -- resolves to
        :func:`~ida_harness.runner.run_task` at CALL time rather than at import
        time, so a test may also reach it by patching this module's ``run_task``
        attribute (which is what the CLI tests do: :func:`main` never passes
        this parameter).  Production never passes it either.
    """
    execute: RunTaskFn = run_task_fn if run_task_fn is not None else run_task
    report = CalibrationReport(
        model_key=entry.key,
        slice_path=str(slice_path) if slice_path is not None else None,
        dry_run=dry_run,
    )

    # Resolve EVERYTHING, and refuse EVERYTHING refusable, before the first call:
    # a slice that is going to be rejected must be rejected before it spends a
    # cent of the first reference's budget.
    #
    # A DRY RUN REPORTS THE REFUSALS INSTEAD OF RAISING ON THE FIRST ONE. Its job
    # is to tell an author everything wrong with a slice in one pass; raising
    # would hide the second problem behind the first, and would make the free,
    # keyless, offline preview -- the only thing CI can run over a template whose
    # citation is still a placeholder -- unusable on exactly the files that most
    # need previewing. Unresolvable task ids are still fatal even in a dry run:
    # that is not a policy refusal, it is a slice that names tasks which do not
    # exist, and there is nothing to preview.
    prepared: list[tuple[CalibrationReference, list, bool]] = []
    refusals: list[str] = []
    for reference in slice_.references:
        specs = _resolve_tasks(catalog, reference)
        cross_model = reference.model_key != entry.key
        if cross_model and not allow_model_mismatch:
            refusals.append(_mismatch_refusal(reference, entry))
        if reference.is_placeholder and not allow_placeholder:
            refusals.append(_placeholder_refusal(reference))
        prepared.append((reference, specs, cross_model))

    if dry_run:
        for reference, specs, cross_model in prepared:
            report.planned.append(
                CalibrationPlanItem(
                    benchmark=reference.benchmark,
                    slice_id=reference.slice_id,
                    reference_model_key=reference.model_key,
                    model_key=entry.key,
                    cross_model=cross_model,
                    is_placeholder=reference.is_placeholder,
                    task_ids=list(reference.task_ids),
                    sample_count=sum(len(spec.samples) for spec in specs),
                )
            )
        report.notes.append("dry run: no model was called and nothing was measured")
        report.notes.extend(f"would be REFUSED without an explicit flag -- {r}" for r in refusals)
        return report

    if refusals:
        raise CalibrationRefusal("; ".join(refusals))

    for reference, specs, cross_model in prepared:
        logs: list[EvalLog] = []
        for spec in specs:
            run_id = run_id_factory()
            log.info(
                "calibration %s: running task %s against %s (run %s)",
                reference.label,
                spec.id,
                entry.key,
                run_id,
            )
            logs.append(
                execute(
                    task=spec,
                    entry=entry,
                    run_id=run_id,
                    api_key=api_key,
                    task_git_sha=task_git_sha,
                    sweep_id=sweep_id,
                    artifact_store=artifact_store,
                    client=client,
                    client_factory=client_factory,
                )
            )

        measured, samples, scored, errors, cost = _aggregate(logs)
        verdict, within, explanation = _decide(
            reference=reference,
            measured=measured,
            error_count=errors,
            scored_count=scored,
            cross_model=cross_model,
            is_placeholder=reference.is_placeholder,
        )
        report.outcomes.append(
            CalibrationOutcome(
                benchmark=reference.benchmark,
                slice_id=reference.slice_id,
                reference_model_key=reference.model_key,
                model_key=entry.key,
                cross_model=cross_model,
                measured_score=measured,
                published_score=reference.published_score,
                tolerance=reference.tolerance,
                delta=None if measured is None else measured - reference.published_score,
                within_tolerance=within,
                verdict=verdict,
                explanation=explanation,
                sample_count=samples,
                scored_count=scored,
                error_count=errors,
                total_cost_usd=cost,
                run_ids=[eval_log.run_id for eval_log in logs],
                task_statuses={eval_log.task_id: str(eval_log.status) for eval_log in logs},
            )
        )

    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ida_harness.calibration",
        description=(
            "Run a slice of a public benchmark through this harness and compare the "
            "score we measure to the number somebody else published for the same model. "
            "A sanity check on the harness, NOT a benchmark result and NOT LLM-judge "
            "calibration. Calls the model under test and spends money at its rates "
            "unless --dry-run is given."
        ),
    )
    parser.add_argument("--slice", required=True, help="path to a calibration/*.yaml slice file")
    parser.add_argument("--model", required=True, help="models.yaml key of the model to measure")
    parser.add_argument(
        "--tasks-dir",
        default=None,
        help="task directory to resolve task_ids against (default: the IDA_TASKS_DIR setting)",
    )
    parser.add_argument(
        "--models-file",
        default=None,
        help="registry file to look --model up in (default: the IDA_MODELS_FILE setting)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve and validate the slice, print the plan, call nothing",
    )
    parser.add_argument(
        "--allow-model-mismatch",
        action="store_true",
        help="compare a number published for one models.yaml key against a run of "
        "another; only correct when the two keys name the same underlying model",
    )
    parser.add_argument(
        "--allow-placeholder",
        action="store_true",
        help=f"measure a reference whose published_source is still a {PLACEHOLDER_MARKER}; "
        "the outcome can never be within tolerance",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """``python -m ida_harness.calibration --slice ... --model ...``.

    Exit codes: **0** when every reference was measured and agreed (or when a
    ``--dry-run`` plan validated), **1** when any reference disagreed, errored or
    measured nothing, **2** when the slice itself is unusable or the comparison
    was refused.  A calibration that silently exits 0 having compared nothing is
    the failure mode this whole module exists to prevent, so
    :attr:`CalibrationReport.ok` is false on an empty outcome list.

    Imports are local for the same reason ``ida_harness.regrade.main``'s are:
    importing this module for :func:`run_calibration` must not drag deployment
    configuration in.
    """
    from ida_core.config import get_settings
    from ida_core.registry import load_registry, resolve_api_key

    args = _build_parser().parse_args(argv)
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")

    models_file = Path(args.models_file) if args.models_file else settings.resolved_models_file()
    tasks_dir = Path(args.tasks_dir) if args.tasks_dir else settings.resolved_tasks_dir()

    try:
        slice_ = load_calibration_slice(args.slice)
        registry = load_registry(models_file)
        entry = registry.get(args.model)
        catalog = TaskCatalog.from_directory(tasks_dir)
    except (CalibrationSliceError, KeyError, ValueError) as exc:
        print(f"calibration: {exc}", file=sys.stderr)
        return 2

    # A dry run never needs a key; a real run against a keyed provider does, and
    # failing here beats failing after the first task has been paid for.
    api_key = None if args.dry_run else resolve_api_key(entry)

    try:
        report = run_calibration(
            slice_=slice_,
            catalog=catalog,
            entry=entry,
            api_key=api_key,
            slice_path=args.slice,
            allow_model_mismatch=args.allow_model_mismatch,
            allow_placeholder=args.allow_placeholder,
            dry_run=args.dry_run,
        )
    except (CalibrationRefusal, CalibrationSliceError) as exc:
        print(f"calibration refused: {exc}", file=sys.stderr)
        return 2

    print(report.table())
    print()
    print(report.summary())
    for outcome in report.outcomes:
        if not outcome.within_tolerance:
            print(f"  {outcome.label}: {outcome.explanation}")
    for note in report.notes:
        print(f"  note: {note}")
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
