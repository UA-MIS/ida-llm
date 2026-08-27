"""Scheduled sweeps -- the CronJob entry points.

All three CronJobs run THIS module from the same image the runner uses, choosing
behaviour by argv (`ida-sweep <name>`). One image, three schedules.

⚠ EVERY SWEEP MUST BE IDEMPOTENT AND MUST EXIT NON-ZERO ON FAILURE. A CronJob
that exits 0 after failing looks successful forever, and nobody notices a nightly
job silently doing nothing until the numbers are needed.

A SWEEP ENQUEUES; RUNNERS EXECUTE
---------------------------------
Nothing here talks to a provider. A sweep plans a set of ``(task, model)`` pairs,
writes ``queued`` run rows and pushes queue messages -- exactly what ``POST
/runs`` does, and deliberately through the same contracts, so a scheduled run and
a hand-launched one are indistinguishable downstream. The per-run token budget,
retries and archival all stay where they already are, in the runner.

That split is why a sweep pod can finish in seconds while the work it scheduled
takes hours, and why ``activeDeadlineSeconds: 21600`` on the CronJob is a
backstop against a hung *plan*, not a limit on the benchmark.

THE THREE NAMES ARE FIXED BY THE CHART
--------------------------------------
``.devops/chart/base/cronjobs.yaml`` hardcodes ``command: ["ida-sweep", "..."]``
for ``rebenchmark``, ``model-sweep`` and ``judge-calibration``. Renaming a sweep
here without the chart -- which this story does not own -- would leave three
CronJobs firing an argv that argparse rejects, i.e. a nightly job that fails
every night with a usage message. Add names, never rename them.

WHAT AN OPERATOR SEES
---------------------
CronJob logs are the operator surface, so every sweep ends with ONE summary line
carrying considered / enqueued / skipped counts. A sweep that enqueues nothing
because everything is already measured is a normal, quiet success -- that is the
steady state of a healthy nightly, not a fault.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from ida_core.artifacts import ArtifactStore, LocalArtifactStore, S3ArtifactStore
from ida_core.config import Settings, get_settings
from ida_core.contracts import (
    ModelRegistry,
    RunJobMessage,
    RunRecord,
    RunStatus,
    TaskKind,
)
from ida_core.db import make_engine, make_session_factory, session_scope, utcnow
from ida_core.gitmeta import build_identity, current_git_sha
from ida_core.ids import new_id, new_run_id
from ida_core.queue import RedisQueue, RunQueue
from ida_core.registry import load_registry
from ida_core.repositories import (
    create_run,
    existing_run_keys,
    fail_run,
    list_ungraded_subjective_results,
    models_with_any_run,
    persist_regraded_results,
)
from ida_harness.regrade import regrade_run
from ida_harness.runner import unscorable_reason
from ida_harness.tasks import TaskCatalog
from ida_runner.judging import build_judge_from_settings

log = logging.getLogger("ida.sweep")

SWEEPS = {
    "rebenchmark": "Re-run the full suite against every enabled model.",
    "model-sweep": "Enqueue the suite for enabled models that have never been measured.",
    "judge-calibration": "Refresh judge scores for subjective samples that carry none.",
}

MEASURED_STATUSES: tuple[RunStatus, ...] = (RunStatus.SUCCEEDED,)
"""Statuses that mean "this pair has a real measurement; do not re-run it".

``succeeded`` ONLY. ``partial`` and ``failed`` are deliberately excluded: a run
where some or all samples errored is not a measurement of the model, it is a
record of an outage, and leaving it in the dedupe index would mean one bad night
permanently suppresses the pair. Excluding them is what makes the nightly
self-healing -- a pair whose only runs errored is retried tonight.

Read the rule precisely: it is "this triple has NO succeeded run", not "this
triple's LAST run failed". A pair that succeeded on Monday and failed on Tuesday
is still skipped, because a valid measurement of that exact task version exists
and re-buying it would spend credits to learn nothing. Recency is deliberately
not part of the key -- ``task_content_sha`` is what expires a measurement here,
not the clock.
"""

IN_FLIGHT_STATUSES: tuple[RunStatus, ...] = (RunStatus.QUEUED, RunStatus.RUNNING)
"""Statuses that mean "somebody is already paying for this pair".

Not a measurement, but skipping them is still correct, and this is NOT redundant
with the CronJobs' ``concurrencyPolicy: Forbid``. Forbid stops a sweep stacking
on ITSELF; it says nothing about ``rebenchmark`` (02:00) and ``model-sweep``
(03:30) overlapping, and a run is allowed six hours. Without this, the 03:30
firing would re-enqueue pairs the 02:00 firing has queued but not yet finished,
and every one of those duplicates is a real provider charge for a number we
already commissioned.

⚠ TIME-BOUNDED, AND THAT BOUND IS NOT OPTIONAL. A ``queued`` row only means "in
flight" while a message for it really is on the queue. If the sweep died between
committing rows and pushing messages -- an evicted pod, a SIGKILL -- the rows
survive and the messages do not, and an UNBOUNDED read of this set would then
skip those pairs every night forever while exiting 0. The sweep asks only about
rows younger than ``stale_run_ttl_s``, the same horizon the reaper uses to decide
a run is not coming back; anything older is treated as abandoned and re-planned.
"""


# --------------------------------------------------------------- planning ----


@dataclass(frozen=True)
class Candidate:
    """One ``(task, model)`` pair a sweep proposes to enqueue."""

    task_id: str
    model_key: str
    content_sha: str | None
    sample_count: int

    @property
    def dedupe_key(self) -> tuple[str, str, str | None]:
        return (self.task_id, self.model_key, self.content_sha)


@dataclass
class SweepReport:
    """The counters behind the one summary line each sweep emits.

    Every candidate is accounted for in exactly one bucket, so
    ``considered == enqueued + planned + skipped_dedupe + skipped_budget +
    skipped_unavailable + failed`` holds -- which is what makes the summary line
    checkable rather than decorative. :meth:`balances` states it, and the tests
    check it on every sweep rather than trusting the arithmetic by eye. A count
    that balances is how a reader knows nothing was quietly dropped between
    planning and enqueueing.
    """

    sweep: str
    considered: int = 0
    enqueued: int = 0
    planned: int = 0
    """Candidates a ``--dry-run`` would have enqueued.

    Its own bucket so the invariant above stays TOTAL rather than carrying a
    "except in dry-run" caveat. An invariant with an exception is one nobody
    checks -- and a dry run that reported ``enqueued=0`` with no other bucket
    accounting for the work would look identical to a sweep that silently lost
    its whole plan."""
    skipped_dedupe: int = 0
    skipped_budget: int = 0
    skipped_unavailable: int = 0
    """Candidates skipped because the thing that would process them is not built
    yet.  Its own bucket rather than borrowed space in ``skipped_dedupe``: "we
    already have this number" and "nothing here can produce this number" are
    opposite states, and an operator reading the summary line has to be able to
    tell them apart."""
    graded: int = 0
    """Candidates that now carry a judge score they did not have before.

    ``judge-calibration``'s equivalent of ``enqueued``, and its own bucket
    rather than a reuse of that one: this sweep pushes nothing onto the queue,
    and an operator reading ``enqueued=7`` from a sweep that enqueues nothing
    would reasonably conclude seven runs were about to happen."""

    failed: int = 0
    samples_enqueued: int = 0
    judge_cost_usd: float = 0.0
    """What tonight's grading actually cost, at the judge's rates.

    On the summary line because a sweep that spends money on every firing is the
    one an operator most needs a running number for -- and because the retry
    bound this sweep enforces is a cost control, so its effect has to be visible
    in the same place."""

    notes: list[str] = field(default_factory=list)
    sweep_id: str | None = None

    def summary(self) -> str:
        parts = [
            f"sweep={self.sweep}",
            f"considered={self.considered}",
            f"enqueued={self.enqueued}",
            f"skipped_dedupe={self.skipped_dedupe}",
            f"skipped_budget={self.skipped_budget}",
            f"skipped_unavailable={self.skipped_unavailable}",
            f"failed={self.failed}",
            f"samples={self.samples_enqueued}",
        ]
        if self.graded:
            parts.append(f"graded={self.graded}")
        if self.judge_cost_usd:
            parts.append(f"judge_cost_usd={self.judge_cost_usd:.6f}")
        if self.planned:
            parts.append(f"planned={self.planned}")
        if self.sweep_id:
            parts.append(f"sweep_id={self.sweep_id}")
        if self.notes:
            parts.append("notes=" + "; ".join(self.notes))
        return " ".join(parts)

    def balances(self) -> bool:
        """Does every considered candidate land in exactly one bucket?"""
        return self.considered == (
            self.enqueued
            + self.graded
            + self.planned
            + self.skipped_dedupe
            + self.skipped_budget
            + self.skipped_unavailable
            + self.failed
        )

    @property
    def exit_code(self) -> int:
        """Non-zero when the sweep did not do what it set out to do.

        ``skipped_budget`` and ``failed`` are the two honest failures: the first
        means the sweep refused its own plan, the second that some of it did not
        land. Both must reach the CronJob's failure count rather than scroll past
        in a log nobody reads.
        """
        return 1 if (self.skipped_budget or self.failed) else 0


def scorable_tasks(catalog: TaskCatalog) -> list:
    """Tasks a sweep can enqueue, in stable id order.

    Subjective tasks are excluded: enqueueing them would spend provider credits
    producing completions that land as ``scorable=False`` rows, and the platform
    would then show a benchmark suite whose subjective half is permanently blank.

    ⚠ THIS ASKS THE JUDGE-FREE QUESTION ON PURPOSE, AND IT IS NOW A CHOICE
    RATHER THAN A CONSEQUENCE. :func:`~ida_harness.runner.unscorable_reason`
    takes ``judge_configured``, and this call leaves it at its conservative
    default, so subjective tasks stay out of ``rebenchmark`` and ``model-sweep``
    **even on a deployment that has configured a judge** -- despite those tasks
    now being fully gradable by the live path.

    That is deliberate, because flipping it is a spending decision, not a wiring
    one: it would add every subjective task to the nightly cross product at one
    candidate call *plus one judge call per criterion per sample*, unattended.
    The backlog is not stranded in the meantime -- ``judge-calibration`` grades
    subjective samples retroactively, so the numbers arrive either way. Whoever
    decides the nightly should also *produce* subjective runs passes
    ``judge_configured=bool(settings.judge_model_key)`` here and re-checks the
    budget caps against the new sample count.
    """
    return [spec for spec in catalog.all() if unscorable_reason(spec) is None]


def plan_candidates(
    *,
    catalog: TaskCatalog,
    model_keys: Sequence[str],
    tasks: Sequence | None = None,
) -> list[Candidate]:
    """Cross product of ``tasks`` x ``model_keys``, ordered deterministically.

    Ordering is task-major and sorted, so two runs of the same sweep against the
    same inputs propose the same list in the same order. That is what makes a
    dry-run's log a truthful preview of the real firing.
    """
    specs = list(tasks) if tasks is not None else scorable_tasks(catalog)
    return [
        Candidate(
            task_id=spec.id,
            model_key=model_key,
            content_sha=spec.content_sha or None,
            sample_count=len(spec.samples),
        )
        for spec in specs
        for model_key in sorted(model_keys)
    ]


def apply_dedupe(
    candidates: Sequence[Candidate],
    *,
    seen: set[tuple[str, str, str | None]],
    force: bool,
    report: SweepReport,
) -> list[Candidate]:
    """Drop candidates whose triple is already measured or already in flight.

    ``force`` bypasses the index entirely -- the deliberate re-measurement
    switch. It does NOT bypass the budget guard downstream; see
    :func:`enforce_budget`.
    """
    if force:
        report.notes.append("force=on (dedupe bypassed)")
        return list(candidates)
    kept = []
    for candidate in candidates:
        if candidate.dedupe_key in seen:
            report.skipped_dedupe += 1
        else:
            kept.append(candidate)
    return kept


# ----------------------------------------------------------- budget guard ----


class BudgetExceeded(Exception):
    """A sweep's plan is larger than its configured cap.  Raised, never swallowed."""


def enforce_budget(candidates: Sequence[Candidate], settings: Settings) -> None:
    """Refuse a plan that exceeds ``IDA_SWEEP_MAX_RUNS`` or ``IDA_SWEEP_MAX_SAMPLES``.

    REFUSE-AND-REPORT, NOT CAP-AND-PROCEED. The sweep enqueues **nothing** and
    exits non-zero. Four reasons, in the order they mattered:

    1. *A capped sweep is a partial suite reported as a whole one.* Truncating to
       the first N pairs enqueues an ordering-dependent subset. The dashboard
       then shows a "nightly benchmark" that silently omits whatever sorted last,
       with nothing marking it incomplete. This platform's entire premise is not
       making that kind of false statement.
    2. *Exit 0 hides the cap.* Cap-and-proceed succeeds every night while quietly
       never finishing the suite. The operator learns the cap is too low only
       when someone asks why a model has no numbers. Refusing puts it in the
       CronJob's failure count, which is a surface people actually watch.
    3. *The costs are asymmetric.* Refusing costs one delayed night, and the fix
       -- raise the cap, or run with force off -- is one env var and fully
       recoverable. Cap-and-proceed spends real provider credits on a subset
       nobody chose, and money is not refundable by editing a ConfigMap.
    4. *It matches the precedent next door.* ``POST /runs`` validates the entire
       cross product before writing anything, so "a typo never leaves half a
       sweep running". A sweep that half-runs on a budget trip would contradict
       the API it shares its contracts with.

    ``backoffLimit: 1`` makes this exactly as loud as intended: one retry, then a
    failed Job that stays visible in the CronJob's history.

    The message NAMES the variable to raise, following
    :class:`ida_core.registry.MissingBaseUrlError` -- the point of a knob nobody
    can find is lost.
    """
    runs = len(candidates)
    samples = sum(c.sample_count for c in candidates)
    if runs > settings.sweep_max_runs:
        raise BudgetExceeded(
            f"plan of {runs} run(s) exceeds IDA_SWEEP_MAX_RUNS={settings.sweep_max_runs}; "
            f"enqueued nothing. Raise the cap deliberately, or narrow the sweep."
        )
    if samples > settings.sweep_max_samples:
        raise BudgetExceeded(
            f"plan of {samples} sample(s) across {runs} run(s) exceeds "
            f"IDA_SWEEP_MAX_SAMPLES={settings.sweep_max_samples}; enqueued nothing. "
            f"One sample is one provider call, so this is the spend estimate that matters."
        )


# --------------------------------------------------------------- enqueue -----


def enqueue_candidates(
    candidates: Sequence[Candidate],
    *,
    queue: RunQueue,
    session_factory,
    git_sha: str | None,
    report: SweepReport,
    label: str,
) -> None:
    """Write ``queued`` rows, then push queue messages.  Counts what landed.

    ROWS FIRST, MESSAGES SECOND -- the same ordering, for the same reason, as
    ``POST /runs``: a crash between the two leaves a ``queued`` row no runner
    picks up, which is visible and re-drivable. The other order hands a runner a
    message for a row that does not exist.

    A push that fails partway is REPORTED, not hidden: the summary line says how
    many actually landed and the exit code is non-zero. Claiming a whole sweep
    when half of it never reached Redis is precisely the silent-success failure
    the module docstring exists to forbid.

    ⚠ AND THE UN-PUSHED ROWS ARE CLOSED OUT ``failed``, NOT LEFT ``queued``.
    This is the one place this module deliberately diverges from ``POST /runs``,
    and the divergence is forced by dedupe. The API leaves un-pushed rows
    ``queued`` because a human sees them and re-drives them. A sweep has no
    human: it reads its own ``queued`` rows back as "in flight" on the next
    firing and skips those pairs -- so leaving them would convert the API's
    "visible and re-drivable" into "permanently invisible", and every subsequent
    night would exit 0 having measured nothing. Verified before this line
    existed: after one mid-sweep Redis blip, six pairs were skipped every night
    thereafter, with a green CronJob.

    A row saying ``queued`` when no message exists is also simply FALSE, which is
    reason enough. ``failed`` carries the real reason, is excluded from
    :data:`MEASURED_STATUSES`, and is therefore retried tomorrow.

    Safe against the ambiguous case where the push actually landed and only the
    acknowledgement was lost: delivery is at-least-once, so the runner claims the
    message, flips the row back to ``running`` and finishes it normally, and
    :func:`ida_core.repositories.fail_run` refuses to overwrite a terminal row.
    """
    if not candidates:
        return

    now = utcnow()
    # ONE sweep id for the whole firing (B9), same as the API mints per request.
    # Without it, "show me what last night's rebenchmark did" is a timestamp
    # range guess rather than a filter the API already supports.
    sweep_id = new_id("swp")
    # ⚠ RESOLVED ONCE PER FIRING, NOT PER CANDIDATE. With IDA_GIT_SHA unset
    # `build_identity()` shells out to `git`, and a rebenchmark plans hundreds of
    # candidates -- so calling it inside the loop below would fork a subprocess
    # per row for a value that cannot change mid-sweep. Same rule `ctx.git_sha`
    # already follows (resolved once in `build_context`) and the same rule
    # `ida_api.app.HARNESS_VERSION` follows. Deliberately a LOCAL and not a module
    # constant: the sweep must read the environment as it is when it FIRES, which
    # is also what keeps it honest under a test that changes directory.
    harness_version = build_identity()
    report.sweep_id = sweep_id

    records: list[RunRecord] = []
    messages: list[RunJobMessage] = []
    for candidate in candidates:
        run_id = new_run_id()
        records.append(
            RunRecord(
                id=run_id,
                status=RunStatus.QUEUED,
                task_id=candidate.task_id,
                model_key=candidate.model_key,
                label=label,
                sweep_id=sweep_id,
                task_git_sha=git_sha,
                task_content_sha=candidate.content_sha,
                harness_version=harness_version,
                sample_count=candidate.sample_count,
                created_at=now,
            )
        )
        messages.append(
            RunJobMessage(
                run_id=run_id,
                task_id=candidate.task_id,
                model_key=candidate.model_key,
                sweep_id=sweep_id,
                enqueued_at=now,
            )
        )

    with session_scope(session_factory) as session:
        for record in records:
            create_run(session, record)

    for index, message in enumerate(messages):
        try:
            queue.enqueue(message)
        except Exception:
            remaining = len(messages) - index
            log.exception(
                "sweep %s: queue push failed for run %s; %d of %d landed, closing out "
                "the remaining %d as failed so tomorrow's sweep re-plans them",
                sweep_id,
                message.run_id,
                report.enqueued,
                len(messages),
                remaining,
            )
            report.failed += remaining
            _close_out_unpushed(
                session_factory,
                [m.run_id for m in messages[index:]],
                sweep_id=sweep_id,
            )
            return
        report.enqueued += 1
        report.samples_enqueued += candidates[index].sample_count


def _close_out_unpushed(session_factory, run_ids: list[str], *, sweep_id: str) -> None:
    """Mark runs whose queue message never landed as ``failed``.

    Best-effort by design. If the database is unreachable too -- the likeliest
    reason the queue was -- the sweep has already counted these as ``failed`` and
    will still exit non-zero, so the operator is told the truth either way. What
    must not happen is this raising and replacing a precise "N of M landed"
    report with a traceback about the cleanup.
    """
    reason = (
        f"sweep {sweep_id}: enqueue failed -- no queue message was ever pushed for this run, "
        f"so no runner will claim it"
    )
    try:
        with session_scope(session_factory) as session:
            for run_id in run_ids:
                fail_run(session, run_id, reason)
    except Exception:
        log.exception(
            "sweep %s: could not close out %d un-pushed run(s); they stay `queued` and "
            "will be re-planned once older than stale_run_ttl_s",
            sweep_id,
            len(run_ids),
        )


# ---------------------------------------------------------------- context ----


@dataclass
class SweepContext:
    """Everything a sweep needs, assembled once.

    Mirrors ``ida_api.deps.AppContext`` rather than reaching for globals, which
    is what lets the tests drive the real sweep bodies with an in-memory queue
    and a SQLite session factory -- the same code path production runs.
    """

    settings: Settings
    session_factory: object
    queue: RunQueue
    registry: ModelRegistry
    catalog: TaskCatalog
    git_sha: str | None
    artifact_store: ArtifactStore | None = None
    """Present only for the sweep that needs it -- today, none of them.

    Retroactive grading reads archived transcripts out of object storage, so
    ``judge-calibration`` will need this the moment a grader exists. It stays
    OPTIONAL, and ``build_context`` builds it only on request, because
    ``rebenchmark`` and ``model-sweep`` touch no blobs: giving them one would
    make the nightly benchmark fail on a MinIO outage that cannot affect it."""


def build_artifact_store(settings: Settings) -> ArtifactStore:
    """MinIO/S3 or a local directory, per ``IDA_ARTIFACT_BACKEND``.

    Mirrors ``ida_runner.main.build_worker`` rather than importing the API's
    copy: the runner does not depend on ``ida_api``, and a sweep is a runner.
    """
    if settings.artifact_backend == "local":
        return LocalArtifactStore(settings.artifact_local_root, bucket=settings.s3_bucket)
    return S3ArtifactStore.from_settings(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
    )


def build_context(
    settings: Settings | None = None, *, need_artifacts: bool = False
) -> SweepContext:
    """Assemble the production context from environment settings.

    ``need_artifacts`` is opt-in per sweep rather than always-on. Only a sweep
    that reads archived transcripts needs object storage, and building a client
    a sweep will not use turns an unrelated MinIO outage into a failed nightly
    benchmark.
    """
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    return SweepContext(
        artifact_store=build_artifact_store(settings) if need_artifacts else None,
        settings=settings,
        session_factory=make_session_factory(engine),
        queue=RedisQueue.from_url(settings.redis_url),
        registry=load_registry(settings.resolved_models_file()),
        catalog=TaskCatalog.from_directory(settings.resolved_tasks_dir()),
        git_sha=current_git_sha(settings.resolved_tasks_dir()),
    )


# ------------------------------------------------------------ the sweeps ----


def _enqueueing_sweep(
    ctx: SweepContext,
    *,
    name: str,
    model_keys: Sequence[str],
    report: SweepReport,
    dry_run: bool,
    dedupe_model_scope: Sequence[str] | None,
) -> SweepReport:
    """Shared body of the two enqueueing sweeps.

    ``rebenchmark`` and ``model-sweep`` differ ONLY in which models they consider
    -- everything after that (cross product, dedupe, budget, enqueue, summary) is
    identical, and keeping it identical is the point: two copies would drift, and
    the one that drifted would be the one spending money.
    """
    candidates = plan_candidates(catalog=ctx.catalog, model_keys=model_keys)
    report.considered = len(candidates)

    if not candidates:
        # Not a fault. An empty registry, a registry with nothing enabled, or a
        # catalog with no scorable task all land here, and all three are states
        # an operator may have chosen deliberately.
        report.notes.append("nothing to consider")
        return report

    # TWO queries, not one, because the two halves of the index expire
    # differently. A measurement is timeless -- it stays valid until the task's
    # content sha changes. "In flight" is a claim about RIGHT NOW, and a row old
    # enough that the reaper would have given up on it is not in flight, it is
    # abandoned; reading it as in-flight would skip the pair forever.
    in_flight_cutoff = utcnow() - timedelta(seconds=ctx.settings.stale_run_ttl_s)
    with session_scope(ctx.session_factory) as session:
        seen = existing_run_keys(
            session,
            statuses=MEASURED_STATUSES,
            model_keys=dedupe_model_scope,
        ) | existing_run_keys(
            session,
            statuses=IN_FLIGHT_STATUSES,
            model_keys=dedupe_model_scope,
            created_after=in_flight_cutoff,
        )
    candidates = apply_dedupe(candidates, seen=seen, force=ctx.settings.sweep_force, report=report)

    if not candidates:
        report.notes.append("everything already measured or in flight")
        return report

    try:
        enforce_budget(candidates, ctx.settings)
    except BudgetExceeded as exc:
        # LOUD, and the count goes to skipped_budget so the summary line still
        # balances against `considered`.
        log.error("sweep=%s REFUSED: %s", name, exc)
        report.skipped_budget = len(candidates)
        return report

    if dry_run:
        report.planned = len(candidates)
        report.notes.append(f"dry-run: would enqueue {len(candidates)} run(s)")
        for candidate in candidates:
            log.info(
                "dry-run would enqueue task=%s model=%s samples=%d",
                candidate.task_id,
                candidate.model_key,
                candidate.sample_count,
            )
        return report

    enqueue_candidates(
        candidates,
        queue=ctx.queue,
        session_factory=ctx.session_factory,
        git_sha=ctx.git_sha,
        report=report,
        label=f"sweep:{name}",
    )
    return report


def run_rebenchmark(ctx: SweepContext, *, dry_run: bool = False) -> SweepReport:
    """Nightly: every enabled model x every scorable task, minus what is measured.

    The broad sweep. Dedupe on ``(task, model, task_content_sha)`` is what keeps
    a nightly full-suite job cheap in the steady state: on an unchanged repo with
    everything measured it enqueues zero runs and exits quietly. It re-enqueues
    exactly three things -- a newly enabled model, a task whose content changed,
    and a pair with no succeeded run at the current content sha (so a pair that
    has only ever failed, never one that succeeded and later failed).
    """
    report = SweepReport(sweep="rebenchmark")
    return _enqueueing_sweep(
        ctx,
        name="rebenchmark",
        model_keys=ctx.registry.enabled_keys(),
        report=report,
        dry_run=dry_run,
        dedupe_model_scope=None,
    )


def run_model_sweep(ctx: SweepContext, *, dry_run: bool = False) -> SweepReport:
    """Registry diff: enqueue the suite only for models never measured at all.

    The cheap, targeted counterpart to ``rebenchmark``. A model with no
    ``succeeded`` run against anything is new -- somebody just enabled it -- and
    getting a first set of numbers for it should not wait on, or be entangled
    with, a full-suite pass.

    ``rebenchmark`` (02:00) covers this too, so on most nights the 03:30 firing
    finds the new model's runs already queued and enqueues nothing. That overlap
    is intended: the two sweeps are independently correct, and the cheap one
    exists so a model enabled at 09:00 is not invisible until the next 02:00.
    """
    report = SweepReport(sweep="model-sweep")
    enabled = ctx.registry.enabled_keys()
    with session_scope(ctx.session_factory) as session:
        measured = models_with_any_run(session, statuses=MEASURED_STATUSES)
    fresh = [key for key in enabled if key not in measured]
    if not fresh:
        report.notes.append(f"no new models among {len(enabled)} enabled")
        return report
    log.info("sweep=model-sweep new models: %s", ", ".join(sorted(fresh)))
    return _enqueueing_sweep(
        ctx,
        name="model-sweep",
        model_keys=fresh,
        report=report,
        dry_run=dry_run,
        # Scope the dedupe query to the new models. Correct AND cheaper: these
        # models have no measured runs by construction, so the only rows that can
        # match are ones an earlier sweep tonight left in flight -- which is
        # exactly what must still be caught.
        dedupe_model_scope=fresh,
    )


# ── judge calibration ────────────────────────────────────────────────────────
#
# THE RETROACTIVE HALF OF GRADING. Its live counterpart is
# `IDA_JUDGE_MODEL_KEY` -> `ida_runner.main.build_worker` -> `Worker` ->
# `run_task(judge=...)`, which grades a subjective sample while its run is
# happening. The two exist together and must agree, because they write the same
# columns: this sweep picks up what the live path could not grade -- samples
# that ran before a judge was configured, and samples whose online grading
# failed -- and its candidate query is the SQL image of the four-way partition
# in `docs/llm-judge.md`.
#
# ⚠ THIS SWEEP SPENDS MONEY ON EVERY FIRING, WHICH IS WHY IT IS BOUNDED TWICE.
# `IDA_SWEEP_JUDGE_CANDIDATE_LIMIT` bounds one pass; `IDA_SWEEP_JUDGE_MAX_ATTEMPTS`
# bounds a sample's lifetime. Only the second one terminates: without it a judge
# that stays down is re-asked about the same failed samples every night forever,
# and the only symptom is the invoice.


def _judgeable(catalog: TaskCatalog, task_id: str) -> bool:
    """Can a judge produce a grade for this task at all?

    The nomination query cannot answer this. ``results`` stores ``task_id``, not
    task *kind*, so no SQL predicate can distinguish a subjective sample from a
    verifiable one whose score is missing for some other reason -- and a task
    that has been deleted or had its rubric removed since the run is not visible
    to SQL at all. Filtering here, against the live catalog, is what keeps the
    sweep from handing the grader work it will only decline.

    An unknown task is not judgeable: the rubric is gone, so there is nothing to
    grade against. That is a real state -- a task deleted after its runs -- and
    it must not raise.
    """
    try:
        spec = catalog.get(task_id)
    except KeyError:
        return False
    return spec.kind is TaskKind.SUBJECTIVE and spec.rubric is not None


def run_judge_calibration(ctx: SweepContext, *, dry_run: bool = False) -> SweepReport:
    """Grade subjective samples that carry no score, retroactively.

    Candidates come from :func:`~ida_core.repositories.list_ungraded_subjective_results`,
    which selects the two gradable classes of the ``docs/llm-judge.md``
    partition -- *never judged* and the still-affordable part of *judge failed* --
    and excludes the two that are not: *graded* (done) and *ungradable* (the
    model call died, so no completion exists and no judge can ever succeed).

    Each nominated result is graded from its **archived completion**. The model
    under test is never called again: re-answering the prompt would produce a
    grade of a different run that happens to share a run id.

    WHY THIS CALLS A PER-RUN FUNCTION WITH A PER-RESULT FILTER
    ---------------------------------------------------------
    :func:`ida_harness.regrade.regrade_run` reads one run's archived eval log,
    so grading is batched by run. But the bound this sweep enforces is
    per-*result*: within one run, some samples are freshly nominated and others
    have already exhausted ``judge_attempts``. Calling ``regrade_run`` bare would
    silently re-grade the exhausted ones -- the per-run call widening the
    per-result bound back open, and re-billing exactly the samples the bound
    exists to stop. ``only_result_ids`` is what keeps the two honest.

    WHAT IT WRITES, AND WHY THE WRITE-BACK IS HERE
    ----------------------------------------------
    ``regrade_run`` archives to object storage and hands back records "ready to
    persist"; it has no database, because the harness deliberately has no
    database. The service that owns ``results`` does the write, and this is that
    service. Until it did, a regrade updated the eval log while the UI kept
    showing the original blank -- and, more sharply, ``judge_attempts`` never
    moved, so the bound could never engage.

    EXIT CODE
    ---------
    A judge that fails on a sample makes this sweep exit non-zero. That is a
    change in kind from the state it replaces, and it is deliberate: "no judge is
    built yet" was a gap no operator action could clear, so failing on it would
    have painted a permanent red mark and taught everyone to ignore the alarm.
    A judge that is configured and failing is the opposite -- someone can fix it,
    and the retry bound means it will stop being retried if nobody does.

    ``dry_run`` reports what would change **and still calls the judge, and is
    still billed for it**. It answers "what would this change", not "what would
    this cost". It does not count an attempt, so a dry run does not move a sample
    toward its bound.
    """
    report = SweepReport(sweep="judge-calibration")
    settings = ctx.settings
    limit = settings.sweep_judge_candidate_limit
    max_attempts = settings.sweep_judge_max_attempts

    with session_scope(ctx.session_factory) as session:
        # limit + 1: fetching exactly `limit` cannot distinguish "the backlog is
        # exactly this long" from "there is more", and claiming more candidates
        # remain when none do is a false statement on the operator's only
        # surface. One extra row answers it for certain; it is then dropped.
        rows = list_ungraded_subjective_results(
            session, limit=limit + 1, max_judge_attempts=max_attempts
        )
        truncated = len(rows) > limit
        rows = rows[:limit]
        # Read every attribute inside the session: the rows are detached on exit
        # and touching a lazy attribute afterwards raises.
        nominated = [(row.id, row.run_id, row.task_id) for row in rows]

    candidates = [
        (rid, run_id) for rid, run_id, task_id in nominated if _judgeable(ctx.catalog, task_id)
    ]
    not_judgeable = len(nominated) - len(candidates)
    report.considered = len(candidates)

    if truncated:
        # A bounded pass that looks complete is the failure this note prevents.
        report.notes.append(f"hit IDA_SWEEP_JUDGE_CANDIDATE_LIMIT={limit}; more candidates remain")
    if not_judgeable:
        # Kept OUT of `considered` rather than parked in a skip bucket: these
        # rows are not candidates this sweep declined, they are rows the SQL
        # predicate cannot exclude on its own (no task kind in `results`). They
        # would otherwise inflate the backlog figure every night forever.
        report.notes.append(
            f"{not_judgeable} nominated row(s) belong to tasks that are not subjective "
            "or have no rubric; not judgeable"
        )

    if not candidates:
        return report

    if ctx.artifact_store is None:
        # Regrading reads archived transcripts. A context built without object
        # storage cannot grade anything, and saying so beats an AttributeError
        # at 02:00. `judge-calibration` is in NEEDS_ARTIFACTS precisely so this
        # is unreachable in production.
        log.warning("no artifact store on this context -- skipped %d candidate(s)", len(candidates))
        report.skipped_unavailable = len(candidates)
        report.notes.append("no artifact store configured")
        return report

    judge = build_judge_from_settings(settings, ctx.registry)
    if judge is None:
        # Still exit 0. "The operator has not chosen to pay for a judge" is a
        # configuration state, not tonight's failure, and the backlog is logged
        # so it stays visible while it waits.
        log.warning(
            "no judge configured (IDA_JUDGE_MODEL_KEY is unset) -- skipped %d candidate(s) "
            "across %d run(s)",
            len(candidates),
            len({run_id for _rid, run_id in candidates}),
        )
        report.skipped_unavailable = len(candidates)
        report.notes.append("no judge configured")
        return report

    by_run: dict[str, list[str]] = defaultdict(list)
    for result_id, run_id in candidates:
        by_run[run_id].append(result_id)

    with judge:
        # sorted() so a firing is reproducible and its log is diffable against
        # the previous one; dict order here would follow row order, which is
        # stable in practice and not guaranteed.
        for run_id, result_ids in sorted(by_run.items()):
            _grade_one_run(
                ctx,
                report,
                judge=judge,
                run_id=run_id,
                result_ids=result_ids,
                dry_run=dry_run,
            )

    if dry_run:
        report.notes.append(
            f"dry-run: nothing written, but the judge WAS called and billed "
            f"(${report.judge_cost_usd:.6f})"
        )
    return report


def _grade_one_run(
    ctx: SweepContext,
    report: SweepReport,
    *,
    judge,
    run_id: str,
    result_ids: list[str],
    dry_run: bool,
) -> None:
    """Grade one run's nominated results and fold the outcome into ``report``.

    Every nominated result lands in exactly one bucket, computed as
    ``skipped = nominated - graded - failed`` rather than by counting
    ``regrade_run``'s own skip list. That list also contains the run's
    *non-nominated* results (``regrade_run`` reports them as skipped so its
    report accounts for the whole run), and counting it directly would
    double-count them into this sweep's totals.

    ⚠ ONE RUN'S FAILURE MUST NOT END THE PASS. A sweep that dies on the first
    unreadable eval log leaves every later run ungraded, and tomorrow it dies on
    the same one -- so a whole backlog is held hostage by a single bad row.
    """
    nominated = len(result_ids)
    try:
        regrade_report = regrade_run(
            run_id=run_id,
            store=ctx.artifact_store,
            judge=judge,
            catalog=ctx.catalog,
            only_result_ids=set(result_ids),
            dry_run=dry_run,
        )
    except KeyError:
        # No archived eval log for this run. Nothing failed tonight that fixing
        # the judge would fix, so this is `unavailable`, not `failed`.
        #
        # ⚠ AND IT WILL BE RE-NOMINATED TOMORROW, FOREVER. `judge_attempts` only
        # moves when a judge is actually asked, and none was, so the bound never
        # engages on these rows. That is bounded in MONEY (no judge call is made)
        # and unbounded in NOISE. Stated rather than hidden: the fix is to make
        # eval-log archival failures visible on the run, which is not this
        # change's to make.
        log.warning(
            "run %s has no archived eval log; %d candidate(s) cannot be graded "
            "and will be re-nominated",
            run_id,
            nominated,
        )
        report.skipped_unavailable += nominated
        return
    except Exception:
        log.exception("run %s: regrade failed", run_id)
        report.failed += nominated
        return

    report.judge_cost_usd += regrade_report.judge_cost_usd

    if dry_run:
        report.planned += nominated
        return

    graded = len(regrade_report.graded)
    failed = len(regrade_report.failed)
    report.graded += graded
    report.failed += failed
    report.skipped_unavailable += nominated - graded - failed

    # PERSIST ONLY WHAT WAS NOMINATED. The eval log holds every result in the
    # run; the ones this sweep did not nominate were not touched, and writing
    # them back would restate untouched rows from a record that merely carried
    # them along.
    wanted = set(result_ids)
    touched = [r for r in regrade_report.eval_log.results if r.id in wanted]
    try:
        with session_scope(ctx.session_factory) as session:
            persist_regraded_results(session, touched)
    except Exception:
        # The grades ARE archived (regrade_run wrote the eval log); only the
        # database copy is missing. Counted as failed so the CronJob goes red:
        # a silent divergence between object storage and Postgres is exactly the
        # state nobody discovers until the numbers are needed.
        log.exception("run %s: could not persist %d regraded result(s)", run_id, len(touched))
        # MOVE the graded ones from `graded` to `failed` -- do not ADD them to
        # `failed` while leaving them in `graded`, which would count them twice
        # and break `balances()`. The already-failed ones are NOT moved: they are
        # in `failed` already, and adding them again is the same double count.
        report.graded -= graded
        report.failed += graded
        report.notes.append(f"run {run_id}: grades archived but not persisted")


NEEDS_ARTIFACTS = frozenset({"judge-calibration"})
"""Sweeps that read archived transcripts and therefore need object storage.

Kept as data next to :data:`HANDLERS` so adding a sweep is one table edit, and so
the two enqueueing sweeps stay provably independent of MinIO."""

HANDLERS = {
    "rebenchmark": run_rebenchmark,
    "model-sweep": run_model_sweep,
    "judge-calibration": run_judge_calibration,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scheduled benchmark sweeps.")
    parser.add_argument("sweep", choices=sorted(SWEEPS), help="which sweep to run")
    parser.add_argument("--dry-run", action="store_true", help="log the plan, change nothing")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-enqueue pairs that are already measured (budget caps still apply); "
        "IDA_SWEEP_FORCE=1 does the same for the CronJobs, whose argv is fixed",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if args.force:
        # CLI wins over the env, and never the other way round: a human typing
        # --force is a stronger signal than a variable somebody set last month.
        settings = settings.model_copy(update={"sweep_force": True})

    log.info("sweep=%s dry_run=%s -- %s", args.sweep, args.dry_run, SWEEPS[args.sweep])

    try:
        ctx = build_context(settings, need_artifacts=args.sweep in NEEDS_ARTIFACTS)
        report = HANDLERS[args.sweep](ctx, dry_run=args.dry_run)
    except Exception:
        # A sweep that dies must LOOK dead. Logging and returning non-zero rather
        # than letting the traceback propagate keeps the message in the same
        # format as the summary line an operator is scanning for.
        log.exception("sweep=%s failed", args.sweep)
        return 1

    log.info("%s", report.summary())
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
