"""The FastAPI application: routes, wiring, error handling.

Route map
---------
``GET  /health``            liveness + dependency checks
``GET  /models``            the model registry (secrets stripped)
``GET  /tasks``             the task catalog, with scorability
``GET  /tasks/{task_id}``   one full task spec
``POST /runs``              enqueue task x model runs
``GET  /runs``              newest-first list of runs
``GET  /runs/{run_id}``     one run plus its results (score + artifact pointer)
``GET  /runs/{run_id}/results/{sample_id}/transcript``
                            the archived transcript, fetched from object storage

The API is a thin, honest layer over :mod:`ida_core.repositories`.  Any logic
that is about *evaluating* belongs in the harness, not here.
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from ida_api import __version__
from ida_api.auth import Principal, current_principal
from ida_api.deps import AppContext, build_context, get_context
from ida_api.schemas import (
    EnqueueResponse,
    HealthResponse,
    ModelSummary,
    RunListResponse,
    TaskDetail,
    TaskSummary,
)
from ida_core import artifacts as artifact_paths
from ida_core.contracts import (
    RunDetail,
    RunJobMessage,
    RunRecord,
    RunRequest,
    RunStatus,
)
from ida_core.db import session_scope, utcnow
from ida_core.ids import new_id, new_run_id
from ida_core.repositories import (
    count_runs,
    create_run,
    get_run,
    list_results_for_run,
    list_runs,
    result_row_to_record,
    run_row_to_record,
)
from ida_harness import __version__ as harness_version
from ida_harness.runner import unscorable_reason

log = logging.getLogger(__name__)

MAX_PAGE_SIZE = 200
"""Hard cap on ``GET /runs?limit=``.  Prevents an accidental full-table scan."""


def create_app(context: AppContext | None = None) -> FastAPI:
    """Build the API.

    ``context`` is injected by tests (in-memory queue, SQLite, local artifact
    store).  In production it is ``None`` and :func:`build_context` reads the
    environment.
    """
    app = FastAPI(
        title="Capstone-IDA API",
        version=__version__,
        description=(
            "Benchmarking platform for LLMs on non-coding academic tasks. "
            "Every result carries the full serving config and task git SHA "
            "needed to reproduce it (D-1)."
        ),
    )

    app.state.context = context or build_context()
    app.state.settings = app.state.context.settings

    # TODO-PLACEHOLDER(cors-origins): restrict to the platform ingress hostnames
    # once the dev/staging/prod domains are assigned. Open during skeleton dev
    # so the Next.js dev server on :3000 can call the API on :8000.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------- health --

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health(ctx: AppContext = Depends(get_context)) -> HealthResponse:
        """Readiness probe: reports each dependency separately.

        Returns 200 with ``status="degraded"`` rather than 503 when a
        dependency is down, so the probe response body is still readable in
        ``kubectl describe``. The k8s readinessProbe checks the body, not just
        the code -- see the probes on `ida-llm-api` in .devops/chart/base/deployments.yaml.
        """
        checks = {"database": _check_database(ctx), "queue": _check_queue(ctx)}
        return HealthResponse(
            status="ok" if all(checks.values()) else "degraded",
            version=__version__,
            checks=checks,
        )

    # ------------------------------------------------------------ registry --

    @app.get("/models", response_model=list[ModelSummary], tags=["registry"])
    def list_models(
        ctx: AppContext = Depends(get_context),
        include_disabled: bool = Query(
            False, description="Include entries with enabled: false"
        ),
    ) -> list[ModelSummary]:
        """The parsed ``models.yaml``, with API keys and key values never exposed."""
        entries = ctx.registry.models
        if not include_disabled:
            entries = [e for e in entries if e.enabled]
        return [ModelSummary.from_entry(e) for e in entries]

    @app.get("/tasks", response_model=list[TaskSummary], tags=["registry"])
    def list_tasks(ctx: AppContext = Depends(get_context)) -> list[TaskSummary]:
        """The task catalog.

        Subjective tasks appear here with ``scorable: false`` and a reason, so
        the UI can say "not yet scorable" instead of showing a misleading zero.
        """
        return [
            TaskSummary(
                id=spec.id,
                title=spec.title,
                description=spec.description,
                kind=spec.kind,
                domain=spec.domain,
                scorer=spec.scorer.kind.value,
                sample_count=len(spec.samples),
                scorable=spec.is_scorable,
                unscorable_reason=unscorable_reason(spec),
                tags=list(spec.tags),
            )
            for spec in ctx.catalog.all()
        ]

    @app.get("/tasks/{task_id:path}", response_model=TaskDetail, tags=["registry"])
    def get_task(
        task_id: str,
        ctx: AppContext = Depends(get_context),
        principal: Principal = Depends(current_principal),
        include_targets: bool = Query(
            False,
            description=(
                "Include gold answers. Requires the 'author' role: publishing the "
                "answer key for every verifiable benchmark is both an integrity "
                "and a training-contamination risk."
            ),
        ),
    ) -> TaskDetail:
        """One full task spec.  **Gold answers are redacted by default (A10).**

        ``:path`` because task ids contain slashes (``demo/arithmetic-quiz-check``).

        Reads are unauthenticated in the skeleton, so this endpoint is reachable
        by anyone who can reach the ingress.  Returning every ``target`` would
        publish our answer key -- see :class:`~ida_api.schemas.TaskDetail`.
        Authors ask for ``?include_targets=true``; everyone else gets the task
        text and an honest ``targets_redacted: true``.
        """
        try:
            spec = ctx.catalog.get(task_id)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no task {task_id!r}") from None
        if include_targets:
            principal.require_role("author")
        return TaskDetail.of(
            spec,
            include_targets=include_targets,
            unscorable_reason=unscorable_reason(spec),
        )

    # ---------------------------------------------------------------- runs --

    @app.post(
        "/runs",
        response_model=EnqueueResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["runs"],
    )
    def enqueue_runs(
        request: RunRequest,
        ctx: AppContext = Depends(get_context),
        principal: Principal = Depends(current_principal),
    ) -> EnqueueResponse:
        """Expand ``task_ids x model_keys`` into one queued run per pair.

        Validation happens *before* anything is written: an unknown task id or
        model key 404s with nothing enqueued, so a typo never leaves half a
        sweep running.

        The rows are committed **before** the queue messages are pushed.  A
        crash between the two leaves a ``queued`` run that no runner picks up --
        visible and re-enqueueable.  The other order would let a runner receive
        a message for a run row that does not exist yet, which is a 500 in the
        runner and much harder to reason about.
        """
        principal.require_role("runner")

        for task_id in request.task_ids:
            if task_id not in ctx.catalog:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no task {task_id!r}")
        for model_key in request.model_keys:
            try:
                entry = ctx.registry.get(model_key)
            except KeyError:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"no model {model_key!r}"
                ) from None
            if not entry.enabled:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, f"model {model_key!r} is disabled"
                )

        now = utcnow()
        # One sweep id for the whole cross product (B9). Without it, "show me
        # the comparison table for the sweep I just launched" is a string match
        # on a nullable free-text label.
        sweep_id = new_id("swp")
        records: list[RunRecord] = []
        messages: list[RunJobMessage] = []
        for task_id in request.task_ids:
            spec = ctx.catalog.get(task_id)
            for model_key in request.model_keys:
                run_id = new_run_id()
                records.append(
                    RunRecord(
                        id=run_id,
                        status=RunStatus.QUEUED,
                        task_id=task_id,
                        model_key=model_key,
                        label=request.label,
                        sweep_id=sweep_id,
                        task_git_sha=ctx.git_sha,
                        task_content_sha=spec.content_sha or None,
                        harness_version=harness_version,
                        sample_count=len(spec.samples),
                        created_at=now,
                    )
                )
                messages.append(
                    RunJobMessage(
                        run_id=run_id,
                        task_id=task_id,
                        model_key=model_key,
                        sweep_id=sweep_id,
                        sampling_override=request.sampling_override,
                        enqueued_at=now,
                    )
                )

        with session_scope(ctx.session_factory) as session:
            for record in records:
                create_run(session, record)

        # Rows are committed above, before any message is pushed -- see the
        # docstring. If a push fails partway we report how many actually landed
        # rather than pretending all of them did; the un-pushed runs stay
        # `queued` and are visibly re-drivable.
        queued = 0
        for message in messages:
            try:
                ctx.queue.enqueue(message)
                queued += 1
            except Exception:
                log.exception(
                    "queue push failed for run %s; %d of %d landed",
                    message.run_id,
                    queued,
                    len(messages),
                )
                break

        log.info(
            "sweep %s: enqueued %d/%d run(s) for principal %s",
            sweep_id,
            queued,
            len(records),
            principal.subject,
        )
        return EnqueueResponse(sweep_id=sweep_id, runs=records, queued=queued)

    @app.get("/runs", response_model=RunListResponse, tags=["runs"])
    def get_runs(
        ctx: AppContext = Depends(get_context),
        limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(0, ge=0),
        run_status: RunStatus | None = Query(None, alias="status"),
        task_id: str | None = Query(None),
        model_key: str | None = Query(None),
        sweep_id: str | None = Query(None, description="All runs from one POST /runs"),
    ) -> RunListResponse:
        """Newest-first page of runs.  The frontend's landing page calls this.

        ``total`` reports how many rows match the filters overall, so a client
        can paginate without probing for the end.
        """
        with session_scope(ctx.session_factory) as session:
            filters = {
                "status": run_status,
                "task_id": task_id,
                "model_key": model_key,
                "sweep_id": sweep_id,
            }
            rows = list_runs(session, limit=limit, offset=offset, **filters)
            return RunListResponse(
                runs=[run_row_to_record(r) for r in rows],
                total=count_runs(session, **filters),
                limit=limit,
                offset=offset,
            )

    @app.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"])
    def get_run_detail(run_id: str, ctx: AppContext = Depends(get_context)) -> RunDetail:
        """One run plus every result: score, serving config, artifact pointer."""
        with session_scope(ctx.session_factory) as session:
            row = get_run(session, run_id)
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {run_id!r}")
            results = [result_row_to_record(r) for r in list_results_for_run(session, run_id)]
            return RunDetail(run=run_row_to_record(row), results=results)

    @app.get("/runs/{run_id}/results/{sample_id}/transcript", tags=["runs"])
    def get_transcript(
        run_id: str, sample_id: str, ctx: AppContext = Depends(get_context)
    ) -> dict:
        """Fetch an archived transcript from object storage.

        The API resolves the object key from the *path convention*, not from a
        user-supplied URI -- a client can never make this endpoint read an
        arbitrary object.
        """
        try:
            key = artifact_paths.sample_key(run_id, sample_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        try:
            return ctx.artifact_store.get_json(key)
        except KeyError:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"no transcript for run {run_id!r} sample {sample_id!r}",
            ) from None

    return app


def _check_database(ctx: AppContext) -> bool:
    try:
        with session_scope(ctx.session_factory) as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        log.exception("database health check failed")
        return False


def _check_queue(ctx: AppContext) -> bool:
    ping = getattr(ctx.queue, "ping", None)
    if ping is None:
        return True
    try:
        return bool(ping())
    except Exception:
        log.exception("queue health check failed")
        return False
