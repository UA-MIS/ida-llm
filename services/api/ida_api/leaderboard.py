"""Task-first results: the front door of the product.

**The shape decision, stated once.** The results view leads with the *task*, not
with the model ranking (direction B in ``sprint-planning-ideas-2026-08-26.md``).
A professor arrives asking "can it grade my quizzes?", never "rank these seven
models", and a cross-model leaderboard answers the second question while looking
like it answered the first.  So the primary object here is a
:class:`TaskLeaderboard` -- one task, every model that has been measured on it,
ranked -- and the cross-model comparison is what you get by reading down the
list, not by starting there.

**What this module is allowed to compute.** Aggregation only, over runs that
already exist.  It never scores anything and it never fills a gap: a (task,
model) pair with no finished run is simply absent, and a task with no measured
model reports ``has_results: false`` so the UI can say so in words.  There is no
code path in this file that can produce a number the database did not.

**Faceting is the SLO benchmark's contract, not this module's invention.** A
task's two axes live in its ``tags`` -- ``slo:<ID>`` and ``use-mode:<id>``, with
``slo-benchmark`` marking membership -- and they are parsed by
:mod:`ida_api.slo`, which delegates to ``ida_core.curriculum``.  Outcome ids,
titles and statements are read from ``curriculum/slo.yaml``; **nothing here
hardcodes an outcome or a use mode.**  Results group by ``tags``; per-sample
drill-down reads each sample's un-prefixed ``metadata`` (``slo``, ``use_mode``,
``skill``, ``provenance``), and the validator requires the two spellings to
agree, so a consumer never has to reconcile them.

Tagging a task file therefore remains the only step needed to make a new outcome
appear on this page -- the same "adding a class is a YAML edit" property the SLO
plan depends on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ida_api.pricing import CostNote, cost_note
from ida_api.slo import CurriculumView, in_benchmark, slo_of, use_mode_of
from ida_api.trust import TrustTell, assess
from ida_core.contracts import (
    SYNTHETIC_HARNESS_VERSION,
    SYNTHETIC_MARKER,
    ModelEntry,
    RunRecord,
    RunStatus,
    TaskKind,
    TaskSpec,
    TokenUsage,
)
from ida_core.repositories import latest_terminal_run_per_pair, run_row_to_record
from ida_harness.runner import unscorable_reason

DataResidency = Literal["on_campus", "third_party", "not_a_real_model", "unknown"]

ON_CAMPUS_TAGS = frozenset({"local", "campus", "on-prem", "self-hosted"})
"""Registry tags that mean "the prompt never leaves our hardware".

This is the FERPA-relevant property and the one recommendation only this project
can credibly make, so it is derived from the registry rather than typed into the
UI: adding a campus model is a ``models.yaml`` edit, and the badge follows.
"""

THIRD_PARTY_TAGS = frozenset({"cloud", "hosted", "api"})
NOT_REAL_MODEL_TAGS = frozenset({"mock", "tracer", "stub"})
"""``mock`` is a deterministic echo stub used by the tracer bullet.

It must appear in the raw results (it is a real row, and hiding rows is how a
results page starts lying), and it must never be recommended.  One tag set,
read by both.
"""


def data_residency(entry: ModelEntry) -> DataResidency:
    """Where a prompt sent to this model physically goes."""
    tags = {t.lower() for t in entry.tags}
    if tags & NOT_REAL_MODEL_TAGS:
        return "not_a_real_model"
    if tags & ON_CAMPUS_TAGS:
        return "on_campus"
    if tags & THIRD_PARTY_TAGS:
        return "third_party"
    return "unknown"


RESIDENCY_LABEL: dict[DataResidency, str] = {
    "on_campus": "Runs on campus hardware",
    "third_party": "Sends data to a third party",
    "not_a_real_model": "Test stub — not a usable model",
    "unknown": "Hosting not stated in the registry",
}


def is_demonstration(run: RunRecord) -> bool:
    """Whether this row is seeded illustration rather than a measurement.

    ⚠ A PROPERTY OF THE ROW, NOT OF THE DEPLOYMENT. The obvious alternative --
    a page-level "this environment holds demo data" banner -- cannot be true of
    a database holding both kinds of row, which is exactly what a dev database
    holds the first time somebody runs a real model against a seeded catalogue.
    Per-row is also self-clearing: the flag stops appearing when the row it
    describes is replaced by a real one, so nobody has to remember to take a
    disclaimer down.

    Either marker is believed. ``tools/seed_dev_benchmark.py`` writes both, and
    requiring both would mean a seeder that dropped one silently started
    presenting its fixtures as measurements.
    """
    if run.harness_version == SYNTHETIC_HARNESS_VERSION:
        return True
    extra = run.serving_config.extra if run.serving_config else {}
    return bool(extra.get(SYNTHETIC_MARKER))


def task_axes(spec: TaskSpec) -> tuple[str | None, str | None, bool]:
    """A task's ``(outcome, use mode, is in the benchmark)``.

    Thin on purpose: every rule lives in :mod:`ida_api.slo`, which delegates to
    ``ida_core.curriculum``.  A second parser here is exactly the drift the
    single-source rule exists to prevent -- and a dashboard that parsed tags its
    own way would disagree with the CI gate that validates them.
    """
    tags = list(spec.tags)
    return slo_of(tags), use_mode_of(tags), in_benchmark(tags)


def task_family(spec: TaskSpec) -> str:
    """The family a task belongs to: the id prefix before the first ``/``.

    ``tasks/SCHEMA.md`` makes "one directory, one family, one id prefix" a hard
    authoring convention, so the id is a reliable source and needs no extra tag.
    """
    head, sep, _ = spec.id.partition("/")
    return head if sep else spec.id


class ModelResult(BaseModel):
    """One model's measured standing on one task, with its receipts attached."""

    model_config = ConfigDict(extra="forbid")

    model_key: str
    display_name: str
    model_tags: list[str] = Field(default_factory=list)
    data_residency: DataResidency
    data_residency_label: str
    enabled: bool
    """False when the registry has since disabled the model.  The measurement
    still stands -- it happened -- but the model cannot be run today."""

    recommendable: bool
    """False for test stubs.  A recommendation engine must never return one."""

    mean_score: float | None
    """``None`` is never zero.  :attr:`trust` says which kind of ``None`` it is."""

    scored_count: int
    sample_count: int
    error_count: int
    total_cost_usd: float
    """What WE spent measuring this pair -- not what the reader would pay.

    ⚠ NOT A PRICE, AND THE DIFFERENCE HAS BURNED A PAGE BEFORE. This is our
    measurement spend on this one task: it scales with how many samples we
    chose to run, it is ``0`` on a cache hit, and it is ``0`` for every row the
    dev seeder writes. A UI that divides it by :attr:`scored_count` and calls
    the result "cost per answer" is describing our benchmark, not the model --
    and on a seeded environment it would report every model as free. Use
    :attr:`price` for anything a reader is meant to budget against.
    """

    price: CostNote | None
    """The registry's published rate card, or ``None`` for an unregistered key.

    THE number for a value comparison: it is what the provider charges, it does
    not move when our sample counts move, and it exists for a model nobody has
    run yet. ``None`` is not "free" -- it means the model is not in
    ``models.yaml`` at all, so we have nothing to quote.
    """

    usage: TokenUsage
    """Tokens behind :attr:`total_cost_usd`, so a rate card can become a figure.

    :attr:`price` is per MILLION tokens, which no professor thinks in. Carrying
    the token counts lets a consumer turn the rate card into "what one answer of
    the length we actually observed costs" without inventing an answer length.
    All-zero means no token accounting was recorded, which is not the same as a
    free run -- and a consumer that cannot tell them apart should say so rather
    than divide.
    """

    demonstration: bool
    """True when this row was seeded for illustration and never measured.

    Carried per row so a UI can label exactly the numbers that are illustrative,
    on a board that may hold both kinds at once.
    """

    trust: TrustTell

    run_id: str
    """THE receipt (D-3).  Every number on this page is one click from the exact
    run that produced it -- transcripts, scorer, serving config and all."""

    run_status: RunStatus
    task_content_sha: str | None
    measured_at: str | None
    """When the run that produced this number finished, ISO-8601."""


class TaskLeaderboard(BaseModel):
    """One task, every model measured on it, best first."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    title: str
    description: str
    kind: TaskKind
    domain: str
    scorer: str
    family: str
    tags: list[str] = Field(default_factory=list)

    slo: str | None = None
    """The outcome this task measures, e.g. ``SLO2``.  ``None`` when untagged.

    The grouping key for the per-outcome view.  Its *meaning* -- title,
    statement, whether it is text-benchmarkable -- comes from
    ``curriculum/slo.yaml`` via :attr:`LeaderboardResponse.curriculum`, never
    from this row and never from the UI.
    """

    use_mode: str | None = None
    """What is asked of the model: ``capability`` today; ``assistive`` and
    ``instructional`` are declared but not yet in use."""

    in_benchmark: bool = False
    """Carries the ``slo-benchmark`` tag.  One filter selects the whole
    benchmark, which is why the tag exists at all."""

    sample_count: int
    scorable: bool
    unscorable_reason: str | None = None

    results: list[ModelResult] = Field(default_factory=list)
    has_results: bool
    """False when no model has a finished run on this task.

    Read this rather than ``len(results) > 0`` at a call site that cares about
    the distinction between "nothing measured" and "measured, all null".
    """

    best_model_key: str | None = None
    """Highest scoring *recommendable* model, or ``None`` when nothing scored.

    Test stubs are excluded here and only here: leaving ``mock`` out of the
    ranking but in the table is the difference between a leaderboard that says
    something true and one whose winner is an echo server.
    """


class LeaderboardResponse(BaseModel):
    """``GET /leaderboard``."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskLeaderboard]
    task_count: int
    """Tasks in the catalog matching the filters, measured or not."""

    measured_task_count: int
    runs_considered: int
    has_any_results: bool
    """False on a fresh install.  The UI renders an honest empty state on this
    flag rather than an empty table that looks like a rendering bug."""

    curriculum: CurriculumView
    """``curriculum/slo.yaml``, read not retyped.

    Carried on the response so the UI can render an outcome's real title and
    statement beside its results without ever holding a copy of the nine.
    ``available: false`` is a legitimate state and says so in words.
    """

    benchmark_task_count: int = 0
    """Tasks carrying the ``slo-benchmark`` tag."""

    slos: list[str] = Field(default_factory=list)
    """Outcome ids present in the returned tasks, in curriculum order.

    Curriculum order, not alphabetical: ``SLO10`` would sort before ``SLO2``,
    and a programme's outcomes have an order its own document defines. Ids the
    curriculum does not know are appended rather than dropped -- an unknown id
    is a tagging error the CI gate reports, and hiding it here would hide a real
    row from the person who has to fix it.
    """

    use_modes: list[str] = Field(default_factory=list)
    families: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


def _sort_key(result: ModelResult) -> tuple:
    """Best first: scored before unscored, then by score, then deterministically.

    Confidence deliberately does NOT enter the ordering.  Sorting a
    high-confidence 0.80 above a low-confidence 0.95 would be this module
    quietly making the reader's judgement call for them; the badges exist so the
    reader can make it themselves, on a list whose order still means one thing.
    """
    return (
        0 if result.mean_score is not None else 1,
        -(result.mean_score or 0.0),
        result.model_key,
    )


def build_task_leaderboard(
    spec: TaskSpec,
    runs: list[RunRecord],
    registry_by_key: dict[str, ModelEntry],
) -> TaskLeaderboard:
    """Assemble one task's row set from its newest finished run per model."""
    results: list[ModelResult] = []
    for run in runs:
        entry = registry_by_key.get(run.model_key)
        residency = data_residency(entry) if entry else "unknown"
        results.append(
            ModelResult(
                model_key=run.model_key,
                display_name=entry.display_name if entry else run.model_key,
                model_tags=list(entry.tags) if entry else [],
                data_residency=residency,
                data_residency_label=RESIDENCY_LABEL[residency],
                # A model dropped from the registry entirely is not runnable
                # either; `False` is the honest answer for both cases.
                enabled=bool(entry and entry.enabled),
                recommendable=residency != "not_a_real_model" and entry is not None,
                mean_score=run.mean_score,
                scored_count=run.scored_count,
                sample_count=run.sample_count,
                error_count=run.error_count,
                total_cost_usd=run.total_cost_usd,
                # Read off the registry entry we already resolved for the
                # residency badge, so the price and the badge can never come
                # from two different readings of the same entry.
                price=cost_note(entry, residency) if entry else None,
                usage=run.total_usage,
                demonstration=is_demonstration(run),
                trust=assess(
                    kind=spec.kind,
                    scorer=spec.scorer.kind.value,
                    scorable=spec.is_scorable,
                    unscorable_reason=unscorable_reason(spec),
                    mean_score=run.mean_score,
                    scored_count=run.scored_count,
                    sample_count=run.sample_count,
                    error_count=run.error_count,
                ),
                run_id=run.id,
                run_status=run.status,
                task_content_sha=run.task_content_sha,
                measured_at=(run.finished_at or run.created_at).isoformat(),
            )
        )
    results.sort(key=_sort_key)

    slo, use_mode, benchmark_member = task_axes(spec)
    best = next(
        (r.model_key for r in results if r.mean_score is not None and r.recommendable),
        None,
    )
    return TaskLeaderboard(
        task_id=spec.id,
        title=spec.title,
        description=spec.description,
        kind=spec.kind,
        domain=spec.domain,
        scorer=spec.scorer.kind.value,
        family=task_family(spec),
        tags=list(spec.tags),
        slo=slo,
        use_mode=use_mode,
        in_benchmark=benchmark_member,
        sample_count=len(spec.samples),
        scorable=spec.is_scorable,
        unscorable_reason=unscorable_reason(spec),
        results=results,
        has_results=bool(results),
        best_model_key=best,
    )


def _ordered_slos(boards: list[TaskLeaderboard], curriculum: CurriculumView) -> list[str]:
    """Outcome ids present, in the order the curriculum publishes them.

    NOT alphabetical: ``SLO10`` sorts before ``SLO2``, and a programme's
    outcomes have an order its own document defines. An id the curriculum does
    not know is appended rather than dropped -- it is a tagging error, the CI
    gate reports it, and hiding the row here would hide it from the person who
    has to fix it.
    """
    present = {b.slo for b in boards if b.slo}
    known = [o.id for o in curriculum.outcomes if o.id in present]
    unknown = sorted(present - set(known))
    return known + unknown


def build_leaderboard(
    session: Session,
    *,
    specs: list[TaskSpec],
    registry_by_key: dict[str, ModelEntry],
    curriculum: CurriculumView,
) -> LeaderboardResponse:
    """Aggregate the newest finished run per (task, model) into the results view.

    One database round trip for every task on the page: the per-pair reduction
    happens in SQL (see :func:`latest_terminal_run_per_pair`), not in a loop of
    queries per task.

    ``curriculum`` is passed in rather than loaded here so it is read once per
    process at startup, not once per request -- and so a test can exercise both
    the "curriculum available" and "curriculum missing" paths without touching
    the filesystem.
    """
    spec_ids = [spec.id for spec in specs]
    rows = latest_terminal_run_per_pair(session, task_ids=spec_ids)
    runs_by_task: dict[str, list[RunRecord]] = {}
    for row in rows:
        record = run_row_to_record(row)
        runs_by_task.setdefault(record.task_id, []).append(record)

    boards = [
        build_task_leaderboard(spec, runs_by_task.get(spec.id, []), registry_by_key)
        for spec in specs
    ]
    # Measured tasks first so a mostly-empty catalog still leads with whatever
    # real data exists; ladder order (l1, l2, ...) within each group, which task
    # ids already sort into.
    boards.sort(key=lambda b: (not b.has_results, b.task_id))

    return LeaderboardResponse(
        tasks=boards,
        task_count=len(boards),
        measured_task_count=sum(1 for b in boards if b.has_results),
        runs_considered=len(rows),
        has_any_results=any(b.has_results for b in boards),
        curriculum=curriculum,
        benchmark_task_count=sum(1 for b in boards if b.in_benchmark),
        slos=_ordered_slos(boards, curriculum),
        use_modes=sorted({b.use_mode for b in boards if b.use_mode}),
        families=sorted({b.family for b in boards}),
        domains=sorted({b.domain for b in boards}),
    )
