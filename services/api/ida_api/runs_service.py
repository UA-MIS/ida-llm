"""Enqueueing runs: the body of ``POST /runs``, shared with ``POST /admin/runs``.

Extracted so the public route and the admin console run the SAME code: the
same validation (unknown -> 404, disabled -> 409, nothing enqueued), the same
rows-before-messages ordering, the same partial-push accounting.  Two copies of
the path that spends money would drift, and the one that drifted would be the
one spending it.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from ida_api.schemas import EnqueueResponse
from ida_core.contracts import RunJobMessage, RunRecord, RunStatus, SamplingParams
from ida_core.db import RunRow, session_scope, utcnow
from ida_core.ids import new_id, new_run_id
from ida_core.repositories import create_run

log = logging.getLogger("ida_api.app")
"""The enqueue log line keeps the logger it always had: it is the attribution
record ("who spent the money"), and anything filtering on it -- a log query, a
test -- must not lose it because the code moved."""


def validate_targets(ctx, task_ids: list[str], model_keys: list[str]) -> None:
    """404 for an unknown task or model, 409 for a disabled model -- before
    anything is written, so a typo never leaves half a sweep running."""
    for task_id in task_ids:
        if task_id not in ctx.catalog:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no task {task_id!r}")
    for model_key in model_keys:
        try:
            entry = ctx.registry.get(model_key)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no model {model_key!r}") from None
        if not entry.enabled:
            raise HTTPException(status.HTTP_409_CONFLICT, f"model {model_key!r} is disabled")


def enqueue(
    ctx,
    *,
    task_ids: list[str],
    model_keys: list[str],
    label: str | None,
    sampling_override: SamplingParams | None,
    harness_version: str,
    principal_subject: str,
    launched_by: str | None = None,
    config_revision: int | None = None,
) -> EnqueueResponse:
    """Expand ``task_ids x model_keys`` into one queued run per pair.

    The rows are committed **before** the queue messages are pushed.  A crash
    between the two leaves a ``queued`` run that no runner picks up -- visible
    and re-enqueueable.  The other order would let a runner receive a message
    for a run row that does not exist yet.

    ``launched_by``/``config_revision`` are the admin console's provenance
    (migration 0007); the public route leaves them NULL.
    """
    validate_targets(ctx, task_ids, model_keys)
    catalog, git_sha = ctx.catalog, ctx.git_sha
    now = utcnow()
    # One sweep id for the whole cross product (B9).
    sweep_id = new_id("swp")
    records: list[RunRecord] = []
    messages: list[RunJobMessage] = []
    for task_id in task_ids:
        spec = catalog.get(task_id)
        for model_key in model_keys:
            run_id = new_run_id()
            records.append(
                RunRecord(
                    id=run_id,
                    status=RunStatus.QUEUED,
                    task_id=task_id,
                    model_key=model_key,
                    label=label,
                    sweep_id=sweep_id,
                    task_git_sha=git_sha,
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
                    sampling_override=sampling_override,
                    enqueued_at=now,
                )
            )

    with session_scope(ctx.session_factory) as session:
        for record in records:
            create_run(session, record)
        if launched_by is not None or config_revision is not None:
            session.flush()
            for record in records:
                row = session.get(RunRow, record.id)
                row.launched_by = launched_by
                row.config_revision = config_revision

    # If a push fails partway we report how many actually landed rather than
    # pretending all of them did; the un-pushed runs stay `queued` and are
    # visibly re-drivable.
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
        "sweep %s: enqueued %d/%d run(s) for principal %s%s",
        sweep_id,
        queued,
        len(records),
        principal_subject,
        f" (admin {launched_by})" if launched_by else "",
    )
    return EnqueueResponse(sweep_id=sweep_id, runs=records, queued=queued)
