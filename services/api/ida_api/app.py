"""The FastAPI application: routes, wiring, error handling.

Route map
---------
``GET  /healthz``           LIVENESS. Touches nothing. Always 200.
``GET  /readyz``            READINESS. Checks every dependency; 503 if any fails.
``GET  /health``            alias of /readyz's body at 200 (compose + tracer)
``GET  /metrics``           Prometheus exposition (ServiceMonitor ida-llm-api)
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
import time

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
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
from ida_core.gitmeta import build_identity
from ida_core.ids import new_id, new_run_id
from ida_core.repositories import (
    count_results_for_run,
    count_runs,
    create_run,
    get_run,
    list_results_for_run,
    list_runs,
    result_row_to_record,
    run_row_to_record,
)
from ida_harness.runner import unscorable_reason

log = logging.getLogger(__name__)

HARNESS_VERSION = build_identity()
"""What goes into ``runs.harness_version`` on the rows this process enqueues.

⚠ RESOLVED ONCE, AT IMPORT, NOT PER REQUEST. With ``IDA_GIT_SHA`` unset
:func:`build_identity` shells out to ``git``, and this value is read on the
``POST /runs`` path -- a fork per enqueue would be a real cost for a value that
cannot change while the process lives. Inside the image ``IDA_GIT_SHA`` is baked
in, so no subprocess runs at all.

It used to be ``ida_harness.__version__``, a hardcoded ``"0.1.0"`` that no
release step ever wrote to. See :func:`ida_core.gitmeta.build_identity`. The
runner overwrites this field with the harness's own answer when the run
finishes; the two agree because both call the same resolver.
"""

MAX_PAGE_SIZE = 200
"""Hard cap on ``GET /runs?limit=``.  Prevents an accidental full-table scan."""

REQUESTS = Counter(
    "ida_llm_api_requests_total",
    "API requests, by method, matched route template and status code.",
    ["method", "route", "status"],
)

REQUEST_SECONDS = Histogram(
    "ida_llm_api_request_duration_seconds",
    "API request latency, by matched route template.",
    ["method", "route"],
)


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

    @app.middleware("http")
    async def _record_request_metrics(request: Request, call_next):
        """Count and time every request.

        ⚠ LABELLED BY ROUTE TEMPLATE (`/runs/{run_id}`), NEVER BY RAW PATH.
        Raw paths mint one time series per run id, and a benchmark platform
        creates run ids without limit -- that is unbounded cardinality, and it
        takes Prometheus down rather than the app.

        The template is only known AFTER routing, so it is read off
        `request.scope["route"]` on the way out. A request that matched no route
        is labelled `<unmatched>` for the same reason: 404-scanning traffic must
        not be able to create series either.
        """
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        template = getattr(route, "path", None) or "<unmatched>"
        REQUEST_SECONDS.labels(method=request.method, route=template).observe(
            time.perf_counter() - started
        )
        REQUESTS.labels(
            method=request.method, route=template, status=str(response.status_code)
        ).inc()
        return response

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
    #
    # THE SPLIT IS A DEPLOYMENT CONTRACT, NOT AN APP DETAIL.
    #
    # /healthz is LIVENESS and MUST NOT TOUCH A DEPENDENCY. A liveness probe
    # that checks the database turns a brief Postgres blip into a rolling
    # restart of every replica -- that is how a small outage becomes a large
    # one. TestHealth::test_healthz_never_touches_a_dependency fails if this
    # endpoint ever grows a dependency check.
    #
    # /readyz is READINESS and DOES check, and returns 503 when anything is
    # down, so a pod that cannot reach its database is pulled from the Service
    # and left running -- diagnosable, not restarted.
    #
    # See the probes on `ida-llm-api` in .devops/chart/base/deployments.yaml.

    @app.get("/healthz", response_model=HealthResponse, tags=["ops"])
    def healthz() -> HealthResponse:
        """Liveness. No dependencies, no I/O, no `ctx`. Always 200."""
        return HealthResponse(status="ok", version=__version__, checks={})

    def _readiness() -> tuple[HealthResponse, dict[str, bool]]:
        ctx: AppContext = app.state.context
        # EVERY check runs even when an earlier one fails: a response that stops
        # at the first failure hides the second, and "the database is down" plus
        # "so is redis" is a different incident from either alone.
        checks = {
            "database": _check_database(ctx),
            "queue": _check_queue(ctx),
            "artifacts": _check_artifacts(ctx),
        }
        body = HealthResponse(
            status="ok" if all(checks.values()) else "degraded",
            version=__version__,
            checks=checks,
        )
        return body, checks

    @app.get("/readyz", response_model=HealthResponse, tags=["ops"])
    def readyz(response: Response) -> HealthResponse:
        """Readiness. Each dependency reported separately; 503 if any is down."""
        body, checks = _readiness()
        if not all(checks.values()):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return body

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        """/readyz's body, ALWAYS at 200.

        Kept because the compose healthcheck and both tracer modes read
        ``status`` from the body rather than the status code, and because a
        200-with-detail is the more useful thing to curl while debugging.
        Neither probe points here.
        """
        return _readiness()[0]

    # ------------------------------------------------------------ metrics --

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    def metrics() -> Response:
        """Prometheus exposition. Scraped by ServiceMonitor `ida-llm-api`."""
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    # ------------------------------------------------------------ registry --

    @app.get("/models", response_model=list[ModelSummary], tags=["registry"])
    def list_models(
        ctx: AppContext = Depends(get_context),
        include_disabled: bool = Query(False, description="Include entries with enabled: false"),
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
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no model {model_key!r}") from None
            if not entry.enabled:
                raise HTTPException(status.HTTP_409_CONFLICT, f"model {model_key!r} is disabled")

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
                        harness_version=HARNESS_VERSION,
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
    def get_run_detail(
        run_id: str,
        ctx: AppContext = Depends(get_context),
        limit: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(0, ge=0),
    ) -> RunDetail:
        """One run plus a page of its results: score, serving config, artifact pointer.

        **Why this is paged at all.** A run holds one result per (sample,
        repetition). Nothing bounds that product -- a large task swept with
        repeats is the normal way to get a big one -- and this endpoint used to
        serialise every row, so the response size was set by authored data
        rather than by anything the API controls.

        The default is the maximum page rather than a small one, deliberately:
        no run this platform can currently produce reaches it, so existing
        clients see exactly what they saw before, while the response gains a
        ceiling. ``results_total`` always reports the true count, so a client
        can detect a partial view instead of quietly drawing conclusions from
        one.
        """
        with session_scope(ctx.session_factory) as session:
            row = get_run(session, run_id)
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {run_id!r}")
            rows = list_results_for_run(session, run_id, limit=limit, offset=offset)
            return RunDetail(
                run=run_row_to_record(row),
                results=[result_row_to_record(r) for r in rows],
                results_total=count_results_for_run(session, run_id),
                results_limit=limit,
                results_offset=offset,
            )

    @app.get("/runs/{run_id}/results/{sample_id}/transcript", tags=["runs"])
    def get_transcript(run_id: str, sample_id: str, ctx: AppContext = Depends(get_context)) -> dict:
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


def _check_artifacts(ctx: AppContext) -> bool:
    """Can we reach the object store at all?

    ``ensure_bucket`` is idempotent and is the cheapest call that actually
    round-trips to MinIO -- a readiness check that only inspected local state
    would report Ready while every transcript write was failing.
    """
    try:
        ctx.artifact_store.ensure_bucket()
        return True
    except Exception:
        log.exception("artifact store health check failed")
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
