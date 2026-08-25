"""HTTP-facing response models.

Most endpoints return the :mod:`ida_core.contracts` types directly -- the wire
format *is* the contract, and re-declaring it would let the two drift.  This
module holds only the shapes that exist purely for HTTP: envelopes, health, and
the enqueue acknowledgement.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ida_core.contracts import ModelEntry, Rubric, RunRecord, ScorerSpec, TaskKind, TaskSpec


class HealthResponse(BaseModel):
    """``GET /health``.  ``status`` is ``ok`` only if every dependency answered."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str = "api"
    version: str
    checks: dict[str, bool]
    """Per-dependency liveness: ``database``, ``queue``.  All must be true for ``ok``."""

    git_sha: str | None = None
    """The commit this build was made from, or ``None`` when it cannot be known.

    THE FIELD THAT IDENTIFIES THE RUNNING BUILD.  ``version`` is whatever the
    release process was told to say; this is baked into the image at build time
    (``IDA_GIT_SHA``, from the ``GIT_SHA`` build-arg) and is correct by
    construction.  ``None`` means "unreproducible" and is never a placeholder --
    a wrong SHA looks like a real one (see :mod:`ida_core.gitmeta`).
    """


class ModelSummary(BaseModel):
    """A registry entry as the UI wants it: no secrets, key *name* only."""

    model_config = ConfigDict(extra="forbid")

    key: str
    display_name: str
    base_url: str
    enabled: bool
    requires_api_key: bool
    """True when the entry names an ``api_key_env``.  The value is never exposed."""

    serving_stack: str
    model_id: str
    quantization: str
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_entry(cls, entry: ModelEntry) -> ModelSummary:
        return cls(
            key=entry.key,
            display_name=entry.display_name,
            base_url=entry.base_url,
            enabled=entry.enabled,
            requires_api_key=entry.api_key_env is not None,
            serving_stack=entry.serving.serving_stack.value,
            model_id=entry.serving.model_id,
            quantization=entry.serving.quantization.value,
            tags=list(entry.tags),
        )


class TaskSummary(BaseModel):
    """A task as the UI wants it: no samples, but the scorability verdict."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    kind: TaskKind
    domain: str
    scorer: str
    sample_count: int
    scorable: bool
    """False for subjective tasks until the LLM judge lands."""

    unscorable_reason: str | None = None
    tags: list[str] = Field(default_factory=list)


class EnqueueResponse(BaseModel):
    """``POST /runs``.  One :class:`RunRecord` per (task, model) pair, all ``queued``."""

    model_config = ConfigDict(extra="forbid")

    sweep_id: str
    """Groups every run this request created (B9).

    Returned so the caller can immediately ask ``GET /runs?sweep_id=...`` for
    the comparison view, rather than string-matching a free-text label.
    """

    runs: list[RunRecord]
    queued: int
    """Queue messages actually pushed.

    Normally equals ``len(runs)``.  It is reported separately rather than
    assumed because rows are committed *before* messages are pushed, so the two
    can legitimately differ if the queue fails partway -- and a caller that sees
    ``queued < len(runs)`` knows to re-drive rather than to wait forever.
    """


class RunListResponse(BaseModel):
    """``GET /runs``.  Newest first."""

    model_config = ConfigDict(extra="forbid")

    runs: list[RunRecord]
    total: int
    """Rows matching the filters, ignoring pagination (A11).

    Without this a UI cannot render "page 3 of 12", and can only discover the
    end of the list by requesting a page that comes back short.
    """

    limit: int
    offset: int


class SampleView(BaseModel):
    """One sample as the API exposes it: the prompt, and optionally the answer."""

    model_config = ConfigDict(extra="forbid")

    id: str
    input: str
    metadata: dict = Field(default_factory=dict)

    target: str | None = None
    """The gold answer, or ``None`` when redacted **or** genuinely absent.

    Do not infer "this task has no answer key" from a ``None`` here -- consult
    :attr:`has_target` and :attr:`TaskDetail.targets_redacted`.
    """

    has_target: bool = False
    """Whether an answer key exists.  Safe to publish; the answer itself is not."""


class TaskDetail(BaseModel):
    """``GET /tasks/{id}``: the task, with gold answers redacted by default (A10).

    **Why this is not just a `TaskSpec`.** A verifiable ``TaskSpec`` is invalid
    without a target on every sample -- the taxonomy validator enforces exactly
    that, and it should. A redacted view is therefore *not a task*: it is a
    projection of one, and giving it its own type keeps that honest. A client
    cannot round-trip this back in as a task definition, which is correct,
    because it is missing the answers.

    **Why redact at all.** Reads are unauthenticated in the skeleton (D-5:
    platform SSO lands later), so this endpoint is reachable by anyone who can
    reach the ingress. Returning every ``target`` publishes the answer key for
    every verifiable benchmark we run: an integrity problem (anyone can tune
    against our key) and a contamination one (a scraped key reaches a future
    training corpus, after which the benchmark measures memorisation rather than
    ability). A caller holding the ``author`` role can pass
    ``?include_targets=true``; when real auth arrives, granting that role is the
    only change required.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    kind: TaskKind
    domain: str
    system_prompt: str | None
    scorer: ScorerSpec
    rubric: Rubric | None
    tags: list[str]

    content_sha: str
    """SHA-256 of the canonicalised task definition (B8).

    Exposed so a consumer can ask "are these two runs of the same task text?"
    without needing the task body, and without trusting a repo-wide git SHA.
    """

    samples: list[SampleView]
    sample_count: int
    scorable: bool
    unscorable_reason: str | None = None

    targets_redacted: bool
    """True when gold answers were withheld.  Stated explicitly so a client
    never mistakes a redacted view for a task that has no answer key."""

    @classmethod
    def of(
        cls,
        spec: TaskSpec,
        *,
        include_targets: bool,
        unscorable_reason: str | None = None,
    ) -> TaskDetail:
        """Project a :class:`TaskSpec` into the wire view."""
        return cls(
            id=spec.id,
            title=spec.title,
            description=spec.description,
            kind=spec.kind,
            domain=spec.domain,
            system_prompt=spec.system_prompt,
            scorer=spec.scorer,
            rubric=spec.rubric,
            tags=list(spec.tags),
            content_sha=spec.content_sha,
            samples=[
                SampleView(
                    id=sample.id,
                    input=sample.input,
                    metadata=sample.metadata,
                    target=sample.target if include_targets else None,
                    has_target=sample.target is not None,
                )
                for sample in spec.samples
            ],
            sample_count=len(spec.samples),
            scorable=spec.is_scorable,
            unscorable_reason=unscorable_reason,
            targets_redacted=not include_targets,
        )
