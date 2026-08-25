"""**The frozen contracts.**  Everything else in Capstone-IDA codes against this file.

Read this module top-to-bottom and you should be able to write a task, a
scorer, a runner or a UI without asking anyone a question.

Layering
--------
``TaskSpec``      what to ask a model  (authored as YAML under ``tasks/``)
``ModelEntry``    what to ask it *of*  (authored as YAML in ``models.yaml``)
``RunRequest``    a user's intent: run these tasks against these models
``RunJobMessage`` the wire format on the Redis queue (api -> runner)
``EvalLog``       the harness's structured output for one (task, model) pair
``ResultRecord``  one scored sample, the durable unit the UI reads

Reproducibility (decision **D-1**)
----------------------------------
A result is worthless if you cannot say *exactly* what produced it.  Every
``ResultRecord`` therefore embeds a complete :class:`ServingConfig` (model id,
quantization, sampling params, serving stack + version) **and** the git SHA of
the task/rubric definitions that were in effect (:attr:`RunRecord.task_git_sha`).
Neither is optional and neither is a foreign key -- they are *copied in* so that
editing ``models.yaml`` or a task YAML tomorrow cannot retroactively change what
a stored result claims.

Task taxonomy (the key axis)
----------------------------
Every task is exactly one of:

``verifiable``  scored programmatically against a gold answer
                (:class:`ScorerKind.EXACT_MATCH`, :class:`ScorerKind.NUMERIC_MATCH`).
``subjective``  scored by an LLM judge against a rubric.  **Not implemented in
                the walking skeleton** -- the interface exists, the scorer
                raises ``NotImplementedError``, and such tasks are loaded and
                validated but marked not-yet-scorable.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SWEEP_DIMENSION = 200
"""Cap on ``task_ids`` / ``model_keys`` length in a single :class:`RunRequest`."""

MAX_SWEEP_RUNS = 500
"""Cap on ``len(task_ids) * len(model_keys)``.

A spend guard, not a technical limit.  ``POST /runs`` is unauthenticated in the
skeleton and every run costs real money once a hosted model is enabled, so the
cross product needs a ceiling that fails loudly rather than a queue that fills
quietly.  Raise it deliberately when someone actually needs a bigger sweep.
"""


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class TaskKind(StrEnum):
    """The taxonomy axis that decides how a task can be scored."""

    VERIFIABLE = "verifiable"
    """Programmatically scorable against a gold answer.  No judge needed."""

    SUBJECTIVE = "subjective"
    """Requires a rubric + LLM-as-judge.  Interface only in the skeleton."""


class ScorerKind(StrEnum):
    """Identifiers of the scorers the harness knows how to construct."""

    EXACT_MATCH = "exact_match"
    """String equality after the normalisation configured on the task."""

    NUMERIC_MATCH = "numeric_match"
    """Parse a number out of the completion; compare within a tolerance."""

    LLM_JUDGE = "llm_judge"
    """Rubric-graded by a judge model.  Registered but not implemented."""


class RunStatus(StrEnum):
    """Lifecycle of a :class:`RunRecord`.

    ``queued`` -> ``running`` -> (``succeeded`` | ``partial`` | ``failed``).
    A run that the runner claims but never finishes stays ``running``; reaping
    stale runs is deliberately out of scope for the skeleton.

    The three terminal states are decided by :attr:`RunRecord.error_count`
    against :attr:`RunRecord.sample_count` and are **not** interchangeable.
    Reporting a run in which every sample errored as ``succeeded`` -- which an
    earlier revision did -- tells the reader the model was measured when it was
    not, and is exactly the kind of false statement this platform exists to
    avoid.  :func:`terminal_status` is the single place that decision is made.
    """

    QUEUED = "queued"
    RUNNING = "running"

    SUCCEEDED = "succeeded"
    """Every sample produced a result without erroring.

    Note this does **not** mean every sample was *scored*: a subjective task
    succeeds with zero scores, because not-yet-scorable is not a failure.
    """

    PARTIAL = "partial"
    """Some samples errored, some completed.  The run measured *something*.

    A consumer aggregating scores must treat a ``partial`` run's mean as
    computed over the surviving samples only -- see
    :attr:`RunRecord.error_count`.
    """

    FAILED = "failed"
    """The run measured nothing: setup failed, or every sample errored."""


def terminal_status(*, sample_count: int, error_count: int) -> RunStatus:
    """Decide a finished run's status from its error accounting.

    One function, used by the harness and asserted by the tests, so the
    succeeded/partial/failed rule cannot drift between producers.

    >>> terminal_status(sample_count=4, error_count=0) is RunStatus.SUCCEEDED
    True
    >>> terminal_status(sample_count=4, error_count=1) is RunStatus.PARTIAL
    True
    >>> terminal_status(sample_count=4, error_count=4) is RunStatus.FAILED
    True
    >>> terminal_status(sample_count=0, error_count=0) is RunStatus.FAILED
    True
    """
    if sample_count == 0:
        # A run that produced no records at all measured nothing.
        return RunStatus.FAILED
    if error_count == 0:
        return RunStatus.SUCCEEDED
    if error_count >= sample_count:
        return RunStatus.FAILED
    return RunStatus.PARTIAL


class ServingStack(StrEnum):
    """*How* an endpoint is served.  Part of the reproducibility record.

    Per **D-1** every model -- hosted API, campus vLLM, laptop llama.cpp -- is
    reached through the same OpenAI-compatible surface.  This field records
    which implementation actually answered, because identical weights served by
    different stacks do not produce identical numbers.
    """

    OPENAI_API = "openai_api"
    ANTHROPIC_COMPAT = "anthropic_compat"
    VLLM = "vllm"
    OLLAMA = "ollama"
    LLAMA_CPP = "llama_cpp"
    MOCK = "mock"
    """The deterministic stand-in used by the tracer bullet and all tests."""


class Quantization(StrEnum):
    """Weight precision as served.  ``unknown`` is honest for hosted APIs."""

    NONE = "none"
    """Full precision as published (fp16/bf16)."""

    FP8 = "fp8"
    INT8 = "int8"
    INT4 = "int4"
    AWQ = "awq"
    GPTQ = "gptq"
    UNKNOWN = "unknown"
    """We are not told -- true for every hosted commercial API."""


# --------------------------------------------------------------------------
# Serving configuration (D-1)
# --------------------------------------------------------------------------


class SamplingParams(BaseModel):
    """Decoding parameters sent to the endpoint, recorded verbatim on results.

    Defaults are the *benchmark* defaults, not the provider defaults: we want
    near-deterministic output so that re-running a task reproduces a number.
    """

    model_config = ConfigDict(extra="forbid")

    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.0
    top_p: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0
    max_tokens: Annotated[int, Field(ge=1, le=131_072)] = 1024
    seed: int | None = None
    """Passed through when the endpoint supports it (vLLM does, most APIs do not)."""

    stop: list[str] = Field(default_factory=list)


class ServingConfig(BaseModel):
    """The complete, self-contained description of *what answered the prompt*.

    This is the D-1 payload.  It is embedded in every :class:`ResultRecord` by
    value.  If you add a field here you must also add it to the ``results``
    table's ``serving_config`` JSON blob -- which happens automatically,
    because that column stores this model's ``model_dump()``.
    """

    model_config = ConfigDict(extra="forbid")

    model_id: str
    """The id sent in the request body, e.g. ``mock-echo-1`` or ``claude-sonnet-4``."""

    registry_key: str = ""
    """The ``models.yaml`` key this config was resolved from.  Provenance, not identity.

    Derived, not authored: ``models.yaml`` omits it and :class:`ModelEntry`
    fills it in from the entry's ``key``.  Empty string means "constructed
    outside the registry" (a hand-built config in a test).
    """

    serving_stack: ServingStack
    serving_version: str | None = None
    """Version of the serving stack, e.g. ``vllm 0.6.3``.  ``None`` when unreported."""

    quantization: Quantization = Quantization.UNKNOWN
    revision: str | None = None
    """Weight revision/commit (HF revision, provider snapshot date).  ``None`` if opaque."""

    context_window: int | None = None
    sampling: SamplingParams = Field(default_factory=SamplingParams)
    hardware: str | None = None
    """Free text, e.g. ``2x DGX Spark GB10``.  ``None`` for hosted APIs."""

    extra: dict[str, Any] = Field(default_factory=dict)
    """Escape hatch for stack-specific knobs.  Recorded, never interpreted."""


class CostRates(BaseModel):
    """USD per *million* tokens.  Zero for self-hosted models."""

    model_config = ConfigDict(extra="forbid")

    input_usd_per_mtok: Annotated[float, Field(ge=0.0)] = 0.0
    output_usd_per_mtok: Annotated[float, Field(ge=0.0)] = 0.0


# --------------------------------------------------------------------------
# Model registry (models.yaml)
# --------------------------------------------------------------------------


class ModelEntry(BaseModel):
    """One entry in ``models.yaml``.

    Per **D-1** there is no per-provider branching anywhere in the codebase:
    a model is a base URL, an API key reference and a serving config.  Adding
    a campus vLLM deployment is a YAML edit, not a code change.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    """Stable registry key.  Referenced by ``RunRequest.model_keys``."""

    display_name: str
    base_url: str
    """OpenAI-compatible base, *including* ``/v1``.  e.g. ``http://mock-model:8000/v1``.

    A literal, and therefore the FALLBACK.  Prefer :attr:`base_url_env` whenever
    the endpoint differs per environment -- see below.
    """

    base_url_env: str | None = None
    """Name of an env var that OVERRIDES :attr:`base_url` when set and non-empty.

    This is the credit/hardware safety switch, and it has to be env indirection
    rather than a literal because ONE image is promoted byte-identically across
    dev, staging and prod.  ``MOCK_MODEL_BASE_URL`` is patched per overlay --
    pointed at the in-cluster stub in dev and preview, and EMPTY in staging and
    prod -- and the chart's render test asserts both directions.  With only a
    literal here, that patch would have no effect and dev would resolve a
    docker-compose hostname.

    Same mechanism gives ``sparks-local`` its ``SPARKS_BASE_URL``, which is empty
    everywhere today (no egress route to campus), so selecting it fails fast with
    a clear message instead of hanging.

    Like :attr:`api_key_env` this holds the NAME of a variable, never a value.
    """

    api_key_env: str | None = None
    """Name of the env var holding the key.  ``None`` for unauthenticated endpoints.

    The value is **never** stored in YAML.  In-cluster the env var is projected
    from Vault; locally it comes from ``.env``.
    """

    serving: ServingConfig
    cost: CostRates = Field(default_factory=CostRates)
    timeout_s: Annotated[float, Field(gt=0)] = 120.0
    max_retries: Annotated[int, Field(ge=0, le=10)] = 3
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _has_somewhere_to_send_the_request(self) -> ModelEntry:
        """An entry with neither a literal endpoint nor a variable naming one is
        unusable, and the only honest time to say so is at load."""
        if not self.base_url and not self.base_url_env:
            raise ValueError(
                f"model {self.key!r} has neither base_url nor base_url_env; "
                "one of them must say where to send the request"
            )
        return self

    @model_validator(mode="after")
    def _registry_key_matches(self) -> ModelEntry:
        """``serving.registry_key`` is derived, so keep it honest."""
        if self.serving.registry_key != self.key:
            # Normalise rather than reject: the field is derived, so an author
            # who omits it (the documented case) or mistypes it gets the
            # correct value rather than a validation error about a field they
            # were told not to write.
            self.serving.registry_key = self.key
        return self


class ModelRegistry(BaseModel):
    """Parsed ``models.yaml``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    models: list[ModelEntry]

    @model_validator(mode="after")
    def _keys_unique(self) -> ModelRegistry:
        keys = [m.key for m in self.models]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"duplicate model keys in registry: {sorted(dupes)}")
        return self

    def get(self, key: str) -> ModelEntry:
        """Look up by registry key.  Raises ``KeyError`` if absent."""
        for entry in self.models:
            if entry.key == key:
                return entry
        raise KeyError(f"no model with key {key!r} in registry")

    def enabled_keys(self) -> list[str]:
        return [m.key for m in self.models if m.enabled]


# --------------------------------------------------------------------------
# Tasks (tasks/**/*.yaml)
# --------------------------------------------------------------------------


class Normalisation(BaseModel):
    """How a completion is massaged before an exact/numeric comparison.

    Kept explicit and per-task rather than hidden in the scorer, because
    "we stripped trailing punctuation" is exactly the kind of silent decision
    that makes two labs' numbers incomparable.
    """

    model_config = ConfigDict(extra="forbid")

    strip: bool = True
    lowercase: bool = False
    collapse_whitespace: bool = True
    strip_punctuation: bool = False
    take_last_line: bool = False
    """Useful when the model reasons first and answers on the final line."""


class ScorerSpec(BaseModel):
    """Which scorer runs, and with what knobs."""

    model_config = ConfigDict(extra="forbid")

    kind: ScorerKind
    tolerance: Annotated[float, Field(ge=0.0)] = 0.0
    """``numeric_match`` only: absolute tolerance ``|got - want| <= tolerance``."""

    relative_tolerance: Annotated[float, Field(ge=0.0)] = 0.0
    """``numeric_match`` only: additionally allow ``|got-want| <= rel * |want|``."""

    normalisation: Normalisation = Field(default_factory=Normalisation)
    rubric_id: str | None = None
    """``llm_judge`` only: which rubric under ``rubric`` grades this task."""

    @model_validator(mode="after")
    def _numeric_scorers_reject_punctuation_stripping(self) -> ScorerSpec:
        """``strip_punctuation`` is incompatible with numeric scoring.

        ``string.punctuation`` contains ``.`` and ``,``, so stripping it turns
        ``"3.5"`` into ``"35"`` and ``"1,234.5"`` into ``"12345"``.  A task
        author who enabled the flag on a numeric task previously got a silent
        ``0.0`` on every correct decimal answer -- no error, no warning, the
        model simply looked worse than it was.  In a platform whose output is a
        recommendation backed by evidence, that is data corruption.

        We reject it at validation time rather than silently ignoring the flag:
        the author asked for something that cannot be honoured, and the honest
        answer is to say so where they can see it (CI, ``make lint-tasks``).
        """
        if self.kind is ScorerKind.NUMERIC_MATCH and self.normalisation.strip_punctuation:
            raise ValueError(
                "scorer.normalisation.strip_punctuation is not allowed with "
                "kind=numeric_match: '.' and ',' are numerically significant, so "
                "stripping punctuation would turn '3.5' into '35' and score correct "
                "answers as wrong. Remove strip_punctuation, or use exact_match."
            )
        return self


class Rubric(BaseModel):
    """A judging rubric.  Loaded and validated today; *applied* in a later phase."""

    model_config = ConfigDict(extra="forbid")

    id: str
    criteria: list[RubricCriterion]
    scale_min: float = 0.0
    scale_max: float = 1.0


class RubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    weight: Annotated[float, Field(gt=0.0)] = 1.0


class TaskSample(BaseModel):
    """One prompt/answer pair inside a task.

    ``target`` is required for ``verifiable`` tasks and forbidden for
    ``subjective`` ones -- enforced on :class:`TaskSpec`, not here, because
    only the task knows its kind.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    """Unique within the task.  Appears in artifact paths, so keep it path-safe."""

    input: str
    """The user message sent to the model."""

    target: str | None = None
    """Gold answer.  ``verifiable`` tasks only."""

    metadata: dict[str, Any] = Field(default_factory=dict)


def content_sha_of(document: Any) -> str:
    """SHA-256 of a parsed document, canonicalised (B8).

    Canonical JSON with sorted keys and no whitespace, so the hash is a function
    of *content* rather than of formatting: reindenting the YAML, reordering
    mapping keys or editing a comment all leave it unchanged.

    >>> content_sha_of({"a": 1, "b": 2}) == content_sha_of({"b": 2, "a": 1})
    True
    """
    import hashlib
    import json

    blob = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


_METADATA_NUMBER = re.compile(r"(?<![0-9A-Za-z._-])[-+]?\d+(?:\.\d+)?(?![0-9A-Za-z])")
"""A number in a metadata string, ignoring digits that are part of a word.

The lookarounds are the whole point.  Sample metadata is full of identifiers
that contain digits -- ``ladder-l3``, ``interest-v2``, ``mirrors:
l4-distribution-key`` -- and a bare ``\d+`` would read the ``4`` out of
``l4-distribution-key`` and report a task whose target is ``4`` as leaking.  A
digit glued to a letter is part of a name, not a value.
"""


def _metadata_scalars(value: Any) -> list[Any]:
    """Every scalar reachable from a metadata value, including dict keys."""
    if isinstance(value, dict):
        out: list[Any] = []
        for key, item in value.items():
            out.append(key)
            out.extend(_metadata_scalars(item))
        return out
    if isinstance(value, (list, tuple, set)):
        return [scalar for item in value for scalar in _metadata_scalars(item)]
    return [value]


def _target_leaks_into_metadata(target: str, metadata: dict[str, Any]) -> str | None:
    """Return a human-readable reason if ``target`` is recoverable from ``metadata``.

    **Why this rule exists.**  ``GET /tasks/{id}`` redacts every ``target``
    unless the caller holds the ``author`` role -- publishing the answer key is
    both an integrity risk (anyone can tune against it) and a contamination one
    (a scraped key reaches a future training corpus).  But that same endpoint
    returns ``sample.metadata`` **verbatim, to everyone, unauthenticated**
    (``ida_api.schemas.SampleView``).  An author who writes the derivation into
    ``metadata`` therefore hands out exactly what the redaction exists to
    protect, and nothing used to say so.  Derivations belong in YAML comments,
    which are not parsed, not part of ``content_sha``, and never served.

    **What this catches**: the target as a standalone value or token in any
    metadata scalar (recursively, keys included), and -- for numeric targets --
    the same value written in another format (``7.50`` for ``7.5``, ``+3`` for
    ``3``).

    **What this does NOT catch, honestly.**  It is a tripwire, not a proof:

    * a derivation that yields the answer without stating it
      (``{working: "sum=70, n=5"}`` for a target of ``14``);
    * the answer in words (``{note: "forty-two"}``);
    * the answer in a *different* sample's metadata, or in ``description``,
      ``title`` or ``tags``;
    * an answer a reader can infer from a hint (``{note: "answer is negative"}``).

    Passing this check is not evidence that a task keeps its key secret.  The
    rule exists to make the common, mechanical mistake impossible to commit.
    """
    scalars = _metadata_scalars(metadata)
    stripped = target.strip()
    if not stripped:
        return None
    folded = stripped.casefold()

    for scalar in scalars:
        if isinstance(scalar, str) and scalar.strip().casefold() == folded:
            return f"a metadata value is exactly the target ({stripped!r})"

    try:
        wanted = float(stripped)
    except ValueError:
        # Non-numeric target (exact_match): a standalone-token match is a leak.
        pattern = re.compile(rf"(?<![0-9A-Za-z_]){re.escape(stripped)}(?![0-9A-Za-z_])", re.I)
        for scalar in scalars:
            if isinstance(scalar, str) and pattern.search(scalar):
                return f"a metadata value contains the target {stripped!r}"
        return None

    for scalar in scalars:
        if isinstance(scalar, bool):
            continue
        if isinstance(scalar, (int, float)) and float(scalar) == wanted:
            return f"a metadata value is numerically the target ({stripped!r})"
        if isinstance(scalar, str):
            for found in _METADATA_NUMBER.findall(scalar):
                try:
                    if float(found) == wanted:
                        return (
                            f"a metadata value contains the target as a number "
                            f"({found!r} == {stripped!r})"
                        )
                except ValueError:  # pragma: no cover - regex guarantees parseability
                    continue
    return None


class TaskSpec(BaseModel):
    """A parsed task YAML.  The unit of benchmarking work.

    Authoring conventions live in ``tasks/SCHEMA.md``; the machine-checkable
    subset lives in ``ida_core/schemas/task.schema.json`` and is enforced in CI
    by the ``task-schema`` job in ``.github/workflows/ci.yml``.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    id: str
    """Globally unique task id, e.g. ``demo/arithmetic-quiz-check``."""

    title: str
    description: str = ""
    kind: TaskKind
    domain: str = "general"
    """Academic domain, e.g. ``statistics``, ``history``.  Used by the recommender (D-3)."""

    system_prompt: str | None = None
    scorer: ScorerSpec
    rubric: Rubric | None = None
    samples: list[TaskSample] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    content_sha: str = ""
    """SHA-256 of the canonicalised task document (B8).  **Derived, never authored.**

    Set by :meth:`from_document` (which is what the loader uses); the JSON
    Schema forbids the key in a task file.  Empty string means "constructed
    in-memory rather than loaded from a file".

    Computed over the *parsed* document rendered as canonical JSON, so
    reformatting the YAML or editing a comment does not change it -- only a
    change to the task's actual content does.  That is what makes it usable
    both as a comparability key and as a cache key.
    """

    @model_validator(mode="after")
    def _taxonomy_consistency(self) -> TaskSpec:
        """Enforce the verifiable/subjective axis.

        * ``verifiable`` -> programmatic scorer, every sample has a ``target``,
          no rubric.
        * ``subjective`` -> ``llm_judge`` scorer, a rubric, no ``target``s.
        """
        programmatic = {ScorerKind.EXACT_MATCH, ScorerKind.NUMERIC_MATCH}
        if self.kind is TaskKind.VERIFIABLE:
            if self.scorer.kind not in programmatic:
                raise ValueError(
                    f"verifiable task {self.id!r} must use a programmatic scorer, "
                    f"got {self.scorer.kind!r}"
                )
            missing = [s.id for s in self.samples if s.target is None]
            if missing:
                raise ValueError(
                    f"verifiable task {self.id!r} has samples without a target: {missing}"
                )
            if self.rubric is not None:
                raise ValueError(f"verifiable task {self.id!r} must not carry a rubric")
        else:
            if self.scorer.kind is not ScorerKind.LLM_JUDGE:
                raise ValueError(
                    f"subjective task {self.id!r} must use the {ScorerKind.LLM_JUDGE!r} scorer"
                )
            if self.rubric is None:
                raise ValueError(f"subjective task {self.id!r} must carry a rubric")
            if self.scorer.rubric_id != self.rubric.id:
                raise ValueError(
                    f"task {self.id!r}: scorer.rubric_id {self.scorer.rubric_id!r} "
                    f"does not match rubric.id {self.rubric.id!r}"
                )
            targets = [s.id for s in self.samples if s.target is not None]
            if targets:
                raise ValueError(f"subjective task {self.id!r} must not carry targets: {targets}")
        sample_ids = [s.id for s in self.samples]
        dupes = {i for i in sample_ids if sample_ids.count(i) > 1}
        if dupes:
            raise ValueError(f"task {self.id!r} has duplicate sample ids: {sorted(dupes)}")
        return self

    @model_validator(mode="after")
    def _targets_do_not_leak_into_metadata(self) -> TaskSpec:
        """A gold answer must not be recoverable from its own sample's metadata.

        Targets are redacted by ``GET /tasks/{id}``; ``metadata`` is not.  A
        derivation written into ``metadata`` therefore publishes the answer key
        the redaction exists to protect -- see
        :func:`_target_leaks_into_metadata` for what this does and does not
        catch.  Put derivations in YAML comments instead.

        Enforced here rather than in the JSON Schema because it is a
        data-dependent cross-field rule the schema cannot express, and enforced
        in ``ida_core`` rather than in ``tools/validate_tasks.py`` so that it
        binds everywhere a task is loaded -- the CI ``task-schema`` job, the
        harness catalog, and API startup -- not only when someone runs the CLI.
        """
        leaks = []
        for sample in self.samples:
            if sample.target is None or not sample.metadata:
                continue
            reason = _target_leaks_into_metadata(sample.target, sample.metadata)
            if reason is not None:
                leaks.append(f"{sample.id}: {reason}")
        if leaks:
            raise ValueError(
                f"task {self.id!r} leaks gold answers through sample metadata "
                f"(metadata is served unauthenticated while targets are redacted; "
                f"move the derivation into a YAML comment): " + "; ".join(leaks)
            )
        return self

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> TaskSpec:
        """Validate a parsed task document and stamp its content hash.

        This is how tasks should be constructed from files -- plain
        ``model_validate`` leaves :attr:`content_sha` empty.
        """
        spec = cls.model_validate(document)
        spec.content_sha = content_sha_of(document)
        return spec

    @property
    def is_scorable(self) -> bool:
        """False for ``subjective`` tasks until the judge lands.

        The API and the UI surface this so a subjective task shows as
        *loaded, validated, not yet scorable* rather than silently failing.
        """
        return self.kind is TaskKind.VERIFIABLE


Rubric.model_rebuild()


# --------------------------------------------------------------------------
# Run request / queue message
# --------------------------------------------------------------------------


class RunRequest(BaseModel):
    """What a caller POSTs to ``/runs`` to start work.

    The cross product ``task_ids x model_keys`` defines the work.  In the
    skeleton the API expands that product into exactly one queue message per
    (task, model) pair.
    """

    model_config = ConfigDict(extra="forbid")

    task_ids: Annotated[list[str], Field(min_length=1, max_length=MAX_SWEEP_DIMENSION)]
    model_keys: Annotated[list[str], Field(min_length=1, max_length=MAX_SWEEP_DIMENSION)]
    label: str | None = None
    """Human-facing note, e.g. ``"pre-registration sweep"``."""

    sampling_override: SamplingParams | None = None
    """Overrides the registry's sampling params for this run only.

    The *effective* params are what land in the result's serving config, so an
    override never hides behind the registry default.
    """

    @model_validator(mode="after")
    def _dedupe_and_bound(self) -> RunRequest:
        """Drop duplicates (order-preserving) and cap the cross product.

        Both matter because this endpoint spends money.  ``{"task_ids": ["X",
        "X"], "model_keys": ["m", "m"]}`` previously enqueued four identical
        runs and billed four times; and with no ceiling, one unauthenticated
        request for 100 tasks x 50 models would commit 5 000 rows and 5 000
        queue messages. On a shared campus platform with a real API key
        attached, that is an accidental budget event.
        """
        self.task_ids = list(dict.fromkeys(self.task_ids))
        self.model_keys = list(dict.fromkeys(self.model_keys))
        total = len(self.task_ids) * len(self.model_keys)
        if total > MAX_SWEEP_RUNS:
            raise ValueError(
                f"this request expands to {total} runs "
                f"({len(self.task_ids)} tasks x {len(self.model_keys)} models), "
                f"which exceeds the ceiling of {MAX_SWEEP_RUNS}. Split it, or raise "
                "MAX_SWEEP_RUNS deliberately."
            )
        return self


class RunJobMessage(BaseModel):
    """**The queue contract.**  api -> Redis -> runner.  Versioned; JSON on the wire.

    Transport: a Redis list used as a FIFO queue.  The API ``RPUSH``es the JSON
    body onto :data:`ida_core.queue.RUN_QUEUE_KEY`; runners ``BLPOP`` it.  There
    is no ack/retry in the skeleton -- a runner that dies loses its message, and
    the run stays ``running``.  That is a known, documented gap (see
    ``ida_core.queue`` module docstring) and the first thing a durability pass
    should fix.

    Compatibility rule: ``schema_version`` is bumped on any change that is not
    additive-with-default.  A runner **must** refuse a message whose
    ``schema_version`` it does not know rather than guess.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str
    """Minted by the API (:func:`ida_core.ids.new_run_id`) *before* enqueue."""

    task_id: str
    model_key: str

    sweep_id: str | None = None
    """The sweep this run belongs to (B9).

    Additive-with-default, so adding it did **not** require a
    ``schema_version`` bump: a runner that predates the field parses a message
    carrying it, and a runner that expects it tolerates a message without it.
    That is the compatibility rule this envelope exists to make explicit.
    """
    sampling_override: SamplingParams | None = None
    enqueued_at: datetime
    attempt: Annotated[int, Field(ge=1)] = 1
    """1-based.  Reserved for a future retry policy; always 1 in the skeleton."""

    def to_wire(self) -> str:
        """Serialise to the exact bytes that go on the queue."""
        return self.model_dump_json()

    @classmethod
    def from_wire(cls, payload: str | bytes) -> RunJobMessage:
        """Parse a queue payload, refusing unknown schema versions loudly."""
        text = payload.decode() if isinstance(payload, bytes) else payload
        return cls.model_validate_json(text)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


class TokenUsage(BaseModel):
    """Token accounting for a single completion, as reported by the endpoint."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: Annotated[int, Field(ge=0)] = 0
    completion_tokens: Annotated[int, Field(ge=0)] = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )

    def cost_usd(self, rates: CostRates) -> float:
        """Cost of this usage under ``rates``.  Zero for self-hosted models."""
        return (
            self.prompt_tokens * rates.input_usd_per_mtok
            + self.completion_tokens * rates.output_usd_per_mtok
        ) / 1_000_000


class CriterionScore(BaseModel):
    """One rubric criterion's contribution to a judged :class:`Score`.

    Exists so that a four-criterion rubric is not collapsed into a single float
    before anyone can read it.  "specificity 0.4, tone 0.9" is precisely what a
    professor reviewing a recommendation wants to see; "0.58" is not.

    Populated by the LLM judge when it lands (see
    :class:`ida_harness.scoring.LLMJudgeScorer`); empty for programmatic scorers.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    """Must match a :attr:`RubricCriterion.name` on the task's rubric."""

    value: Annotated[float, Field(ge=0.0, le=1.0)]
    weight: Annotated[float, Field(gt=0.0)] = 1.0
    """Copied from the rubric so the weighted total is reconstructible."""

    explanation: str = ""
    """The judge's justification for this criterion specifically."""


class Score(BaseModel):
    """A scorer's verdict on one sample.

    ``value`` is always in ``[0, 1]`` so that scores from different scorers
    aggregate.
    """

    model_config = ConfigDict(extra="forbid")

    scorer: ScorerKind
    value: Annotated[float, Field(ge=0.0, le=1.0)]

    passed: bool | None = None
    """The binary reading, or ``None`` when a binary reading is not meaningful.

    Verifiable scorers set it: exact/numeric matching is genuinely pass/fail.
    A rubric-weighted judge score is inherently graded, and forcing it through a
    threshold would invent a cutoff nobody chose -- so the judge leaves this
    ``None`` and consumers use :attr:`value`.  ``None`` means "this scorer does
    not make a pass/fail claim", which is different from ``False``.
    """

    explanation: str = ""
    """Why.  For programmatic scorers this is the normalised got/want pair."""

    criteria: list[CriterionScore] = Field(default_factory=list)
    """Per-criterion breakdown.  Empty for programmatic scorers."""

    details: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """One OpenAI-compatible chat message."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class SampleTranscript(BaseModel):
    """The full interaction for one sample.  Archived to object storage, not Postgres.

    Postgres holds the *pointer* (:attr:`ResultRecord.transcript_uri`) and the
    score; the bytes live in MinIO/S3 under the path convention in
    :mod:`ida_core.artifacts`.  Rationale: transcripts are large, append-only,
    and never queried relationally.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    sample_id: str
    model_key: str
    messages: list[ChatMessage]
    completion: str
    usage: TokenUsage
    latency_ms: float
    request_id: str | None = None
    """Provider-side request id when supplied.  Useful for support tickets."""

    raw_response: dict[str, Any] = Field(default_factory=dict)
    """Verbatim provider JSON, minus the API key.  Kept for post-hoc forensics."""


class ResultRecord(BaseModel):
    """**One scored sample.**  The durable unit the UI and the recommender read.

    Every field needed to reproduce and to *cite* the number is present on the
    record itself (D-1, and D-3's evidence-traceability requirement): serving
    config by value, task git SHA, transcript pointer, token + cost accounting.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    task_id: str
    sample_id: str

    repeat_index: Annotated[int, Field(ge=0)] = 0
    """Which repetition of this sample this is.  0-based; 0 for a single run.

    Reserved for repeated sampling -- self-consistency, pass@k, variance at
    temperature > 0 -- the strategies :mod:`ida_harness.solver` exists to make
    possible.  The skeleton always emits 0, but uniqueness is
    ``(run_id, sample_id, repeat_index)`` and the transcript key includes it,
    so turning repetition on later needs no migration and no break in a path
    convention documented as stable.
    """

    model_key: str
    serving_config: ServingConfig
    """Copied by value -- see the D-1 note in this module's docstring.

    This describes the model **under test**.  A judged result additionally
    carries :attr:`judge_serving_config`.
    """

    judge_serving_config: ServingConfig | None = None
    """The model that *graded* this sample, when one did -- D-1 applied to the grade.

    A judged result has two models, and swapping the judge (or changing its
    temperature) moves the score just as surely as changing the model under
    test does.  So the judge's config gets the same by-value treatment and its
    own queryable column, rather than being buried in :attr:`Score.details`
    where it would sit outside the D-1 guarantee, be unqueryable without a JSON
    scan, and be invisible to the UI.

    ``None`` for programmatic scorers and for the not-yet-scored subjective
    samples the skeleton produces.
    """

    task_content_sha: str | None = None
    """SHA-256 of this task's canonicalised definition.

    Finer-grained than :attr:`RunRecord.task_git_sha`, which is a whole-repo SHA
    and therefore changes on every unrelated commit.  This answers the question
    the repo SHA cannot: *are these two runs of the same task comparable?*
    """

    score: Score | None = None
    """``None`` when the sample errored, or when the task is not yet scorable."""

    scorable: bool = True
    """False for ``subjective`` samples in the skeleton (no judge yet).

    Read together with :attr:`error`, this distinguishes the two very different
    reasons :attr:`score` can be ``None``::

        scorable=False, error=None    not-yet-scorable (subjective task)
        scorable=True,  error="..."   the sample failed; nothing was measured

    Collapsing those into "score is null" is what let an earlier revision
    describe a run of failed API calls as a subjective task.  **Consumers must
    branch on these two fields, never on score nullity alone.**
    """

    cached: bool = False
    """True when the completion came from the cache rather than the endpoint.

    A cached result is a real result -- it was scored, and its transcript is
    faithful -- but it incurred no latency and cost no money on *this* run.
    :attr:`latency_ms` and :attr:`cost_usd` are therefore 0.0 on a hit, and this
    flag is what lets the UI say "cached" instead of reporting a measurement
    that never happened.
    """

    usage: TokenUsage = Field(default_factory=TokenUsage)
    """Tokens the underlying call consumed.  Retained on a cache hit for
    reproducibility -- but see :attr:`cost_usd`; they were not re-purchased."""

    cost_usd: Annotated[float, Field(ge=0.0)] = 0.0
    """Money actually spent producing *this* record.  0.0 on a cache hit."""

    latency_ms: Annotated[float, Field(ge=0.0)] = 0.0
    """Wall-clock actually observed on *this* run.  0.0 on a cache hit."""

    transcript_uri: str | None = None
    """``s3://<bucket>/<key>`` pointer built by :mod:`ida_core.artifacts`."""

    archive_error: str | None = None
    """Set when the transcript could not be archived though the sample succeeded.

    The completion was paid for and scored; only the evidence pointer is
    missing.  Recording that is strictly better than discarding the work.
    """

    error: str | None = None
    """Set when the sample failed; ``score`` is then ``None``."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunRecord(BaseModel):
    """A run: one (task, model) pair's worth of work, plus its rollup.

    A ``RunRequest`` covering 3 tasks x 2 models produces **6** ``RunRecord``s.
    Keeping the grain at (task, model) means a slow model cannot block the
    display of a fast one, and a partial failure is isolated.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    status: RunStatus
    task_id: str
    model_key: str
    label: str | None = None

    sweep_id: str | None = None
    """Groups every run minted by one ``POST /runs`` (B9).

    A benchmarking platform's core question is "how do these models compare on
    these tasks", and a request for 3 tasks x 2 models produces 6 independent
    runs.  Without a shared id the only thread between them is the free-text
    ``label``, so the comparison view would have to string-match.  Minted
    server-side at enqueue; ``None`` only for rows created by other means.
    """

    task_git_sha: str | None = None
    """Git SHA of the repo when the task/rubric was read (D-1).  ``None`` outside git."""

    task_content_sha: str | None = None
    """SHA-256 of the task's canonicalised definition.  See
    :attr:`ResultRecord.task_content_sha` -- this is the comparability key."""

    harness_version: str
    """``ida_harness.__version__`` that executed the run."""

    serving_config: ServingConfig | None = None
    """Resolved at claim time; ``None`` while still ``queued``."""

    sample_count: int = 0

    scored_count: int = 0
    """Samples that produced a :class:`Score`."""

    error_count: int = 0
    """Samples that failed outright (B5).

    Without this, ``scored_count < sample_count`` is ambiguous between "some
    calls to the model failed" and "this task is not scorable yet" -- two
    situations that must never be confused.  The UI needs the distinction to
    avoid describing a broken run as a subjective one, and the recommendation
    engine (D-3) needs it so an outage is not recorded as "no data for this
    model".  :attr:`status` is derived from it via :func:`terminal_status`.
    """

    mean_score: float | None = None
    """Mean of ``score.value`` over scored samples.  ``None`` if nothing scored.

    On a ``partial`` run this is a mean over the *surviving* samples: errored
    samples are excluded rather than counted as zero, because our outage is not
    the model's failure.  :attr:`error_count` is what tells you how much of the
    task the number actually covers.
    """

    total_usage: TokenUsage = Field(default_factory=TokenUsage)
    total_cost_usd: float = 0.0
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunDetail(BaseModel):
    """API response for ``GET /runs/{run_id}``: the run plus a page of results."""

    model_config = ConfigDict(extra="forbid")

    run: RunRecord
    results: list[ResultRecord]

    results_total: int
    """Results this run has, ignoring pagination.

    Load-bearing, not decorative. ``results`` alone cannot distinguish a run
    that produced nothing from a page requested past the end, and the UI
    classifies those differently -- an empty result set reads as *all errored*
    (``frontend/src/lib/outcome.ts``). A client comparing ``len(results)`` with
    ``results_total`` can also tell that it is looking at a partial view before
    it draws a conclusion from it.
    """

    results_limit: int
    results_offset: int


class EvalLog(BaseModel):
    """The harness's structured output for one (task, model) pair.

    Deliberately mirrors the "structured eval log" concept from Inspect AI
    (**D-4** -- we study the concepts, we import nothing).  The runner persists
    a ``RunRecord`` + N ``ResultRecord``s from this, and archives the whole log
    to object storage so a run is replayable from artifacts alone.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    task_git_sha: str | None
    task_content_sha: str | None = None
    sweep_id: str | None = None
    model_key: str
    serving_config: ServingConfig
    harness_version: str
    status: RunStatus
    results: list[ResultRecord]
    transcripts: list[SampleTranscript]
    started_at: datetime
    finished_at: datetime
    error: str | None = None

    @property
    def mean_score(self) -> float | None:
        """Mean over *scored* samples.  ``None`` if nothing scored.

        Errored samples are excluded rather than counted as zero: a failed HTTP
        call is our outage, not the model's wrong answer, and scoring it 0 would
        defame the model for our infrastructure.  :attr:`error_count` is how a
        consumer learns how much of the task the mean covers.
        """
        values = [r.score.value for r in self.results if r.score is not None]
        return sum(values) / len(values) if values else None

    @property
    def error_count(self) -> int:
        """Samples that failed outright (B5)."""
        return sum(1 for r in self.results if r.error is not None)

    @property
    def scored_count(self) -> int:
        return sum(1 for r in self.results if r.score is not None)

    def error_summary(self) -> str | None:
        """A one-line summary of what went wrong, or ``None`` if nothing did.

        Deliberately reports the *distinct* error types and a representative
        message rather than concatenating N identical stack traces -- a run
        where all 500 samples hit the same dead endpoint should read as one
        problem, because it is one problem.
        """
        errors = [r.error for r in self.results if r.error]
        if not errors:
            return None
        distinct = sorted(set(errors))
        head = distinct[0]
        if len(distinct) == 1:
            return f"{len(errors)}/{len(self.results)} samples failed: {head}"
        return (
            f"{len(errors)}/{len(self.results)} samples failed with "
            f"{len(distinct)} distinct errors; first: {head}"
        )

    @property
    def total_usage(self) -> TokenUsage:
        total = TokenUsage()
        for result in self.results:
            total = total + result.usage
        return total
