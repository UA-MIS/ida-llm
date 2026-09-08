"""The SLO axis, as the dashboard consumes it.

``curriculum/slo.yaml`` is the authority for what an outcome id *means*, and
:mod:`ida_core.curriculum` is the authority for how a task's tags are *parsed*.
This module is neither — it is the thin adapter that lets the results view read
both without owning either, and its whole job is to make sure the dashboard
never becomes a second, drifting copy of the curriculum.

The contract it consumes, stated once so a reader of this file need not go
looking (it is defined and enforced in :mod:`ida_core.curriculum`):

``slo-benchmark``     the task is part of the SLO-anchored benchmark. One tag,
                      one filter, the whole benchmark.
``slo:<ID>``          which outcome, e.g. ``slo:SLO2``. Exactly one per task.
``use-mode:<id>``     what is asked of the model, e.g. ``use-mode:capability``.
                      Exactly one per task.

Tags are split on the **first** colon, so a value containing a colon survives.
Sample ``metadata`` carries the same two facts un-prefixed (``slo``,
``use_mode``) for per-sample drill-down; the validator requires the two
spellings to agree, so the dashboard groups by tags and drills by metadata
without ever having to reconcile them.

⚠ NOTHING IN THE UI HARDCODES AN OUTCOME. There are nine of them, two are not
text-benchmarkable, and the wording is the registrar's. A list of nine strings
typed into a component is a list that silently disagrees with the programme the
first time the registrar edits it, and the disagreement would surface as a
dashboard confidently mislabelling a real score.

Merge-order note
----------------
``ida_core.curriculum`` arrives in the SLO-benchmark pull request, which is open
alongside this one. Importing it unconditionally would make this branch's CI
depend on merge order, so the import is optional and the degrade is **narrow and
loud**: without it the dashboard still groups by outcome id (the tag parse is
four lines and is pinned by a test against the documented rule), but it reports
``available: false`` and shows ids with no statements rather than inventing any.
When both are merged, delete :func:`_fallback_slo_of` and friends and import
directly — there should be exactly one parser.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

BENCHMARK_TAG = "slo-benchmark"
SLO_TAG_PREFIX = "slo:"
USE_MODE_TAG_PREFIX = "use-mode:"
SLO_METADATA_KEY = "slo"
USE_MODE_METADATA_KEY = "use_mode"

try:  # pragma: no cover - exercised by whichever branch is checked out
    from ida_core.curriculum import (  # type: ignore[import-not-found]
        BENCHMARK_TAG as _CORE_BENCHMARK_TAG,
    )
    from ida_core.curriculum import (
        default_curriculum_path as _core_default_path,
    )
    from ida_core.curriculum import (
        load_curriculum as _core_load_curriculum,
    )
    from ida_core.curriculum import (
        slo_of as _core_slo_of,
    )
    from ida_core.curriculum import (
        use_mode_of as _core_use_mode_of,
    )

    CURRICULUM_MODULE_AVAILABLE = True
    BENCHMARK_TAG = _CORE_BENCHMARK_TAG
except ImportError:  # pragma: no cover - see the merge-order note above
    CURRICULUM_MODULE_AVAILABLE = False
    _core_load_curriculum = None  # type: ignore[assignment]
    _core_default_path = None  # type: ignore[assignment]
    _core_slo_of = None  # type: ignore[assignment]
    _core_use_mode_of = None  # type: ignore[assignment]


def _values_for(tags: list[str], prefix: str) -> list[str]:
    """Every value carried under a ``prefix:`` tag, in file order.

    Split on the FIRST colon only — the rule ``ida_core.curriculum`` documents
    for consumers, restated here rather than approximated.
    """
    return [tag[len(prefix) :] for tag in tags if tag.startswith(prefix)]


def _fallback_slo_of(tags: list[str]) -> str | None:
    values = _values_for(tags, SLO_TAG_PREFIX)
    return values[0] if len(values) == 1 else None


def _fallback_use_mode_of(tags: list[str]) -> str | None:
    values = _values_for(tags, USE_MODE_TAG_PREFIX)
    return values[0] if len(values) == 1 else None


def slo_of(tags: list[str]) -> str | None:
    """The outcome a task claims, or ``None`` when it claims none — or several.

    Several is ``None`` deliberately, matching the core helper: two outcome tags
    is not a task measuring two outcomes, it is a task whose grouping is
    undefined, and the validator is what reports it as an error. Grouping it
    under an arbitrary one of the two would file a real score under a heading
    the author did not choose.
    """
    return _core_slo_of(tags) if _core_slo_of else _fallback_slo_of(tags)


def use_mode_of(tags: list[str]) -> str | None:
    """The use mode a task claims, or ``None``.  See :func:`slo_of`."""
    return _core_use_mode_of(tags) if _core_use_mode_of else _fallback_use_mode_of(tags)


def in_benchmark(tags: list[str]) -> bool:
    """Is this task part of the SLO-anchored benchmark? One tag, one filter."""
    return BENCHMARK_TAG in tags


def sample_facets(metadata: dict[str, Any]) -> dict[str, str]:
    """The per-sample drill-down keys, un-prefixed, as authored.

    ``slo`` and ``use_mode`` repeat the task's tags (the validator requires them
    to agree); ``skill`` and ``provenance`` are the sample's own. Everything
    else in ``metadata`` is left alone — it belongs to the task author, and a
    dashboard that decided which of an author's keys were interesting would
    start hiding the one that mattered.
    """
    interesting = (SLO_METADATA_KEY, USE_MODE_METADATA_KEY, "skill", "provenance")
    return {key: str(metadata[key]) for key in interesting if metadata.get(key) not in (None, "")}


# --------------------------------------------------------------------------
# What the dashboard needs from curriculum/slo.yaml
# --------------------------------------------------------------------------


class OutcomeView(BaseModel):
    """One Student Learning Outcome, as published."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    statement: str
    """The registrar's wording, read from the file. Never retyped here."""

    text_benchmarkable: bool
    """False for the outcomes a single-turn text benchmark cannot measure.

    Surfaced rather than filtered out: a benchmark that silently covered seven
    of nine outcomes would read as though the programme has seven.
    """

    benchmark_note: str


class UseModeView(BaseModel):
    """One end of the "what is being asked of the model" axis."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    statement: str
    in_use: bool
    """False declares the spelling without permitting a task to tag it yet."""


class CourseCoverageView(BaseModel):
    """One row of the published course-by-outcome grid, as the dashboard reads it.

    ⚠ SERVED BECAUSE THE HIERARCHY IS THE PRODUCT, NOT BECAUSE IT IS TIDY. The
    guided drill-down goes programme → course → outcome → evidence, and the
    middle two levels exist ONLY in ``curriculum/slo.yaml``'s coverage grid.
    Until this field existed a client could ask which outcomes a course teaches
    only by shipping its own transcription of the registrar's map -- which is
    the exact failure :mod:`ida_api.slo` was written to prevent, one table over.

    ``outcomes`` maps outcome id to the published level (``I``/``R``/``M``/``A``/
    ``M+A``). A key that is ABSENT means the map does not mark that pair; it does
    NOT mean the level is unknown, and it must never be rendered as a zero.
    """

    model_config = ConfigDict(extra="forbid")

    course: str
    """The course code as the map spells it, e.g. ``MIS 200``."""

    title: str
    outcomes: dict[str, str]
    """Outcome id to level code. Only the cells the published map fills in."""


class CurriculumView(BaseModel):
    """``curriculum/slo.yaml``, projected for the dashboard.

    ``available: false`` is a first-class state, not an error: this repository
    has run without a curriculum map, and a results page must still work — it
    just groups by outcome *id* and says it has no statements, rather than
    guessing at nine of them.
    """

    model_config = ConfigDict(extra="forbid")

    available: bool
    unavailable_reason: str | None = None
    program: str | None = None
    source: str | None = None
    outcomes: list[OutcomeView] = Field(default_factory=list)
    use_modes: list[UseModeView] = Field(default_factory=list)
    coverage: list[CourseCoverageView] = Field(default_factory=list)
    """The published course x outcome grid, in the map's own order.

    Empty when ``available`` is false, for the same reason ``outcomes`` is: a
    deployment without the map has no courses to name, and naming some would be
    inventing a curriculum.
    """

    def outcome(self, outcome_id: str) -> OutcomeView | None:
        return next((o for o in self.outcomes if o.id == outcome_id), None)

    def use_mode(self, mode_id: str) -> UseModeView | None:
        return next((m for m in self.use_modes if m.id == mode_id), None)

    def course(self, course_code: str) -> CourseCoverageView | None:
        """One coverage row, or ``None`` for a code this map does not list.

        ``None`` rather than an empty row: "this programme has no MIS 200" and
        "MIS 200 teaches no outcomes" are different answers, and a caller that
        got a blank row for a course that does not exist would render a course
        page for it.
        """
        return next((c for c in self.coverage if c.course == course_code), None)


UNAVAILABLE_NO_MODULE = (
    "The curriculum loader (ida_core.curriculum) is not installed in this build, "
    "so outcome statements are unavailable. Outcome ids still group results."
)
UNAVAILABLE_NO_FILE = (
    "No curriculum/slo.yaml in this deployment, so outcome statements are "
    "unavailable. Outcome ids still group results."
)


def load_curriculum_view(root: Path | str) -> CurriculumView:
    """Read ``curriculum/slo.yaml`` if this build can, and say so when it cannot.

    Never raises. A malformed curriculum map is a real problem, but it is the
    task validator's problem (``make lint-tasks`` is the gate that fails a pull
    request over it) — taking the results page down over it would replace a
    visible data error with an invisible outage.
    """
    if not CURRICULUM_MODULE_AVAILABLE or _core_load_curriculum is None:
        return CurriculumView(available=False, unavailable_reason=UNAVAILABLE_NO_MODULE)

    path = (
        _core_default_path(root) if _core_default_path else Path(root) / "curriculum" / "slo.yaml"
    )
    if not Path(path).is_file():
        return CurriculumView(available=False, unavailable_reason=UNAVAILABLE_NO_FILE)

    try:
        curriculum = _core_load_curriculum(path)
    except Exception as exc:
        log.exception("could not load the curriculum map at %s", path)
        return CurriculumView(
            available=False,
            unavailable_reason=(
                f"curriculum/slo.yaml could not be loaded ({exc}). Outcome ids still "
                "group results; run `make lint-tasks` to see the full report."
            ),
        )

    return CurriculumView(
        available=True,
        program=curriculum.program,
        source=curriculum.source,
        outcomes=[
            OutcomeView(
                id=outcome.id,
                title=outcome.title,
                statement=outcome.statement,
                text_benchmarkable=outcome.text_benchmarkable,
                benchmark_note=outcome.benchmark_note,
            )
            for outcome in curriculum.outcomes
        ],
        use_modes=[
            UseModeView(
                id=mode.id,
                title=mode.title,
                statement=mode.statement,
                in_use=mode.in_use,
            )
            for mode in curriculum.use_modes
        ],
        coverage=[
            CourseCoverageView(
                course=row.course,
                title=row.title,
                # `str(level)` because CoverageLevel is a StrEnum: the wire
                # format is the published legend's letter, not a Python member
                # name, and a consumer must be able to print it verbatim.
                outcomes={slo: str(level) for slo, level in row.outcomes.items()},
            )
            for row in curriculum.coverage
        ],
    )
