"""Shared settings.  One class, read by api, runner, sweeps and the tracer bullet.

Everything is env-driven (12-factor) because in-cluster the values arrive as env
vars: non-secret ones from the ConfigMap ``ida-llm-config``, secret ones from
Vault via ESO.  Nothing here has a secret as a *default*; secrets default to
empty and the service fails loudly if it needs one.

TWO NAMING CONVENTIONS, DELIBERATELY
------------------------------------
The platform supplies its seven values **unprefixed** -- ``DATABASE_URL``,
``REDIS_URL``, ``LOG_LEVEL``, ``MINIO_*`` -- via ``envFrom: configMapRef`` and
``secretKeyRef``.  A bare ``env_prefix="IDA_"`` would see **none** of them, and
the failure is silent: every field quietly keeps its default and the pod serves
against ``postgres:5432`` while reporting Ready.

So the seven the platform actually writes are **dual-aliased**: ``IDA_``-prefixed
first (local dev, tests, docker-compose), platform name second.  Everything else
stays ``IDA_``-only because it has no ConfigMap entry and defaults correctly
inside the image.

If you add a setting, add it in THREE places or it works locally and is missing
in the cluster: here, ``.env.example``, and the ConfigMap or the ExternalSecret.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Safe: ida_core.queue imports only ida_core.contracts, which imports nothing
# from this package, so there is no cycle -- and the defaults stay defined once,
# next to the code that reasons about them.
from ida_core.queue import DEFAULT_HEARTBEAT_TTL_S, DEFAULT_MAX_ATTEMPTS

_LOG_LEVELS = frozenset({"CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG"})
"""The names `logging` accepts. NOTSET is deliberately excluded: it means
"inherit", which is not a meaningful thing to configure a service to."""


def repo_root() -> Path:
    """Best-effort monorepo root.

    Resolution order: ``IDA_REPO_ROOT`` env (set to /app in the image) -> walk up
    from this file looking for ``models.yaml`` + ``tasks/``.  Returns the cwd as
    a last resort rather than raising, so imports never explode.
    """
    explicit = os.environ.get("IDA_REPO_ROOT")
    if explicit:
        return Path(explicit)
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "models.yaml").exists() and (candidate / "tasks").is_dir():
            return candidate
    return Path.cwd()


def normalize_database_url(database_url: str) -> str:
    """Force the psycopg3 driver onto a bare ``postgresql://`` DSN.

    ESO assembles ``DATABASE_URL`` from the Crossplane-provisioned parts and
    writes a bare ``postgresql://`` scheme.  SQLAlchemy 2.x maps that to
    **psycopg2**, which this image deliberately does not ship (the runtime pins
    ``psycopg[binary]`` so nothing ever has to compile libpq).

    ⚠ ONE HELPER, BOTH CALLERS.  The failure this prevents already happened once
    on this platform: the migration normalised the scheme and the app did not, so
    the schema migrated cleanly while the API could not connect at all.  Both
    :func:`ida_core.db.make_engine` and ``migrations/env.py`` route through here.
    """
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Settings(BaseSettings):
    """Runtime configuration for every Python service."""

    model_config = SettingsConfigDict(
        env_prefix="IDA_", env_file=".env", extra="ignore", case_sensitive=False
    )

    # ── platform-supplied (dual-aliased: IDA_ first, then the ConfigMap name) ──

    database_url: str = Field(
        "postgresql+psycopg://ida:ida@postgres:5432/ida",
        validation_alias=AliasChoices("IDA_DATABASE_URL", "DATABASE_URL"),
    )
    """SQLAlchemy URL.  Tests override with ``sqlite+pysqlite:///:memory:``."""

    redis_url: str = Field(
        "redis://redis:6379/0",
        validation_alias=AliasChoices("IDA_REDIS_URL", "REDIS_URL"),
    )

    log_level: str = Field("INFO", validation_alias=AliasChoices("IDA_LOG_LEVEL", "LOG_LEVEL"))
    """Normalised to UPPER CASE -- see the validator below. The platform writes
    lower case (`LOG_LEVEL: info` in the ConfigMap; `.env.example` documents
    "one of: debug, info, warning, error") and `logging.basicConfig` accepts
    only the upper-case names."""

    s3_bucket: str = Field(
        "run-artifacts", validation_alias=AliasChoices("IDA_S3_BUCKET", "MINIO_BUCKET")
    )
    s3_access_key: str = Field(
        "", validation_alias=AliasChoices("IDA_S3_ACCESS_KEY", "MINIO_ACCESS_KEY")
    )
    s3_secret_key: str = Field(
        "", validation_alias=AliasChoices("IDA_S3_SECRET_KEY", "MINIO_SECRET_KEY")
    )

    host: str = Field("0.0.0.0", validation_alias=AliasChoices("IDA_HOST", "HOST"))  # noqa: S104
    """Bind address.  A loopback bind is invisible to kube-proxy AND to the
    kubelet's probes, so 0.0.0.0 inside a container is correct, not careless."""

    port: int = Field(8000, validation_alias=AliasChoices("IDA_PORT", "PORT"))
    """Each Deployment sets its own literal (api 8000, mock-model 8000)."""

    # ── the object store's split endpoint ──────────────────────────────────
    # The platform gives host/port/TLS as three ConfigMap keys, not one URL.
    # IDA_S3_ENDPOINT_URL still wins when set, so local dev and tests are
    # unchanged; otherwise the triple is composed.

    s3_endpoint_url_explicit: str = Field("", validation_alias=AliasChoices("IDA_S3_ENDPOINT_URL"))
    minio_endpoint: str = Field("", validation_alias=AliasChoices("MINIO_ENDPOINT"))
    minio_port: int = Field(9000, validation_alias=AliasChoices("MINIO_PORT"))
    minio_use_ssl: bool = Field(False, validation_alias=AliasChoices("MINIO_USE_SSL"))

    s3_region: str = "us-east-1"

    # ── app-internal (IDA_-only: no ConfigMap entry, correct default in-image) ──

    artifact_backend: Literal["s3", "local"] = "s3"
    """``s3`` (MinIO) or ``local``.  ``local`` uses :attr:`artifact_local_root`.

    A ``Literal``, not a ``str``, and the difference is a data-loss bug rather
    than a style preference.  Every consumer branches ``if artifact_backend ==
    "local": ... else: <s3>`` (``ida_api.deps``, ``ida_runner.main``,
    ``scripts.bootstrap``), so a typo -- ``IDA_ARTIFACT_BACKEND=locl`` -- did
    not fail: it fell through to the ``else`` and silently selected S3.  A
    developer who asked for local artifacts got writes attempted against
    object storage, and a deployment that meant to use S3 could be typo'd into
    the same silence in the other direction.

    Pydantic now rejects an unknown value at construction, so the process dies
    at startup naming the offending field instead of running with a backend
    nobody chose.
    """

    artifact_local_root: str = "/tmp/ida-artifacts"  # noqa: S108

    models_file: str = ""
    """Path to ``models.yaml``.  Empty -> ``repo_root()/models.yaml``."""

    tasks_dir: str = ""
    """Root of the task tree.  Empty -> ``repo_root()/tasks``."""

    runner_poll_timeout_s: int = 5
    """How long the runner blocks on the queue before re-checking for shutdown."""

    runner_metrics_port: int = 9100
    """The runner's /metrics listener.  9100 matches the container port the
    ServiceMonitor scrapes -- see services/runner/ida_runner/metrics.py."""

    # ── queue durability (see ida_core.queue) ─────────────────────────────
    # All IDA_-only with in-image defaults: the ConfigMap carries no entry for
    # any of them, so the defaults below ARE the deployed values until somebody
    # deliberately overrides one.

    queue_max_attempts: int = DEFAULT_MAX_ATTEMPTS
    """How many times a run job may be delivered before it is dead-lettered."""

    runner_heartbeat_interval_s: int = 30
    """How often a runner refreshes its liveness key while a job is in flight.

    Must stay comfortably below :attr:`runner_heartbeat_ttl_s`, or a runner
    working normally on a long job looks dead and its job gets duplicated."""

    runner_heartbeat_ttl_s: int = DEFAULT_HEARTBEAT_TTL_S
    """TTL on the liveness key.  3x the interval, so two missed refreshes are
    survivable."""

    reaper_interval_s: int = 60
    """How often each runner runs the recovery/stale-run pass.  Every replica
    does it; the pass is idempotent and lock-free (see ida_core.queue)."""

    stale_run_ttl_s: int = 21600
    """How long a run may sit ``running`` with nobody claiming it before it is
    closed out as ``failed``.

    Six hours, not minutes.  This is the LAST-RESORT backstop for a run whose
    claim record is gone entirely (Redis flushed, key evicted); the ordinary
    crash path is caught in seconds by claim recovery, which knows the truth
    rather than guessing from a clock.  A run that a live runner is still
    working on is never eligible however old it is -- see
    :meth:`ida_core.queue.RunQueue.live_claims`.  Erring long costs a delayed
    status update; erring short would report a healthy run as failed, which is
    the kind of false statement this platform exists to avoid.

    TWO CONSUMERS, ONE HORIZON.  The scheduled sweeps also read this to decide
    how long a ``queued`` row may be treated as "in flight" before it is assumed
    abandoned and its pair re-planned.  Deliberately the same value rather than a
    second knob: both answer the identical question -- how long before we stop
    believing a row that says work is in progress -- and two knobs that must
    agree are two knobs that will eventually disagree."""

    # ── scheduled sweeps (see services/runner/ida_runner/sweeps.py) ───────
    # IDA_-only with in-image defaults, same as the queue block above: the
    # ConfigMap carries no entry for any of them, so these defaults ARE the
    # deployed values. The three CronJobs run a FIXED argv, so an operator's only
    # lever in-cluster is the environment -- which is why the force switch is a
    # setting and not merely a CLI flag.

    sweep_max_runs: int = 200
    """Most runs one sweep may enqueue.  Beyond this the sweep REFUSES.

    Bounds queue pressure and blast radius: a dedupe regression that made every
    pair look un-measured would otherwise re-enqueue the whole cross product
    every night.  Sized well above a realistic registry x catalog (today: 2
    enabled models, of which 1 is swept -- ``luna`` is held back by
    :attr:`sweep_exclude_tags` -- x 8 scorable tasks = 8), so tripping it means
    something is wrong, not that the suite grew."""

    sweep_max_samples: int = 2000
    """Most *samples* one sweep may enqueue.  Beyond this the sweep REFUSES.

    The honest spend estimate, and the reason there are two caps rather than
    one.  A run is not a unit of cost; a sample is -- one sample is one provider
    call.  Ten runs of two hundred samples and two hundred runs of ten samples
    cost the same and look nothing alike to :attr:`sweep_max_runs`.  Known
    exactly (not estimated) at planning time, because ``len(spec.samples)`` is
    read from the task file the sweep is planning against."""

    sweep_exclude_tags: str = "testing-only"
    """Comma-separated ``models.yaml`` tags whose models scheduled sweeps SKIP.

    **The gap this closes.** Both nightly sweeps plan over
    ``registry.enabled_keys()``, so ``enabled: true`` means two different things
    at once: *an operator may select this model* and *a CronJob will select it
    every night, unattended*. Those are not the same permission, and conflating
    them is how a model enabled for one careful hand-run becomes a standing
    nightly bill.

    The live case is ``luna``, whose key is scoped to it with a **$25 hard cap
    for testing**. It must be selectable on purpose and must NOT be swept at
    02:00 -- ``model-sweep`` in particular exists to give a *newly enabled*
    model a first full set of numbers, which is precisely the unattended spend
    that budget cannot absorb.

    Tag-driven rather than a key list, so the decision travels with the entry in
    ``models.yaml`` instead of drifting in a second place -- the same reason
    ``serving_stack`` lives there. A sweep that holds a model back **says so**
    in its report and its log; a silently narrowed sweep would read as "the
    suite is fully measured" when it is not.

    Set to ``""`` to sweep every enabled model."""

    sweep_force: bool = False
    """Re-enqueue pairs that are already measured, ignoring dedupe.

    The deliberate credit-spending switch: a sweep normally skips a
    ``(task, model, task_content_sha)`` triple that already succeeded, which is
    what makes a nightly CronJob cheap and idempotent.  Off by default, and the
    budget caps still apply when it is on -- forcing a re-measurement is a
    decision about staleness, not permission to spend without limit."""

    sweep_judge_candidate_limit: int = 500
    """Most ungraded subjective samples one judge-calibration pass examines.

    Bounds the pass the same way :attr:`stale_run_ttl_s`'s query is bounded; the
    next night's firing picks up the remainder.  The sweep logs when it hits
    this bound so a truncated pass never reads as "that was all"."""

    judge_model_key: str = ""
    """``models.yaml`` key of the model that grades ``subjective`` tasks.

    **Empty by default, and that default is a decision.**  A judge is a second
    model call per criterion per sample; turning it on spends real money on every
    subjective run, so it must be an operator's explicit choice rather than
    something that starts happening because a feature merged.  Empty means
    subjective tasks stay ``scorable=False`` with their transcripts archived, and
    ``python -m ida_harness.regrade`` can grade them later.

    Any registry key works -- the judge goes through the same client factory as
    the model under test, so "who judges" is a YAML edit (D-13).
    """

    auth_mode: str = "disabled"
    """Which credential the API believes.  ``disabled`` (default) or ``token``.

    **D-5: there is still no auth *service*.**  Platform SSO/OIDC arrives later
    and the API consumes it through one dependency-injected seam
    (``ida_api.auth.current_principal``).  This flag selects what that seam does:

    ``disabled``  anonymous holds ``reader`` AND ``runner`` -- local dev, CI, the
                  tracer bullet.  The default, because every one of those runs
                  against the mock model and none of them can reach a provider.
    ``token``     anonymous holds ``reader`` ONLY.  Spending money needs a bearer
                  token from :attr:`auth_tokens`.  This is the deployed posture
                  once the API is routed publicly -- see
                  ``docs/sensitive-material.md`` section 6.
    anything else 501 at request time, loudly, rather than a half-implemented
                  mode that silently allows traffic.

    Reads stay anonymous in BOTH modes.  The public benchmark is the product; the
    thing being gated is *spend*, not *viewing* (D-49)."""

    auth_tokens: str = ""
    """Bearer tokens that grant the ``runner`` role, as ``subject:token`` pairs.

    **A SECRET.**  Empty default, like every other secret here -- it arrives from
    Vault via ESO in-cluster and from ``.env`` locally, never from a default and
    never from git.

    Format: comma- or whitespace-separated ``subject:token`` entries, e.g.
    ``ci:s3cr3t...,prof-smith:0th3r...``.  The subject is a LABEL, not a
    credential: it is what lands in the enqueue log line and in
    ``Principal.subject``, so a run can be attributed to whoever triggered it.

    Only ``reader`` + ``runner`` are granted.  **``author`` deliberately is
    not**: a shared static bearer token is a weaker credential than the platform
    SSO that A10 was written for, so the answer key stays fail-shut until real
    SSO lands rather than becoming unlockable by a token in an env var.

    Parsing is strict and happens at startup (:func:`ida_api.auth.validate_auth_config`)
    so a misconfigured deployment fails its readiness probe instead of serving
    with an auth mode it cannot enforce."""

    @property
    def sweep_exclude_tag_set(self) -> frozenset[str]:
        """:attr:`sweep_exclude_tags` parsed, normalised and de-duplicated.

        Comma-separated rather than a JSON list because the only place this is
        ever set is a container environment variable, and
        ``IDA_SWEEP_EXCLUDE_TAGS=testing-only,deferred`` is what an operator
        would expect to write. Blank segments are dropped, so a trailing comma is
        harmless; matching is case-insensitive because ``models.yaml`` tags are
        lower-case by convention but nothing enforces it.
        """
        return frozenset(
            part.strip().lower() for part in self.sweep_exclude_tags.split(",") if part.strip()
        )

    @field_validator("log_level", mode="after")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        """Upper-case the level, and reject anything that is not a real one.

        ⚠ THE CASE MISMATCH IS NOT COSMETIC -- it crash-looped every api and
        runner pod on the first deploy of the port. The platform's ConfigMap
        writes `LOG_LEVEL: info`, and `.env.example` documents lower case as the
        convention; `logging.basicConfig` accepts only `INFO`. Our default was
        already `"INFO"`, so nothing local and nothing in CI ever exercised the
        platform's actual value -- and the failure was `ValueError: Unknown
        level: 'info'` raised at IMPORT time, before any logging existed to
        report it.

        Rejecting an unknown level rather than quietly falling back to INFO:
        `basicConfig` raises either way, so the only question is WHERE and with
        WHAT MESSAGE. Failing where the value enters the system, naming the
        allowed set, beats the same crash six frames deep in the stdlib with
        nothing but the bad value to go on.
        """
        normalised = value.strip().upper()
        if normalised not in _LOG_LEVELS:
            raise ValueError(
                f"log level {value!r} is not a logging level; "
                f"expected one of {sorted(_LOG_LEVELS)} (case-insensitive)"
            )
        return normalised

    # ── resolvers ──────────────────────────────────────────────────────────

    @property
    def s3_endpoint_url(self) -> str:
        """``IDA_S3_ENDPOINT_URL`` wins; else compose the platform's MINIO_* triple."""
        if self.s3_endpoint_url_explicit:
            return self.s3_endpoint_url_explicit
        if self.minio_endpoint:
            scheme = "https" if self.minio_use_ssl else "http"
            return f"{scheme}://{self.minio_endpoint}:{self.minio_port}"
        return "http://minio:9000"

    def sqlalchemy_url(self) -> str:
        """:attr:`database_url` with the driver forced -- for ``migrations/env.py``.

        ``env.py`` builds its engine through ``engine_from_config``, not through
        :func:`ida_core.db.make_engine`, so it needs the normalisation applied
        explicitly.  Same helper, so the two can never disagree.
        """
        return normalize_database_url(self.database_url)

    def resolved_models_file(self) -> Path:
        return Path(self.models_file) if self.models_file else repo_root() / "models.yaml"

    def resolved_tasks_dir(self) -> Path:
        return Path(self.tasks_dir) if self.tasks_dir else repo_root() / "tasks"


def get_settings() -> Settings:
    """Build settings from the environment.

    Not cached: tests monkeypatch env between cases, and building this object is
    cheap.  Services call it once at startup and hold the result.
    """
    return Settings()
