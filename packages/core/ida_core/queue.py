"""**The queue contract**: how the API hands work to runners, reliably.

Transport
---------
A Redis list, :data:`RUN_QUEUE_KEY`, used as a FIFO, plus one *processing* list
per consumer:

* API    -- ``RPUSH ida:queue:runs <json>``  (:class:`~ida_core.contracts.RunJobMessage`)
* Runner -- ``BLMOVE ida:queue:runs ida:queue:runs:processing:<consumer> LEFT RIGHT``
* Runner -- ``LREM ida:queue:runs:processing:<consumer> 1 <json>``  (the **ack**)

Redis was chosen over a Postgres-backed queue (D-5) because runners are
horizontally scaled pods and a blocking list pop gives fair work-stealing for
free.

Claim / ack / nack
------------------
:meth:`RunQueue.dequeue` **claims** a message: it moves atomically from the
pending list onto the caller's processing list, where it stays visible until
the consumer says what happened to it.

* :meth:`RunQueue.ack` -- the run reached a terminal state and is persisted.
  The claim is dropped.  This is the *only* thing that makes a message
  disappear for good.
* :meth:`RunQueue.nack` -- the consumer could not finish.  The message is
  re-queued with ``attempt + 1``, or, once ``max_attempts`` is spent, parked on
  :data:`DEAD_LETTER_KEY` with a reason.  The return value
  (:class:`NackOutcome`) tells the caller which happened, because only the
  caller can write the corresponding run row.

The consequence is **at-least-once** delivery, deliberately.  A runner killed
between "finished the work" and "acked" replays the job; a runner killed
anywhere else replays it too.  At-most-once would mean losing work on every pod
eviction, which is the failure this module previously had.

Liveness, and why a claim is not simply "old"
---------------------------------------------
A claim held by a *slow* runner and a claim held by a *dead* runner look
identical from the outside.  Reaping on age alone would duplicate every job
that legitimately outlives the threshold -- and an LLM eval run can take a very
long time.  So each consumer refreshes ``ida:queue:runs:alive:<consumer>``, a
key with a short TTL, for as long as its process is alive
(:meth:`RunQueue.heartbeat`; the runner drives it from a background thread so a
long job keeps heartbeating).  A processing list whose alive key has expired
belongs to a process that is *gone*, and only those claims are recovered --
see :meth:`RunQueue.recover_abandoned`.

Recovery is lock-free: a claim is taken from the dead consumer's list onto the
recovering consumer's own list with a single atomic ``LMOVE`` before it is
inspected.  Two reapers racing therefore cannot both requeue the same message,
and a reaper that dies mid-recovery leaves the claim on its *own* processing
list, where the next recovery pass finds it.

Poison messages
---------------
A payload that cannot be decoded is **never** allowed to reach the consumer as
an exception it did not ask for.  :meth:`RunQueue.dequeue` parks it on
:data:`DEAD_LETTER_KEY` and returns ``None`` -- indistinguishable, to the
caller, from an empty-queue timeout, so the worker loop simply continues.

This matters most on the path the design *intends* to use: the moment anyone
bumps ``schema_version``, every older runner replica still rolling will meet a
message it cannot parse.  Refusing loudly and moving on is what
:class:`~ida_core.contracts.RunJobMessage`'s docstring promises; crashing is
what an earlier revision actually did, turning a routine version bump into a
tier-wide ``CrashLoopBackOff``.

The dead-letter list therefore holds **two shapes**, and telling them apart is
the point:

* an *undecodable* payload is parked as the **exact original bytes**.  They are
  the entire evidence of whatever produced them, and re-encoding bytes that are
  by definition not known-good JSON would destroy that evidence.
* a *retry-exhausted* message is parked as a JSON envelope
  (:data:`DEAD_LETTER_KIND_RETRY_EXHAUSTED`) carrying the reason, the attempt
  count and the original message -- which is known-good JSON, so wrapping it is
  lossless and the reason travels with it instead of only reaching a log.

Both are readable with ``LRANGE ida:queue:runs:dead 0 -1``.

Schema compatibility
--------------------
Nothing here changes the wire schema.  Retries ride on
:attr:`~ida_core.contracts.RunJobMessage.attempt`, which was reserved for
exactly this, so ``schema_version`` stays ``1`` and an older runner meeting a
retried message parses it unchanged.

Testing
-------
:class:`InMemoryQueue` implements the same :class:`RunQueue` protocol so unit
tests and the in-process tracer bullet need no Redis.  It is a real
implementation, not a mock: same ordering, same JSON round-trip, same
claim/ack/nack/recovery semantics.  ``packages/core/tests/test_queue.py`` runs
one parity suite against **both** implementations so the two cannot drift.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ida_core.contracts import RunJobMessage

log = logging.getLogger(__name__)

RUN_QUEUE_KEY = "ida:queue:runs"
"""The one and only queue key.  Changing it is a breaking deployment change."""

DEAD_LETTER_KEY = "ida:queue:runs:dead"
"""Where payloads that cannot be decoded, or that ran out of attempts, are parked.

A message the runner cannot use must go *somewhere* inspectable.  Dropping it
loses the evidence of whatever produced it; crashing on it takes down the whole
runner tier.  Parking it keeps the queue moving and leaves the bad payload for a
human to look at:  ``LRANGE ida:queue:runs:dead 0 -1``.
"""

PROCESSING_KEY_PREFIX = f"{RUN_QUEUE_KEY}:processing"
"""``<prefix>:<consumer_id>`` -- the claims one consumer is working on.

Per-consumer rather than shared, because recovery has to answer "whose claims
are these, and is that process still alive?".  A single shared in-flight list
cannot answer either question.

DERIVED FROM THE QUEUE KEY, never hard-coded alongside it.  A queue pointed at a
different ``key`` gets a different processing namespace and therefore recovers
only its own claims -- which is what makes it safe to stand a second queue up
against the same Redis (a test, a migration, a parallel environment) without it
scanning over and reaping a live runner's in-flight work.
"""

HEARTBEAT_KEY_PREFIX = f"{RUN_QUEUE_KEY}:alive"
"""``<prefix>:<consumer_id>`` -- a short-TTL key a live consumer keeps warm.
Derived from the queue key for the same reason as :data:`PROCESSING_KEY_PREFIX`."""

MAX_DEAD_LETTERS = 1000
"""Cap on the dead-letter list, trimmed oldest-first.

An unbounded dead-letter list is its own outage: a producer emitting malformed
messages in a loop would fill Redis.  Keeping the most recent N is enough to
diagnose, and bounded.
"""

DEFAULT_BLOCK_TIMEOUT_S = 5
"""How long a runner blocks before looping (so it can notice shutdown signals)."""

DEFAULT_MAX_ATTEMPTS = 3
"""How many times a message may be *delivered* before it is dead-lettered.

Bounded on purpose.  Unbounded retry turns one job that always fails into a
permanent, invisible tax on the whole runner tier -- the queue never drains and
nothing ever says why.  Three deliveries absorbs a pod eviction and a transient
transport failure; a fourth means the job itself is the problem, and saying so
out loud on the dead-letter list is more useful than trying forever.
"""

DEFAULT_HEARTBEAT_TTL_S = 90
"""How long a consumer's liveness key survives without a refresh.

Comfortably longer than the runner's heartbeat interval (30s by default), so a
paused thread or a slow Redis round trip does not read as a dead process.  The
cost of setting it too *low* is duplicated work; the cost of setting it too
high is a delay before a genuinely dead runner's jobs are recovered.  Duplicated
work is the worse of the two, so this errs high.
"""

DEAD_LETTER_KIND_RETRY_EXHAUSTED = "retry_exhausted"
"""``kind`` of the JSON envelope parked when a message runs out of attempts."""


class UndecodableMessage(ValueError):
    """A queue payload could not be parsed into a :class:`RunJobMessage`.

    Carries the raw bytes so the caller can log or park them.  Distinct from a
    plain ``ValidationError`` so a consumer can catch exactly this.
    """

    def __init__(self, payload: bytes, cause: Exception) -> None:
        self.payload = payload
        self.cause = cause
        preview = payload[:200].decode(errors="replace")
        super().__init__(f"undecodable queue payload: {preview!r} ({cause})")


class NackOutcome(StrEnum):
    """What :meth:`RunQueue.nack` did with the message.

    The queue owns the transport decision (retry or park) and the *caller* owns
    the database row, so the decision has to cross back.  Returning it beats
    having the caller re-derive it from ``attempt`` and ``max_attempts``, which
    is how two components come to disagree about whether a run is retriable.
    """

    REQUEUED = "requeued"
    """Back on the pending list with ``attempt + 1``.  The run is not finished."""

    DEAD_LETTERED = "dead_lettered"
    """Attempts exhausted; parked with a reason.  The run is finished, badly --
    the caller must mark it ``failed`` so it never sits ``running`` forever."""


@dataclass(frozen=True)
class RecoveryReport:
    """What one :meth:`RunQueue.recover_abandoned` pass did.

    Run ids rather than messages: the only thing the caller can do with the
    result is reconcile run *rows*, and handing back parsed messages would
    invite a second consumer of the queue's internals.
    """

    requeued: list[str] = field(default_factory=list)
    """Run ids put back on the pending list.  Their rows must return to
    ``queued`` -- a recovered run left ``running`` is the original bug."""

    dead_lettered: list[tuple[str, str]] = field(default_factory=list)
    """``(run_id, reason)`` for claims that had no attempts left.  Their rows
    must be marked ``failed`` with that reason."""

    undecodable: int = 0
    """Claims that could not even be parsed.  Parked, not requeued: there is no
    run id to reconcile, and re-delivering them would only poison a live runner."""

    consumers_reaped: list[str] = field(default_factory=list)
    """Consumer ids whose processing lists were drained.  Worth logging: it
    names the pods that died."""

    @property
    def total(self) -> int:
        return len(self.requeued) + len(self.dead_lettered) + self.undecodable


def default_consumer_id() -> str:
    """A per-process identity for claims: ``<hostname>-<pid>``.

    Stable for the life of the process and unique across a runner Deployment
    (one pod per host-ish, and the pid disambiguates the rest), which is exactly
    the lifetime a claim needs to be attributable to.  A restarted pod gets a
    new pid and therefore a new id, so the *old* id's processing list is
    correctly seen as abandoned rather than silently re-adopted by a process
    that knows nothing about those claims.
    """
    return f"{socket.gethostname()}-{os.getpid()}"


@runtime_checkable
class RunQueue(Protocol):
    """Everything the API and the runner are allowed to assume about the queue."""

    @property
    def consumer_id(self) -> str:
        """This consumer's claim identity.  See :func:`default_consumer_id`."""

    def enqueue(self, message: RunJobMessage) -> None:
        """Append a job.  Must be durable enough that a crash right after
        returning still leaves the job visible to a runner."""

    def dequeue(self, timeout_s: int = DEFAULT_BLOCK_TIMEOUT_S) -> RunJobMessage | None:
        """Block up to ``timeout_s`` for a job and **claim** it.

        ``None`` means "no job for you right now" -- either the queue was empty
        or a payload was undecodable and has been dead-lettered.  **An
        implementation must not raise on a malformed payload**: the consumer is
        a long-lived loop, and a decode error is a property of one message, not
        a reason to stop consuming.

        A returned message is *claimed*, not consumed: it stays recoverable
        until :meth:`ack` or :meth:`nack`.  A consumer that returns from
        ``dequeue`` and then dies has not lost the job.

        ``timeout_s <= 0`` polls once and returns immediately rather than
        blocking forever -- Redis's own "0 means block indefinitely" is a trap
        for a caller that meant "don't wait", and both implementations here
        agree on the non-blocking reading.
        """

    def ack(self, message: RunJobMessage) -> None:
        """Drop the claim: the run reached a terminal state and is persisted.

        Must be safe to call for a message this consumer did not claim (it is
        then a no-op), so that a retry-after-crash path cannot wedge on it.
        """

    def nack(self, message: RunJobMessage, reason: str) -> NackOutcome:
        """Give the message back, retrying it or parking it.  See :class:`NackOutcome`."""

    def heartbeat(self) -> None:
        """Refresh this consumer's liveness key.  Best-effort: never raises."""

    def recover_abandoned(self) -> RecoveryReport:
        """Requeue or park the claims of consumers that are no longer alive."""

    def live_claims(self) -> set[str]:
        """Run ids currently claimed by a **live** consumer.

        The stale-run sweep needs this to tell "running for a long time" from
        "nobody is running this any more"; failing a run that a healthy runner
        is still working on would be a lie of exactly the kind this platform
        exists to avoid.
        """

    def depth(self) -> int:
        """Approximate number of waiting jobs.  For ``/health`` and dashboards."""


def _as_bytes(payload) -> bytes:
    """Normalise a Redis reply (bytes) or a local ``str`` to bytes."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode()
    return str(payload).encode()


def _retry_exhausted_envelope(message: RunJobMessage, reason: str, attempts: int) -> bytes:
    """The dead-letter record for a message that ran out of attempts.

    A wrapper rather than the bare payload: the *reason* is the whole value of
    the record, and a reason that lives only in a log line is not evidence a
    human can find three days later from the dead-letter list alone.
    """
    return json.dumps(
        {
            "kind": DEAD_LETTER_KIND_RETRY_EXHAUSTED,
            "reason": reason,
            "attempts": attempts,
            "run_id": message.run_id,
            "message": json.loads(message.to_wire()),
        },
        separators=(",", ":"),
    ).encode()


def _next_attempt(message: RunJobMessage) -> RunJobMessage:
    """The same job, one delivery further along.  Additive: no schema bump."""
    return message.model_copy(update={"attempt": message.attempt + 1})


class RedisQueue:
    """Production :class:`RunQueue` backed by Redis lists.

    One instance per consuming process: the claim identity and the in-flight
    bookkeeping are per-instance.  The API constructs one too and only ever
    calls :meth:`enqueue` and :meth:`depth`, which touch neither.
    """

    def __init__(
        self,
        redis_client,
        key: str = RUN_QUEUE_KEY,
        dead_key: str = DEAD_LETTER_KEY,
        *,
        consumer_id: str | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        heartbeat_ttl_s: int = DEFAULT_HEARTBEAT_TTL_S,
    ) -> None:
        self._redis = redis_client
        self._key = key
        self._dead_key = dead_key
        self._consumer_id = consumer_id or default_consumer_id()
        self._max_attempts = max(1, int(max_attempts))
        self._heartbeat_ttl_s = int(heartbeat_ttl_s)
        self._processing_prefix = f"{key}:processing"
        self._alive_prefix = f"{key}:alive"
        self._processing_key = f"{self._processing_prefix}:{self._consumer_id}"
        self._alive_key = f"{self._alive_prefix}:{self._consumer_id}"
        # The exact bytes each claimed run is parked under, so the ack can LREM
        # the value Redis actually holds. Re-serialising the message would
        # usually produce the same bytes -- but "usually" is not a basis for
        # deleting the only durable copy of a job.
        self._inflight: dict[str, bytes] = {}

    @classmethod
    def from_url(cls, url: str, key: str = RUN_QUEUE_KEY, **kwargs) -> RedisQueue:
        """Build from a ``redis://host:port/db`` URL."""
        import redis  # imported lazily so ida_core stays importable without redis running

        return cls(redis.Redis.from_url(url), key=key, **kwargs)

    # ------------------------------------------------------------ produce --

    @property
    def consumer_id(self) -> str:
        return self._consumer_id

    def enqueue(self, message: RunJobMessage) -> None:
        self._redis.rpush(self._key, message.to_wire())

    # ------------------------------------------------------------ consume --

    def dequeue(self, timeout_s: int = DEFAULT_BLOCK_TIMEOUT_S) -> RunJobMessage | None:
        """Claim one job, dead-lettering anything undecodable.

        Returns ``None`` both when the queue was empty and when the payload was
        garbage.  Collapsing those two into "nothing to do" is deliberate: the
        consumer's correct action is identical (keep polling), and making it
        distinguishable would only tempt a caller into handling one and not the
        other.  The bad payload is not lost -- it is on
        :data:`DEAD_LETTER_KEY`, and the failure is logged.
        """
        self.heartbeat()
        try:
            if timeout_s and timeout_s > 0:
                payload = self._redis.blmove(
                    self._key, self._processing_key, timeout_s, "LEFT", "RIGHT"
                )
            else:
                payload = self._redis.lmove(self._key, self._processing_key, "LEFT", "RIGHT")
        except AttributeError:  # pragma: no cover - redis-py < 6.2 server/client
            log.exception(
                "this Redis does not support LMOVE/BLMOVE; a reliable queue needs it (Redis >= 6.2)"
            )
            raise

        if payload is None:
            return None
        raw = _as_bytes(payload)
        try:
            message = RunJobMessage.from_wire(raw)
        except Exception as exc:
            # Drop the claim first: a payload nobody can parse must not be left
            # looking like work in progress, or every recovery pass will pick it
            # up and park it again.
            self._drop_claim(raw)
            self._dead_letter(raw, exc)
            return None
        self._inflight[message.run_id] = raw
        return message

    # ⚠ `RunJobMessage.to_wire()` BYTE-STABILITY IS LOAD-BEARING BELOW.
    # Both methods prefer the exact bytes recorded at claim time, but fall back
    # to re-serialising when this process did not claim the message (a restart,
    # or a claim taken over by recovery). `LREM` matches by EXACT BYTES, so if
    # `to_wire()` ever emitted a different encoding of the same message -- a key
    # order change, different separators, a pydantic upgrade altering float or
    # datetime rendering -- the fallback would match nothing, the ack would
    # silently no-op, and the claim would leak until a reaper picked it up.
    # That degrades to at-least-once rather than data loss, which is why this is
    # a comment and not a checksum; but nobody should "tidy" the serialisation
    # without knowing an ack depends on it.

    def ack(self, message: RunJobMessage) -> None:
        raw = self._inflight.pop(message.run_id, None) or _as_bytes(message.to_wire())
        self._drop_claim(raw)

    def nack(self, message: RunJobMessage, reason: str) -> NackOutcome:
        raw = self._inflight.pop(message.run_id, None) or _as_bytes(message.to_wire())
        return self._return_claim(raw, message, reason, self._processing_key)

    def heartbeat(self) -> None:
        """Best-effort.  Losing a heartbeat write must not stop the loop; the
        worst case is that this consumer's claims are recovered early, which the
        at-least-once contract already covers."""
        try:
            self._redis.set(self._alive_key, "1", ex=self._heartbeat_ttl_s)
        except Exception:
            log.warning("could not refresh the liveness key %s", self._alive_key, exc_info=True)

    # ----------------------------------------------------------- recovery --

    def recover_abandoned(self) -> RecoveryReport:
        """Take over and resolve the claims of consumers whose heartbeat lapsed.

        Never raises: a reaper pass that cannot reach Redis has nothing useful
        to do, and turning that into an exception would take the runner loop
        down over a transient outage.
        """
        report = RecoveryReport()
        self.heartbeat()  # so a concurrent reaper does not consider *us* dead
        try:
            dead = self._abandoned_processing_keys()
        except Exception:
            log.warning("could not scan for abandoned claims", exc_info=True)
            return report

        for consumer_id, processing_key in dead:
            drained = self._drain(processing_key, report)
            if drained:
                report.consumers_reaped.append(consumer_id)
            self._forget_consumer(consumer_id, processing_key)
        if report.total:
            log.warning(
                "recovered %d abandoned claim(s) from %s: %d requeued, %d dead-lettered, "
                "%d undecodable",
                report.total,
                report.consumers_reaped or "-",
                len(report.requeued),
                len(report.dead_lettered),
                report.undecodable,
            )
        return report

    def live_claims(self) -> set[str]:
        claimed: set[str] = set()
        try:
            for consumer_id, processing_key in self._processing_keys():
                if not self._is_alive(consumer_id):
                    continue
                for raw in self._redis.lrange(processing_key, 0, -1):
                    try:
                        claimed.add(RunJobMessage.from_wire(_as_bytes(raw)).run_id)
                    except Exception:
                        # Not a claim anyone can reconcile to a run row. Skipped
                        # here, parked by the next recovery pass -- not lost.
                        log.debug("unparseable claim on %s", processing_key, exc_info=True)
        except Exception:
            log.warning("could not read live claims", exc_info=True)
        return claimed

    # ------------------------------------------------------------- depths --

    def depth(self) -> int:
        return int(self._redis.llen(self._key))

    def processing_depth(self) -> int:
        """Claims this consumer is holding.  Should track "jobs in flight"."""
        return int(self._redis.llen(self._processing_key))

    def dead_letter_depth(self) -> int:
        """How many payloads are parked.  Worth alerting on."""
        return int(self._redis.llen(self._dead_key))

    def ping(self) -> bool:
        """True if Redis answers.  Used by ``/health``."""
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    # ------------------------------------------------------------ internal --

    def _processing_keys(self) -> list[tuple[str, str]]:
        """``(consumer_id, processing_key)`` for every processing list that exists."""
        found: list[tuple[str, str]] = []
        prefix = f"{self._processing_prefix}:"
        for key in self._redis.scan_iter(match=f"{prefix}*", count=100):
            name = key.decode() if isinstance(key, bytes) else str(key)
            found.append((name[len(prefix) :], name))
        return found

    def _abandoned_processing_keys(self) -> list[tuple[str, str]]:
        return [
            (consumer_id, key)
            for consumer_id, key in self._processing_keys()
            if consumer_id != self._consumer_id and not self._is_alive(consumer_id)
        ]

    def _is_alive(self, consumer_id: str) -> bool:
        if consumer_id == self._consumer_id:
            return True
        return bool(self._redis.exists(f"{self._alive_prefix}:{consumer_id}"))

    def _drain(self, processing_key: str, report: RecoveryReport) -> int:
        """Move a dead consumer's claims onto ours, one at a time, and resolve them.

        The ``LMOVE`` is the whole safety argument: taking ownership of a claim
        and reading it are the same operation, so two reapers cannot both decide
        what to do with one message, and a reaper that dies holding one leaves
        it on its own processing list rather than nowhere.
        """
        moved = 0
        while True:
            try:
                payload = self._redis.lmove(processing_key, self._processing_key, "LEFT", "RIGHT")
            except Exception:
                log.warning("could not drain %s", processing_key, exc_info=True)
                return moved
            if payload is None:
                return moved
            moved += 1
            raw = _as_bytes(payload)
            try:
                message = RunJobMessage.from_wire(raw)
            except Exception as exc:
                self._drop_claim(raw)
                self._dead_letter(raw, exc)
                report.undecodable += 1
                continue
            outcome = self._return_claim(
                raw,
                message,
                f"runner {processing_key.rsplit(':', 1)[-1]} stopped without acknowledging it",
                self._processing_key,
            )
            if outcome is NackOutcome.REQUEUED:
                report.requeued.append(message.run_id)
            else:
                report.dead_lettered.append(
                    (
                        message.run_id,
                        f"abandoned by a dead runner {message.attempt} time(s); no attempts left",
                    )
                )

    def _return_claim(
        self,
        raw: bytes,
        message: RunJobMessage,
        reason: str,
        processing_key: str,
    ) -> NackOutcome:
        """Requeue-or-park, removing the claim in the same transaction.

        Push first, remove second.  A crash in between duplicates the message,
        which at-least-once already tolerates; the other order loses it, which
        is the whole failure this module exists to prevent.
        """
        if message.attempt + 1 > self._max_attempts:
            envelope = _retry_exhausted_envelope(message, reason, message.attempt)
            log.error(
                "run %s dead-lettered after %d attempt(s): %s",
                message.run_id,
                message.attempt,
                reason,
            )
            self._park(envelope, processing_key, raw)
            return NackOutcome.DEAD_LETTERED

        retry = _next_attempt(message)
        log.warning(
            "run %s returned to the queue for attempt %d/%d: %s",
            message.run_id,
            retry.attempt,
            self._max_attempts,
            reason,
        )
        try:
            pipe = self._redis.pipeline()
            pipe.rpush(self._key, retry.to_wire())
            pipe.lrem(processing_key, 1, raw)
            pipe.execute()
        except Exception:
            # The claim stays put. That is the safe end of the failure: a
            # message still on a processing list is recoverable, and this
            # consumer's own heartbeat will lapse if it is really in trouble.
            log.exception("could not requeue run %s; leaving the claim in place", message.run_id)
        return NackOutcome.REQUEUED

    def _park(self, record: bytes, processing_key: str | None = None, raw: bytes | None = None):
        """Push one dead-letter record, trim the list, and drop the claim."""
        try:
            pipe = self._redis.pipeline()
            pipe.rpush(self._dead_key, record)
            pipe.ltrim(self._dead_key, -MAX_DEAD_LETTERS, -1)
            if processing_key is not None and raw is not None:
                pipe.lrem(processing_key, 1, raw)
            pipe.execute()
        except Exception:
            # Redis is in trouble; the record is already logged by the caller,
            # and failing to park it must not escalate into killing the consumer.
            log.exception("could not park a dead-letter record on %s", self._dead_key)

    def _dead_letter(self, payload, exc: Exception) -> None:
        """Park an **undecodable** payload as its exact original bytes."""
        raw = _as_bytes(payload)
        log.error(
            "undecodable queue payload parked on %s: %r (%s)",
            self._dead_key,
            raw[:200],
            exc,
        )
        self._park(raw)

    def _drop_claim(self, raw: bytes) -> None:
        try:
            self._redis.lrem(self._processing_key, 1, raw)
        except Exception:
            # An un-dropped claim is recovered later and, at worst, re-run.
            # Raising here would turn a bookkeeping failure into a lost loop.
            log.warning("could not drop a claim from %s", self._processing_key, exc_info=True)

    def _forget_consumer(self, consumer_id: str, processing_key: str) -> None:
        """Delete a drained processing list, but only if it is genuinely empty."""
        try:
            if int(self._redis.llen(processing_key)) == 0:
                self._redis.delete(processing_key)
                self._redis.delete(f"{self._alive_prefix}:{consumer_id}")
        except Exception:
            log.warning("could not clean up %s", processing_key, exc_info=True)


class _Shared:
    """The storage :class:`InMemoryQueue` siblings share.

    Split out so several ``InMemoryQueue`` objects can model several *runner
    processes* against one queue -- which is what a crash-recovery test needs
    and what a single object cannot express.
    """

    def __init__(self) -> None:
        self.items: deque[str | bytes] = deque()
        self.processing: dict[str, list[bytes]] = {}
        self.alive: set[str] = set()
        self.dead_letters: list[bytes] = []
        self.condition = threading.Condition()


class InMemoryQueue:
    """In-process :class:`RunQueue`.  Used by tests and the in-process tracer.

    A real implementation, not a mock: same FIFO ordering, same JSON round
    trip, same claim/ack/nack/recovery semantics as :class:`RedisQueue`.  The
    parity suite in ``test_queue.py`` runs against both, because a test double
    that has quietly drifted from the thing it doubles is worse than no double.

    Thread-safe: the runner worker runs on its own thread in the e2e test.
    ``timeout_s`` is honoured by waiting on a condition variable, so the
    blocking semantics match Redis closely enough to test against.

    Liveness is explicit rather than clock-driven: a consumer is alive once it
    has heartbeated and stays alive until :meth:`simulate_consumer_death` says
    otherwise.  A wall-clock TTL here would only add flakiness -- the property
    under test is "claims of a dead consumer are recovered", not "Python can
    measure 90 seconds".
    """

    def __init__(
        self,
        *,
        consumer_id: str = "in-memory-0",
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        _shared: _Shared | None = None,
    ) -> None:
        self._shared = _shared if _shared is not None else _Shared()
        self._consumer_id = consumer_id
        self._max_attempts = max(1, int(max_attempts))
        self._inflight: dict[str, bytes] = {}
        self._shared.processing.setdefault(consumer_id, [])

    def for_consumer(self, consumer_id: str) -> InMemoryQueue:
        """A sibling sharing this queue's storage under a different identity.

        The in-memory stand-in for "a second runner pod on the same Redis".
        """
        return InMemoryQueue(
            consumer_id=consumer_id,
            max_attempts=self._max_attempts,
            _shared=self._shared,
        )

    # ------------------------------------------------------------ produce --

    @property
    def consumer_id(self) -> str:
        return self._consumer_id

    @property
    def dead_letters(self) -> list[bytes]:
        """Parked payloads, mirroring Redis's dead-letter list."""
        return self._shared.dead_letters

    def enqueue(self, message: RunJobMessage) -> None:
        with self._shared.condition:
            self._shared.items.append(message.to_wire())
            self._shared.condition.notify()

    def enqueue_raw(self, payload: str | bytes) -> None:
        """Push an arbitrary payload, bypassing the contract.

        Exists so tests can inject the malformed messages a real Redis will
        eventually carry -- a producer at a different schema version, a
        half-written value, a hand-typed ``RPUSH``. Without this, "the worker
        survives a poison message" can only be tested against a *well-formed*
        message, which is how that property came to be asserted without ever
        being exercised.
        """
        with self._shared.condition:
            self._shared.items.append(payload)
            self._shared.condition.notify()

    # ------------------------------------------------------------ consume --

    def dequeue(self, timeout_s: int = DEFAULT_BLOCK_TIMEOUT_S) -> RunJobMessage | None:
        self.heartbeat()
        with self._shared.condition:
            if not self._shared.items and timeout_s and timeout_s > 0:
                self._shared.condition.wait(timeout=timeout_s)
            if not self._shared.items:
                return None
            payload = self._shared.items.popleft()
            raw = _as_bytes(payload)
            # Claimed the instant it leaves the pending list, under the same
            # lock -- the in-memory equivalent of BLMOVE's atomicity.
            self._claims().append(raw)
        try:
            message = RunJobMessage.from_wire(raw)
        except Exception as exc:
            self._drop_claim(raw)
            self._dead_letter(raw, exc)
            return None
        self._inflight[message.run_id] = raw
        return message

    def ack(self, message: RunJobMessage) -> None:
        raw = self._inflight.pop(message.run_id, None) or _as_bytes(message.to_wire())
        self._drop_claim(raw)

    def nack(self, message: RunJobMessage, reason: str) -> NackOutcome:
        raw = self._inflight.pop(message.run_id, None) or _as_bytes(message.to_wire())
        return self._return_claim(raw, message, reason, self._consumer_id)

    def heartbeat(self) -> None:
        with self._shared.condition:
            self._shared.alive.add(self._consumer_id)

    def simulate_consumer_death(self) -> None:
        """Drop this consumer's liveness while leaving its claims in place.

        The in-memory analogue of ``kill -9``: exactly the state Redis is left
        in when a runner pod dies -- the heartbeat key expires, the processing
        list does not.  A documented test affordance on a real implementation,
        like :meth:`enqueue_raw`; there is no other way to reach the state the
        recovery path exists for.
        """
        with self._shared.condition:
            self._shared.alive.discard(self._consumer_id)

    # ----------------------------------------------------------- recovery --

    def recover_abandoned(self) -> RecoveryReport:
        report = RecoveryReport()
        self.heartbeat()
        with self._shared.condition:
            abandoned = [
                consumer_id
                for consumer_id, claims in self._shared.processing.items()
                if claims and consumer_id != self._consumer_id
                if consumer_id not in self._shared.alive
            ]
        for consumer_id in abandoned:
            drained = 0
            while True:
                with self._shared.condition:
                    claims = self._shared.processing.get(consumer_id) or []
                    if not claims:
                        break
                    raw = claims.pop(0)
                    self._claims().append(raw)  # take ownership, then decide
                drained += 1
                try:
                    message = RunJobMessage.from_wire(raw)
                except Exception as exc:
                    self._drop_claim(raw)
                    self._dead_letter(raw, exc)
                    report.undecodable += 1
                    continue
                outcome = self._return_claim(
                    raw,
                    message,
                    f"runner {consumer_id} stopped without acknowledging it",
                    self._consumer_id,
                )
                if outcome is NackOutcome.REQUEUED:
                    report.requeued.append(message.run_id)
                else:
                    report.dead_lettered.append(
                        (
                            message.run_id,
                            f"abandoned by a dead runner {message.attempt} time(s); "
                            "no attempts left",
                        )
                    )
            if drained:
                report.consumers_reaped.append(consumer_id)
                with self._shared.condition:
                    self._shared.processing.pop(consumer_id, None)
        return report

    def live_claims(self) -> set[str]:
        claimed: set[str] = set()
        with self._shared.condition:
            snapshot = {
                consumer_id: list(claims)
                for consumer_id, claims in self._shared.processing.items()
                if consumer_id in self._shared.alive
            }
        for claims in snapshot.values():
            for raw in claims:
                try:
                    claimed.add(RunJobMessage.from_wire(raw).run_id)
                except Exception:
                    log.debug("unparseable claim held in memory", exc_info=True)
        return claimed

    # ------------------------------------------------------------- depths --

    def depth(self) -> int:
        with self._shared.condition:
            return len(self._shared.items)

    def processing_depth(self) -> int:
        with self._shared.condition:
            return len(self._claims())

    def dead_letter_depth(self) -> int:
        with self._shared.condition:
            return len(self._shared.dead_letters)

    def ping(self) -> bool:
        return True

    # ------------------------------------------------------------ internal --

    def _claims(self) -> list[bytes]:
        return self._shared.processing.setdefault(self._consumer_id, [])

    def _return_claim(
        self,
        raw: bytes,
        message: RunJobMessage,
        reason: str,
        owner: str,
    ) -> NackOutcome:
        if message.attempt + 1 > self._max_attempts:
            log.error(
                "run %s dead-lettered after %d attempt(s): %s",
                message.run_id,
                message.attempt,
                reason,
            )
            with self._shared.condition:
                self._shared.dead_letters.append(
                    _retry_exhausted_envelope(message, reason, message.attempt)
                )
                self._trim_dead_letters()
                self._remove_claim(owner, raw)
            return NackOutcome.DEAD_LETTERED

        retry = _next_attempt(message)
        log.warning(
            "run %s returned to the queue for attempt %d/%d: %s",
            message.run_id,
            retry.attempt,
            self._max_attempts,
            reason,
        )
        with self._shared.condition:
            self._shared.items.append(retry.to_wire())
            self._remove_claim(owner, raw)
            self._shared.condition.notify()
        return NackOutcome.REQUEUED

    def _dead_letter(self, raw: bytes, exc: Exception) -> None:
        log.error("undecodable queue payload parked: %r (%s)", raw[:200], exc)
        with self._shared.condition:
            self._shared.dead_letters.append(raw)
            self._trim_dead_letters()

    def _trim_dead_letters(self) -> None:
        """Bounded, exactly as Redis's ``LTRIM`` keeps it bounded."""
        excess = len(self._shared.dead_letters) - MAX_DEAD_LETTERS
        if excess > 0:
            del self._shared.dead_letters[:excess]

    def _drop_claim(self, raw: bytes) -> None:
        with self._shared.condition:
            self._remove_claim(self._consumer_id, raw)

    def _remove_claim(self, owner: str, raw: bytes) -> None:
        """Remove ONE matching claim -- Redis's ``LREM <key> 1 <value>``."""
        claims = self._shared.processing.get(owner)
        if not claims:
            return
        with contextlib.suppress(ValueError):
            claims.remove(raw)
