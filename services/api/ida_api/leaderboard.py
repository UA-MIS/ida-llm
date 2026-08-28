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

**Faceting (SLOs and use-modes).** ``project-direction-2026-08-26.md`` puts the
benchmark on the curriculum's own Student Learning Outcomes and splits each task
by use-mode (capability/integrity-risk, professor-assist, student-learning-aid).
No task carries those tags yet.  Rather than hardcode a taxonomy that does not
exist, this module reads *prefixed tags* (``slo:mis200-3``,
``use-mode:professor-assist``, ``audience:researcher``) out of the tag list the
task schema already exposes, and reports whichever facets it finds.  Tagging a
task file is therefore the only step needed to make the grouping appear -- no
code change, which is the same "adding a class is a YAML edit" property the SLO
plan depends on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ida_api.trust import TrustTell, assess
from ida_core.contracts import ModelEntry, RunRecord, RunStatus, TaskKind, TaskSpec
from ida_core.repositories import latest_terminal_run_per_pair, run_row_to_record
from ida_harness.runner import unscorable_reason

FACET_PREFIXES: dict[str, str] = {
    "slo": "slo",
    "use-mode": "use_mode",
    "audience": "audience",
}
"""Tag prefixes promoted to first-class facets, ``prefix:value``.

Kept to a closed set on purpose.  Treating *every* colon-tag as a facet would
turn a typo into a new filter category that looks official in the UI.
"""

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


def task_facets(spec: TaskSpec) -> dict[str, list[str]]:
    """Extract ``slo:``/``use-mode:``/``audience:`` facets from a task's tags."""
    facets: dict[str, list[str]] = {}
    for tag in spec.tags:
        prefix, sep, value = tag.partition(":")
        if not sep or not value:
            continue
        field = FACET_PREFIXES.get(prefix.strip().lower())
        if field is None:
            continue
        facets.setdefault(field, []).append(value.strip())
    return facets


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
    facets: dict[str, list[str]] = Field(default_factory=dict)
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

    facet_values: dict[str, list[str]] = Field(default_factory=dict)
    """Every facet value present in the returned tasks, for building filters."""

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
        facets=task_facets(spec),
        sample_count=len(spec.samples),
        scorable=spec.is_scorable,
        unscorable_reason=unscorable_reason(spec),
        results=results,
        has_results=bool(results),
        best_model_key=best,
    )


def build_leaderboard(
    session: Session,
    *,
    specs: list[TaskSpec],
    registry_by_key: dict[str, ModelEntry],
) -> LeaderboardResponse:
    """Aggregate the newest finished run per (task, model) into the results view.

    One database round trip for every task on the page: the per-pair reduction
    happens in SQL (see :func:`latest_terminal_run_per_pair`), not in a loop of
    queries per task.
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

    facet_values: dict[str, list[str]] = {}
    for board in boards:
        for field, values in board.facets.items():
            bucket = facet_values.setdefault(field, [])
            for value in values:
                if value not in bucket:
                    bucket.append(value)
    for bucket in facet_values.values():
        bucket.sort()

    return LeaderboardResponse(
        tasks=boards,
        task_count=len(boards),
        measured_task_count=sum(1 for b in boards if b.has_results),
        runs_considered=len(rows),
        has_any_results=any(b.has_results for b in boards),
        facet_values=facet_values,
        families=sorted({b.family for b in boards}),
        domains=sorted({b.domain for b in boards}),
    )
