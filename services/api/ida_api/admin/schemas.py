"""The admin API contract: every request and response body under ``/admin``.

**THIS FILE IS THE WP-B <-> WP-F INTERFACE.**  The frontend hand-writes
``frontend/src/lib/admin/types.ts`` from it, by way of the committed dump
``docs/admin-api.openapi.json`` (``python -m ida_api.admin.dump_openapi``), and a
frontend test fails when a path ``lib/admin`` calls is missing from that dump.
So a change here is a contract change: keep it backward compatible, regenerate
the dump in the same commit, and tell the frontend.  ``test_admin_contract``
fails if the committed dump and this file disagree.

Conventions (design section 9), stated once so no model has to repeat them:

* snake_case fields, ISO-8601 UTC timestamps;
* every mutable resource carries ``version`` -- the optimistic-concurrency
  counter a client echoes back as ``If-Match`` -- and its response sets
  ``ETag: "<version>"``;
* lists paginate with ``limit`` + an opaque ``cursor``;
* every 4xx is the :class:`AdminErrorResponse` envelope.

Input models are ``extra="forbid"`` for the same reason ``models.yaml`` is: a
misspelled field silently ignored is a setting the admin believes they changed
and did not.  Output models are not, so the API can grow a field without
breaking an older console.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ida_api.schemas import EnqueueResponse
from ida_core.contracts import (
    CostRates,
    ResultRecord,
    RunRecord,
    RunStatus,
    SamplingParams,
    ServingConfig,
)

Version = int
"""The row's optimistic-concurrency counter. Starts at 1; every write bumps it."""

GITHUB_LOGIN_PATTERN = r"^[A-Za-z0-9-]{1,39}$"
"""What GitHub allows in a login: alphanumerics and hyphens, at most 39 chars.
Used for ``X-IDA-Actor`` and for the login on auth events."""

ErrorCode = Literal[
    "admin_disabled",
    "unauthenticated",
    "forbidden",
    "actor_required",
    "not_found",
    "version_conflict",
    "precondition_required",
    "validation_failed",
    "conflict",
    "spend_confirmation_required",
    "cap_exceeded",
    "kek_missing",
    "rate_limited",
    "not_implemented",
]
"""Every ``detail.code`` the admin API can return.

``precondition_required`` (a write with no ``If-Match``), ``rate_limited``
(``POST /models/{key}/test``) and ``not_implemented`` (a contract route whose
backend PR has not landed yet) are additions to the design's list; all three
are additive."""


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ─────────────────────────────────────────────────────────────── errors ──


class Issue(BaseModel):
    """One validation finding.  ``path`` is what the UI pins the message to.

    Paths are the validators' own (``samples[3].target``, ``serving.model_id``)
    or ``line N, col M`` for a YAML parse error."""

    path: str
    message: str
    severity: Literal["error", "warning"] = "error"


class AdminErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    issues: list[Issue] | None = None
    current: Any | None = None
    """On ``version_conflict``: the row as it is now, so the UI can say who
    changed it and offer a reload."""


class AdminErrorResponse(BaseModel):
    """The envelope every admin 4xx/5xx uses: ``{"detail": {...}}``."""

    detail: AdminErrorDetail


# ─────────────────────────────────────────────────────────────── system ──


class SystemGuards(BaseModel):
    sweep_max_runs: int
    sweep_max_samples: int
    admin_run_max_estimated_usd: float
    sweep_exclude_tags: list[str]
    public_hide_tags: list[str]


class SystemInfo(BaseModel):
    """``GET /admin/system``: what this deployment is configured to do."""

    config_source: Literal["yaml", "db"]
    revision: int | None
    """``max(config_revisions.id)``; ``None`` in yaml mode or before seeding."""
    revision_at: datetime | None
    guards: SystemGuards
    judge_model_key: str | None
    kek_configured: bool
    kek_active_id: str | None
    """The active key-encryption key's id. The id only -- never key material."""
    admin_group_hint: str | None
    """The Dex group(s) the console admits, for the "denied" screen."""
    tasks_spec_gated: bool = False
    """True once the public ``GET /tasks/{id}`` no longer serves prompts to
    anonymous callers (PR B6). The UI refuses ``provenance=private`` until
    this is true (design risk R10)."""


# ─────────────────────────────────────────────────────── model families ──


class ModelFamily(BaseModel):
    key: str
    display_name: str
    member_keys: list[str]
    version: Version


class ModelFamilyCreate(_Input):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=128)
    display_name: str = Field(min_length=1, max_length=255)


class ModelFamilyUpdate(_Input):
    display_name: str = Field(min_length=1, max_length=255)


# ─────────────────────────────────────────────────────────────── models ──


MODEL_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
"""Registry keys -- the SAME pattern ``models.schema.json`` enforces on
``models.yaml``, so a key the console accepts is a key the registry accepts."""


class AdminModelInput(_Input):
    """A whole model, as the edit form submits it (``POST``/``PUT``).

    Field-for-field ``models.yaml``'s ``ModelEntry`` with two differences:
    ``family_key`` names a row in ``/admin/model-families`` (the display name
    comes from there), and ``credential_ref`` may name an admin-entered
    provider credential instead of ``api_key_env`` -- never both."""

    key: str = Field(pattern=MODEL_KEY_PATTERN, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    family_key: str | None = None
    display_order: int | None = None
    base_url: str | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    credential_ref: str | None = None
    enabled: bool = True
    hidden: bool = False
    timeout_s: float = Field(120.0, gt=0)
    max_retries: int = Field(3, ge=0, le=10)
    tags: list[str] = Field(default_factory=list)
    serving: ServingConfig
    cost: CostRates = Field(default_factory=CostRates)

    @model_validator(mode="after")
    def _one_key_source(self) -> AdminModelInput:
        if self.api_key_env and self.credential_ref:
            raise ValueError(
                "api_key_env and credential_ref are mutually exclusive: a model "
                "reads its key from an env var OR from a stored credential"
            )
        return self


class AdminModel(AdminModelInput):
    model_config = ConfigDict(extra="ignore")

    uses: Literal["env", "credential", "none"]
    key_present: bool
    """For ``env``: whether that variable is set in the API process (presence
    only, never the value). For ``credential``: whether the credential exists
    and the KEK is configured. Always true for ``none``."""
    archived_at: datetime | None = None
    updated_at: datetime
    updated_by: str | None = None
    version: Version


class AdminModelPatch(_Input):
    """Quick toggles from the list view. Absent fields are left unchanged;
    an explicit ``null`` for ``family_key``/``display_order`` clears it."""

    enabled: bool | None = None
    hidden: bool | None = None
    display_order: int | None = None
    family_key: str | None = None


class ReorderInput(_Input):
    order: list[str] = Field(min_length=1)


class ModelTestResult(BaseModel):
    ok: bool
    latency_ms: float
    error: str | None = None


# ─────────────────────────────────────────────────── provider credentials ──


class Credential(BaseModel):
    """A stored provider key's METADATA. No key material in any form."""

    name: str
    provider: str
    kek_id: str
    created_at: datetime
    created_by: str | None
    rotated_at: datetime | None
    last_used_at: datetime | None
    used_by_models: list[str]
    version: Version


class CredentialInput(_Input):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=128)
    provider: str = Field(min_length=1, max_length=64)
    api_key: SecretStr = Field(min_length=1, json_schema_extra={"writeOnly": True})
    """Write-only. ``SecretStr`` so it renders as ``**********`` in any repr,
    traceback or log line that a mistake might put it in."""


class CredentialRotateInput(_Input):
    api_key: SecretStr = Field(min_length=1, json_schema_extra={"writeOnly": True})


# ───────────────────────────────────────────────────────── task families ──


TASK_FAMILY_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
"""The ``tasks/<family>/`` directory-name convention, now a column."""


class UnitRef(BaseModel):
    course: str
    key: str


class TaskFamily(BaseModel):
    key: str
    title: str
    description: str
    provenance: Literal["synthetic", "private"]
    task_count: int
    sample_count: int
    classes: list[str]
    unit: UnitRef | None
    archived_at: datetime | None = None
    version: Version


class TaskFamilyInput(_Input):
    key: str = Field(pattern=TASK_FAMILY_KEY_PATTERN, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    provenance: Literal["synthetic", "private"] = "synthetic"


class TaskFamilyUpdate(_Input):
    """The key is immutable: task ids embed it."""

    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    provenance: Literal["synthetic", "private"] = "synthetic"


# ──────────────────────────────────────────────────────── tasks / samples ──


class AdminTaskSummary(BaseModel):
    id: str
    family_key: str
    title: str
    kind: Literal["verifiable", "subjective"]
    sample_count: int
    content_sha: str
    source: Literal["yaml_seed", "form", "upload"]
    archived_at: datetime | None = None
    updated_at: datetime
    updated_by: str | None
    version: Version


class AdminTask(AdminTaskSummary):
    document: dict[str, Any]
    """The WHOLE task document, unredacted: prompts, targets, rubric. Shape:
    ``tasks/SCHEMA.md``."""
    issues: list[Issue]
    """Warnings only -- a document with errors cannot be stored."""


class TaskWriteInput(_Input):
    document: dict[str, Any]


class TaskValidateInput(_Input):
    """Exactly one of ``document`` (the form) or ``yaml`` (the YAML tab)."""

    document: dict[str, Any] | None = None
    yaml: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> TaskValidateInput:
        if (self.document is None) == (self.yaml is None):
            raise ValueError("send exactly one of 'document' or 'yaml'")
        return self


class ValidateResult(BaseModel):
    ok: bool
    issues: list[Issue]
    content_sha: str | None = None
    sample_count: int | None = None


class SampleInput(_Input):
    sample: dict[str, Any]
    """One entry of ``document.samples``: ``{id, input, target?, metadata?}``."""


class UploadDiff(BaseModel):
    samples_added: int
    samples_removed: int
    samples_changed: int


class UploadResult(ValidateResult):
    task: AdminTaskSummary | None = None
    diff: UploadDiff | None = None
    committed: bool = False


# ─────────────────────────────────────────────────────────── curriculum ──


class AdminUnit(BaseModel):
    id: str
    course: str
    key: str
    n: int
    title: str
    covers: list[str]
    blurb: str
    source: str | None
    caveat: str | None
    families: list[str]
    version: Version


class UnitInput(_Input):
    key: str = Field(min_length=1, max_length=128)
    n: int = Field(ge=1)
    title: str = Field(min_length=1)
    covers: list[str] = Field(default_factory=list)
    blurb: str = ""
    source: str | None = None
    caveat: str | None = None
    families: list[str] = Field(default_factory=list)


class FamiliesInput(_Input):
    """The focused "assign families" body, for a class or a unit."""

    families: list[str]


class AdminClass(BaseModel):
    course: str
    major_id: str | None
    unassigned_reason: str | None
    title: str | None
    resolved_title: str | None
    """``title`` if set, else the curriculum's title for the course."""
    credit_hours: float | None
    position: int
    task_families: list[str]
    units: list[AdminUnit]
    version: Version


class ClassInput(_Input):
    """Exactly one of ``major_id`` and ``unassigned_reason``."""

    course: str = Field(min_length=1, max_length=32)
    major_id: str | None = None
    unassigned_reason: str | None = None
    title: str | None = None
    credit_hours: float | None = None
    position: int = 0

    @model_validator(mode="after")
    def _owner(self) -> ClassInput:
        if (self.major_id is None) == (self.unassigned_reason is None):
            raise ValueError("set exactly one of 'major_id' and 'unassigned_reason'")
        return self


class AdminMajor(BaseModel):
    id: str
    name: str
    department: str
    subject_codes: list[str]
    display_code: str | None
    catalog: str | None
    class_source: str
    position: int
    classes: list[AdminClass]
    version: Version


class MajorInput(_Input):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    name: str = Field(min_length=1)
    department: str = ""
    subject_codes: list[str] = Field(default_factory=list)
    display_code: str | None = None
    catalog: str | None = None
    class_source: str = "manual"
    position: int = 0


class MajorsResponse(BaseModel):
    majors: list[AdminMajor]
    unassigned: list[AdminClass]


class SloDocument(BaseModel):
    yaml: str
    version: Version
    issues: list[Issue] = Field(default_factory=list)


class SloInput(_Input):
    yaml: str


# ───────────────────────────────────────────────────────────────── runs ──


class RunLaunchInput(_Input):
    """What to measure. ``family_keys`` expands to each family's live tasks and
    is unioned with ``task_ids``; at least one of the two must name something."""

    model_keys: list[str] = Field(min_length=1)
    family_keys: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    label: str | None = Field(None, max_length=255)
    sampling_override: SamplingParams | None = None
    confirm_spend_usd: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _something_to_run(self) -> RunLaunchInput:
        if not self.family_keys and not self.task_ids:
            raise ValueError("name at least one task family or task id")
        return self


class EstimatePair(BaseModel):
    task_id: str
    model_key: str
    samples: int
    est_usd_high: float
    basis: Literal["history", "ceiling"]


class EstimateCaps(BaseModel):
    max_runs: int
    max_samples: int
    max_estimated_usd: float


class RunEstimate(BaseModel):
    runs: int
    samples: int
    pairs: list[EstimatePair]
    est_usd_high: float
    includes_judge: bool
    warnings: list[str]
    caps: EstimateCaps
    needs_confirmation: bool


class AdminRunRecord(RunRecord):
    """The public :class:`RunRecord` plus the admin-only provenance columns.

    A subclass rather than new fields on ``RunRecord`` so the PUBLIC ``/runs``
    payload stays byte-identical."""

    launched_by: str | None = None
    config_revision: int | None = None
    cancel_requested_at: datetime | None = None


class AdminEnqueueResponse(EnqueueResponse):
    estimate: RunEstimate


class AdminRunList(BaseModel):
    runs: list[AdminRunRecord]
    next_cursor: str | None


class AdminRunDetail(BaseModel):
    """``GET /admin/runs/{id}``: UNREDACTED (explanations, errors)."""

    run: AdminRunRecord
    results: list[ResultRecord]
    results_total: int


class SweepSummary(BaseModel):
    sweep_id: str
    created_at: datetime
    launched_by: str | None
    label: str | None
    run_count: int
    by_status: dict[RunStatus, int]
    total_cost_usd: float


class SweepList(BaseModel):
    sweeps: list[SweepSummary]
    next_cursor: str | None


class SweepDetail(BaseModel):
    summary: SweepSummary
    runs: list[AdminRunRecord]


# ──────────────────────────────────────────────────────────────── audit ──


class AuditEntry(BaseModel):
    id: int
    at: datetime
    actor_login: str
    actor_sub: str | None = None
    via_subject: str
    action: str
    entity_type: str
    entity_id: str
    before: Any | None
    after: Any | None
    config_revision: int | None
    request_id: str | None = None


class AuditList(BaseModel):
    entries: list[AuditEntry]
    next_cursor: str | None


class AuthEventInput(_Input):
    """Posted by the frontend's Auth.js ``events`` -- the only record of a
    DENIED sign-in, since a non-member never reaches any other route."""

    action: Literal["auth.sign_in", "auth.denied", "auth.sign_out"]
    login: str = Field(pattern=GITHUB_LOGIN_PATTERN)
    sub: str | None = Field(None, max_length=255)
    groups_ok: bool
