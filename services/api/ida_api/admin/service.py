"""The one shape every admin write takes (design 5.1).

    load -> apply -> validate the POST-WRITE state -> (task revision) ->
    append config_revisions -> append audit_log -> commit

all inside ONE transaction, so nothing is ever half-applied: a validation
failure, a version conflict or a constraint violation rolls the whole thing
back and the database is exactly as it was.

Handlers use :func:`admin_write` and only describe the change; the revision,
the audit row, the rollback and the "make my own process see it now" nudge are
here, written once.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ida_api.admin.deps import AdminContext, admin_error, check_version
from ida_api.admin.schemas import Issue as IssueModel
from ida_api.deps import AppContext
from ida_core.configdb import reader
from ida_core.configdb.seed import record_revision
from ida_core.configdb.tables import AuditLogRow
from ida_core.db import utcnow
from ida_core.validation_suite import Issue, errors_of, validate_models
from ida_harness.tasks import TaskCatalog

SCOPE_MODELS = "models"
SCOPE_TASKS = "tasks"


def require_db_config(ctx: AppContext) -> None:
    """Config routes need ``IDA_CONFIG_SOURCE=db``.

    In yaml mode the tables are not the source of truth -- they may not even be
    seeded -- so an edit would be written somewhere nothing reads. Refusing
    loudly beats a console that saves successfully and changes nothing."""
    if ctx.settings.config_source != "db":
        raise admin_error(
            status.HTTP_409_CONFLICT,
            "conflict",
            "this deployment reads its configuration from YAML (IDA_CONFIG_SOURCE=yaml); "
            "admin edits need IDA_CONFIG_SOURCE=db",
        )


def to_issue_models(issues: list[Issue]) -> list[IssueModel]:
    return [IssueModel(path=i.path, message=i.message, severity=i.severity) for i in issues]


def validation_failed(issues: list[Issue], message: str = "Change failed validation"):
    return admin_error(422, "validation_failed", message, issues=to_issue_models(issues))


def not_found(what: str):
    return admin_error(status.HTTP_404_NOT_FOUND, "not_found", f"{what} does not exist")


def conflict(message: str):
    return admin_error(status.HTTP_409_CONFLICT, "conflict", message)


def bump(row: Any, admin: AdminContext) -> None:
    """Every mutation of a versioned row: version + who/when."""
    row.version = (row.version or 0) + 1
    row.updated_at = utcnow()
    row.updated_by = admin.actor


def stamp_new(row: Any, admin: AdminContext) -> Any:
    row.version = 1
    row.created_by = row.updated_by = admin.actor
    return row


def expect_version(row: Any, expected: int, current: Any) -> None:
    check_version(expected=expected, actual=row.version, current=current)


@dataclass
class Write:
    """What a handler fills in inside :func:`admin_write`."""

    session: Session
    action: str
    entity_type: str
    entity_id: str
    summary: str
    scopes: set[str] = field(default_factory=set)
    before: Any = None
    after: Any = None
    revision: int | None = None


def validate_post_state(session: Session, scopes: set[str]) -> list[Issue]:
    """The shared suite over the state this transaction would commit."""
    issues: list[Issue] = []
    if SCOPE_MODELS in scopes:
        issues += [
            Issue(f"registry.{i.path}" if i.path else "registry", i.message, i.severity)
            for i in validate_models(reader.models_document(session))
        ]
    if SCOPE_TASKS in scopes:
        # The whole live catalog must still build -- the same two layers and the
        # same duplicate-id rule every process applies when it loads a snapshot.
        try:
            TaskCatalog.from_documents(reader.task_documents(session))
        except Exception as exc:
            issues.append(Issue("catalog", str(exc)))
    return issues


@contextmanager
def admin_write(
    ctx: AppContext,
    admin: AdminContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    summary: str,
    scopes: set[str] | None = None,
    bumps_revision: bool = True,
) -> Iterator[Write]:
    """One admin write, in one transaction.  See the module docstring.

    ``bumps_revision=False`` for audited actions that change no configuration
    (a connection test, a run launch, a sign-in event)."""
    if bumps_revision:
        require_db_config(ctx)
    session = ctx.session_factory()
    write = Write(
        session=session,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        scopes=set(scopes or ()),
    )
    try:
        yield write
        session.flush()
        errors = errors_of(validate_post_state(session, write.scopes))
        if errors:
            raise validation_failed(errors)
        if bumps_revision:
            write.revision = record_revision(
                session, actor=admin.actor, source="admin", summary=write.summary
            )
        session.add(
            AuditLogRow(
                actor_login=admin.actor,
                actor_sub=admin.actor_sub,
                via_subject=admin.principal.subject,
                action=write.action,
                entity_type=write.entity_type,
                entity_id=write.entity_id,
                before=write.before,
                after=write.after,
                config_revision=write.revision,
                request_id=admin.request_id,
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise conflict(
            "the change conflicts with existing configuration "
            f"({type(exc.orig).__name__ if exc.orig else 'constraint'})"
        ) from None
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
    if bumps_revision:
        refresh_now(ctx)


def refresh_now(ctx: AppContext) -> None:
    """Make THIS process serve the new revision on its next read, instead of
    after the refresh interval -- the admin who just saved sees their edit.
    Other processes pick it up within ``IDA_CONFIG_REFRESH_S``."""
    invalidate = getattr(ctx.config, "invalidate", None)
    if invalidate is not None:
        invalidate()
