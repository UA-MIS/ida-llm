"""The Student Learning Outcomes, and the rule that keeps task tags honest.

``curriculum/slo.yaml`` is the backbone of the SLO-anchored benchmark: the nine
programme outcomes, the two axes a task is filed under (outcome and use mode),
and the published course-by-outcome coverage grid.  This module parses it and
answers the one question that cannot be answered by looking at a task file
alone: **does this task's ``slo:`` tag name an outcome that exists?**

Why that question is load-bearing
---------------------------------
A benchmark result is a number plus the thing it is a number *about*.  The
platform already refuses to lose the first half -- a result carries its serving
config and the task's git SHA (**D-1**).  An ``slo:SL02`` typo loses the second
half just as completely, and does it **silently**: the task loads, the run
succeeds, the score is real, and it is filed under a heading that does not
exist, so it disappears from every per-outcome view without ever appearing in
an error.

So the check runs in ``tools/validate_tasks.py``, which is the ``task-schema``
CI gate: a mistyped outcome fails the pull request, not the analysis three
weeks later.

The two axes
------------
``slo:<ID>``        which outcome the task measures, e.g. ``slo:SLO2``.
``use-mode:<id>``   what is being asked of the model, e.g. ``use-mode:capability``.

Both live in ``tags`` rather than in a structured field because a task file has
**no task-level ``metadata``** -- the JSON Schema sets ``additionalProperties:
false`` at the top level, and ``tags`` is the one free-form list.  That is not a
workaround: ``tags`` is exposed by ``GET /tasks/{id}``, and results are reported
per (task, model), so ``tags`` is exactly the granularity a per-outcome view
groups on.

Sample ``metadata`` carries the same two facts un-prefixed (``slo: SLO2``,
``use_mode: capability``) for per-sample drill-down.  Two spellings of one fact
is a drift risk, so :func:`check_task_tags` requires them to agree rather than
trusting that they do.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ida_core.contracts import TaskSpec
from ida_core.validation import ValidationError, load_yaml, validate_curriculum_document

BENCHMARK_TAG = "slo-benchmark"
"""Marks a task as part of the SLO-anchored benchmark.

A task carrying it MUST also carry exactly one ``slo:`` and one ``use-mode:``
tag -- that is what makes "select the whole benchmark" a single filter rather
than a list of family names somebody has to keep up to date.
"""

SLO_TAG_PREFIX = "slo:"
USE_MODE_TAG_PREFIX = "use-mode:"

SLO_METADATA_KEY = "slo"
USE_MODE_METADATA_KEY = "use_mode"


class CoverageLevel(StrEnum):
    """How deeply a course covers an outcome, per the published map's legend.

    Ordering is not implied by the enum: ``M+A`` is not "more than" ``A``, it is
    a different pair of claims (this course masters the outcome, AND the
    programme measures the outcome here).  Anything wanting a depth ordering
    should say so explicitly rather than sorting these values.
    """

    INTRODUCED = "I"
    REINFORCED = "R"
    MASTERED = "M"
    ASSESSMENT_POINT = "A"
    MASTERED_AND_ASSESSMENT_POINT = "M+A"


ASSESSMENT_LEVELS = frozenset(
    {CoverageLevel.ASSESSMENT_POINT, CoverageLevel.MASTERED_AND_ASSESSMENT_POINT}
)
"""The levels at which the programme actually *reports* on an outcome.

Worth naming: a benchmark family aimed at a (course, outcome) pair the
department already assesses is aimed at something with an existing human
number to compare against later.  A family aimed at an ``I`` cell is not.
"""


class Outcome(BaseModel):
    """One Student Learning Outcome."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    statement: str
    """The outcome as the programme publishes it."""

    text_benchmarkable: bool
    """Whether a single-turn text benchmark can measure this outcome at all.

    Recorded rather than inferred.  It is ``False`` for SLO5 (Teamwork) and
    SLO8 (Oral Communication), and stating so is the point: a benchmark that
    silently covered seven outcomes would read as though the programme has
    seven.
    """

    benchmark_note: str
    """Why it is scored the way it is -- or, when not benchmarkable, why not."""


class UseMode(BaseModel):
    """One end of the "what is being asked of the model" axis."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    statement: str
    in_use: bool
    """``False`` declares the spelling without permitting a task to tag it yet."""


class CourseCoverage(BaseModel):
    """One row of the published course-by-outcome grid."""

    model_config = ConfigDict(extra="forbid")

    course: str
    title: str
    outcomes: dict[str, CoverageLevel]
    """Only the cells the map fills in.  An absent key means the map does not
    mark that pair -- **not** that the level is unknown."""


class CurriculumMap(BaseModel):
    """Parsed ``curriculum/slo.yaml``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    program: str
    source: str
    source_title: str = ""
    source_last_modified: str = ""
    retrieved: str
    outcomes: Annotated[list[Outcome], Field(min_length=1)]
    use_modes: Annotated[list[UseMode], Field(min_length=1)]
    coverage: Annotated[list[CourseCoverage], Field(min_length=1)]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> CurriculumMap:
        for label, values in (
            ("outcome", [o.id for o in self.outcomes]),
            ("use mode", [m.id for m in self.use_modes]),
            ("course", [c.course for c in self.coverage]),
        ):
            dupes = sorted({v for v in values if values.count(v) > 1})
            if dupes:
                raise ValueError(f"duplicate {label} ids in curriculum: {dupes}")
        return self

    @model_validator(mode="after")
    def _coverage_cells_name_declared_outcomes(self) -> CurriculumMap:
        """A grid cell for an outcome that does not exist is the same silent
        misfiling this module exists to prevent, one file earlier."""
        known = {o.id for o in self.outcomes}
        problems = [
            f"{row.course} references undeclared outcome {slo!r}"
            for row in self.coverage
            for slo in sorted(row.outcomes)
            if slo not in known
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @model_validator(mode="after")
    def _at_least_one_mode_is_usable(self) -> CurriculumMap:
        """Every mode declared but none in use makes every benchmark tag invalid,
        which would be a confusing way to discover a one-word edit."""
        if not any(m.in_use for m in self.use_modes):
            raise ValueError("no use mode has in_use: true, so no task could be tagged")
        return self

    # -- lookups ---------------------------------------------------------

    def outcome_ids(self) -> list[str]:
        return [o.id for o in self.outcomes]

    def get(self, outcome_id: str) -> Outcome:
        for outcome in self.outcomes:
            if outcome.id == outcome_id:
                return outcome
        raise KeyError(f"no outcome with id {outcome_id!r} in the curriculum map")

    def text_benchmarkable_ids(self) -> list[str]:
        return [o.id for o in self.outcomes if o.text_benchmarkable]

    def use_mode_ids(self) -> list[str]:
        return [m.id for m in self.use_modes]

    def in_use_mode_ids(self) -> list[str]:
        return [m.id for m in self.use_modes if m.in_use]

    def course(self, code: str) -> CourseCoverage:
        for row in self.coverage:
            if row.course == code:
                return row
        raise KeyError(f"no course with code {code!r} in the curriculum map")

    def outcomes_for_course(self, code: str) -> dict[str, CoverageLevel]:
        """The outcomes one course covers, and at what level."""
        return dict(self.course(code).outcomes)

    def courses_for_outcome(self, outcome_id: str) -> dict[str, CoverageLevel]:
        """Every course that covers an outcome, keyed by course code.

        Raises ``KeyError`` for an outcome that is not declared, rather than
        returning an empty mapping: "no course covers SLO4" and "you misspelled
        SLO4" are different answers and only one of them is ever true.
        """
        self.get(outcome_id)
        return {
            row.course: level
            for row in self.coverage
            for slo, level in row.outcomes.items()
            if slo == outcome_id
        }

    def is_assessment_point(self, course_code: str, outcome_id: str) -> bool:
        """Does the programme *report* on this outcome in this course?"""
        return self.course(course_code).outcomes.get(outcome_id) in ASSESSMENT_LEVELS


def load_curriculum(path: Path | str) -> CurriculumMap:
    """Load and fully validate ``curriculum/slo.yaml``.

    Runs both layers, for the reason given in :mod:`ida_core.validation`: the
    JSON Schema for structure, the pydantic model for the cross-field rules a
    schema expresses badly (a coverage cell naming an undeclared outcome).
    """
    path = Path(path)
    if not path.is_file():
        raise ValidationError(path, ["curriculum file not found"])
    try:
        document = load_yaml(path)
    except Exception as exc:
        raise ValidationError(path, [f"could not parse YAML: {exc}"]) from exc
    if not isinstance(document, dict):
        raise ValidationError(path, [f"top level must be a mapping, got {type(document).__name__}"])
    validate_curriculum_document(document, path)
    try:
        return CurriculumMap.model_validate(document)
    except Exception as exc:
        raise ValidationError(path, [str(exc)]) from exc


def default_curriculum_path(root: Path | str) -> Path:
    """Where the curriculum map lives relative to a repo root."""
    return Path(root) / "curriculum" / "slo.yaml"


# --------------------------------------------------------------------------
# The tag contract
# --------------------------------------------------------------------------


def _values_for(tags: list[str], prefix: str) -> list[str]:
    """Every value carried under a ``prefix:`` tag, in file order.

    Split on the FIRST colon only, so a value containing a colon survives -- and
    so the parse rule is the one documented for consumers.
    """
    return [t[len(prefix) :] for t in tags if t.startswith(prefix)]


def slo_of(tags: list[str]) -> str | None:
    """The outcome a task claims, or ``None`` if it claims none.

    Returns ``None`` for a task carrying *several* ``slo:`` tags too; ambiguity
    is not a claim.  :func:`check_task_tags` is what reports it as an error.
    """
    values = _values_for(tags, SLO_TAG_PREFIX)
    return values[0] if len(values) == 1 else None


def use_mode_of(tags: list[str]) -> str | None:
    """The use mode a task claims, or ``None``.  See :func:`slo_of`."""
    values = _values_for(tags, USE_MODE_TAG_PREFIX)
    return values[0] if len(values) == 1 else None


def check_task_tags(spec: TaskSpec, curriculum: CurriculumMap) -> list[str]:
    """Every problem with one task's SLO tagging.  Empty list means clean.

    Returns *all* problems rather than raising on the first, because this is
    called in a loop over the whole tree by ``tools/validate_tasks.py`` and an
    author fixing tags should get the list in one pass.

    Enforced, in order:

    1. An ``slo:`` or ``use-mode:`` tag appears at most once.  Two outcome tags
       is not a task measuring two outcomes, it is a task whose grouping is
       undefined.
    2. The values name a declared outcome, and a use mode that is ``in_use``.
    3. The outcome is ``text_benchmarkable``.  Tagging a task ``slo:SLO5`` would
       publish a teamwork score derived from a single-turn prompt.
    4. A task carrying either tag carries the :data:`BENCHMARK_TAG`, and vice
       versa -- so the benchmark is exactly one filter.
    5. Sample ``metadata`` agrees with the tags.  The two spellings exist for
       two different consumers; the moment they disagree, one of them is lying
       and nothing else in the system would notice.

    A task with none of the three tags is not part of this benchmark and is
    returned clean -- the exemplar and demo families predate it.
    """
    tags = list(spec.tags)
    slo_values = _values_for(tags, SLO_TAG_PREFIX)
    mode_values = _values_for(tags, USE_MODE_TAG_PREFIX)
    tagged_benchmark = BENCHMARK_TAG in tags

    if not slo_values and not mode_values and not tagged_benchmark:
        return []

    problems: list[str] = []
    here = f"task {spec.id!r}"

    for label, prefix, values in (
        ("outcome", SLO_TAG_PREFIX, slo_values),
        ("use mode", USE_MODE_TAG_PREFIX, mode_values),
    ):
        if not values:
            problems.append(f"{here}: carries no {prefix!r} tag, so its {label} is unrecorded")
        elif len(values) > 1:
            problems.append(
                f"{here}: carries {len(values)} {prefix!r} tags ({values}); "
                f"exactly one is required, because a result row has one {label}"
            )

    if not tagged_benchmark:
        problems.append(
            f"{here}: is SLO-tagged but does not carry the {BENCHMARK_TAG!r} tag, "
            "so it would be missing from a benchmark-wide selection"
        )

    slo = slo_values[0] if len(slo_values) == 1 else None
    mode = mode_values[0] if len(mode_values) == 1 else None

    if slo is not None:
        if slo not in curriculum.outcome_ids():
            problems.append(
                f"{here}: tag '{SLO_TAG_PREFIX}{slo}' names no outcome in the curriculum map "
                f"(known: {', '.join(curriculum.outcome_ids())})"
            )
        elif not curriculum.get(slo).text_benchmarkable:
            problems.append(
                f"{here}: outcome {slo} is marked text_benchmarkable: false in the curriculum map "
                "and must not be scored by a text benchmark"
            )

    if mode is not None and mode not in curriculum.in_use_mode_ids():
        known = ", ".join(curriculum.in_use_mode_ids()) or "<none>"
        declared = ", ".join(curriculum.use_mode_ids())
        problems.append(
            f"{here}: tag '{USE_MODE_TAG_PREFIX}{mode}' is not a use mode that is in use "
            f"(in use: {known}; declared: {declared})"
        )

    problems.extend(_check_sample_metadata(spec, slo, mode))
    return problems


def _check_sample_metadata(spec: TaskSpec, slo: str | None, mode: str | None) -> list[str]:
    """Sample metadata must repeat the task's two tags, and must not contradict them."""
    problems: list[str] = []
    for sample in spec.samples:
        for key, expected in (
            (SLO_METADATA_KEY, slo),
            (USE_MODE_METADATA_KEY, mode),
        ):
            if expected is None:
                continue
            actual: Any = sample.metadata.get(key)
            if actual is None:
                problems.append(
                    f"task {spec.id!r} sample {sample.id!r}: metadata is missing {key!r}; "
                    f"per-sample drill-down needs it and it must read {expected!r}"
                )
            elif actual != expected:
                problems.append(
                    f"task {spec.id!r} sample {sample.id!r}: metadata {key}={actual!r} "
                    f"contradicts the task tag ({expected!r})"
                )
    return problems
