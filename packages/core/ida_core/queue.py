"""**The queue contract**: how the API hands work to runners.

Transport
---------
A single Redis list, :data:`RUN_QUEUE_KEY`, used as a FIFO:

* API   -- ``RPUSH ida:queue:runs <json>``  (:class:`~ida_core.contracts.RunJobMessage`)
* Runner-- ``BLPOP ida:queue:runs <timeout>``

Redis was chosen over a Postgres-backed queue (D-5) because runners are
horizontally scaled pods and ``BLPOP`` gives fair work-stealing for free.

Poison messages
---------------
A payload that cannot be decoded is **never** allowed to reach the consumer as
an exception it did not ask for.  :meth:`RedisQueue.dequeue` parks it on
:data:`DEAD_LETTER_KEY` and returns ``None`` -- indistinguishable, to the
caller, from an empty-queue timeout, so the worker loop simply continues.

This matters most on the path the design *intends* to use: the moment anyone
bumps ``schema_version``, every older runner replica still rolling will meet a
message it cannot parse.  Refusing loudly and moving on is what
:class:`~ida_core.contracts.RunJobMessage`'s docstring promises; crashing is
what an earlier revision actually did, turning a routine version bump into a
tier-wide ``CrashLoopBackOff``.

Known gap (deliberate, documented)
----------------------------------
``BLPOP`` removes the message *before* the runner has done anything with it.
If the runner pod dies mid-run the message is gone and the run stays
``running`` forever.  The skeleton accepts this; the fix is a reliable-queue
pattern (``BLMOVE`` into a per-consumer processing list + a reaper) or Redis
Streams with consumer groups.  Do not build retry semantics on top of the
current interface without changing it -- :attr:`RunJobMessage.attempt` exists
so that change stays additive.

Testing
-------
:class:`InMemoryQueue` implements the same :class:`RunQueue` protocol so unit
tests and the in-process tracer bullet need no Redis.  It is a real
implementation, not a mock: same ordering, same JSON round-trip.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Protocol, runtime_checkable

from ida_core.contracts import RunJobMessage

log = logging.getLogger(__name__)

RUN_QUEUE_KEY = "ida:queue:runs"
"""The one and only queue key.  Changing it is a breaking deployment change."""

DEAD_LETTER_KEY = "ida:queue:runs:dead"
"""Where payloads that cannot be decoded are parked.

A message the runner cannot parse must go *somewhere* inspectable.  Dropping it
loses the evidence of whatever produced it; crashing on it takes down the whole
runner tier.  Parking it keeps the queue moving and leaves the bad payload for a
human to look at:  ``LRANGE ida:queue:runs:dead 0 -1``.
"""

MAX_DEAD_LETTERS = 1000
"""Cap on the dead-letter list, trimmed oldest-first.

An unbounded dead-letter list is its own outage: a producer emitting malformed
messages in a loop would fill Redis.  Keeping the most recent N is enough to
diagnose, and bounded.
"""


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


DEFAULT_BLOCK_TIMEOUT_S = 5
"""How long a runner blocks before looping (so it can notice shutdown signals)."""


@runtime_checkable
class RunQueue(Protocol):
    """Everything the API and the runner are allowed to assume about the queue."""

    def enqueue(self, message: RunJobMessage) -> None:
        """Append a job.  Must be durable enough that a crash right after
        returning still leaves the job visible to a runner."""

    def dequeue(self, timeout_s: int = DEFAULT_BLOCK_TIMEOUT_S) -> RunJobMessage | None:
        """Block up to ``timeout_s`` for a job.

        ``None`` means "no job for you right now" -- either the queue was empty
        or a payload was undecodable and has been dead-lettered.  **An
        implementation must not raise on a malformed payload**: the consumer is
        a long-lived loop, and a decode error is a property of one message, not
        a reason to stop consuming.
        """

    def depth(self) -> int:
        """Approximate number of waiting jobs.  For ``/health`` and dashboards."""


class RedisQueue:
    """Production :class:`RunQueue` backed by a Redis list."""

    def __init__(
        self, redis_client, key: str = RUN_QUEUE_KEY, dead_key: str = DEAD_LETTER_KEY
    ) -> None:
        self._redis = redis_client
        self._key = key
        self._dead_key = dead_key

    @classmethod
    def from_url(cls, url: str, key: str = RUN_QUEUE_KEY) -> RedisQueue:
        """Build from a ``redis://host:port/db`` URL."""
        import redis  # imported lazily so ida_core stays importable without redis running

        return cls(redis.Redis.from_url(url), key=key)

    def enqueue(self, message: RunJobMessage) -> None:
        self._redis.rpush(self._key, message.to_wire())

    def dequeue(self, timeout_s: int = DEFAULT_BLOCK_TIMEOUT_S) -> RunJobMessage | None:
        """Pop one job, dead-lettering anything undecodable.

        Returns ``None`` both when the queue was empty and when the payload was
        garbage.  Collapsing those two into "nothing to do" is deliberate: the
        consumer's correct action is identical (keep polling), and making it
        distinguishable would only tempt a caller into handling one and not the
        other.  The bad payload is not lost -- it is on
        :data:`DEAD_LETTER_KEY`, and the failure is logged.
        """
        popped = self._redis.blpop([self._key], timeout=timeout_s)
        if popped is None:
            return None
        _key, payload = popped
        try:
            return RunJobMessage.from_wire(payload)
        except Exception as exc:
            self._dead_letter(payload, exc)
            return None

    def _dead_letter(self, payload, exc: Exception) -> None:
        raw = payload if isinstance(payload, bytes) else str(payload).encode()
        log.error(
            "undecodable queue payload parked on %s: %r (%s)",
            self._dead_key,
            raw[:200],
            exc,
        )
        try:
            pipe = self._redis.pipeline()
            pipe.rpush(self._dead_key, raw)
            pipe.ltrim(self._dead_key, -MAX_DEAD_LETTERS, -1)
            pipe.execute()
        except Exception:
            # Redis is in trouble; the payload is already logged above, and
            # failing to park it must not escalate into killing the consumer.
            log.exception("could not park undecodable payload on %s", self._dead_key)

    def dead_letter_depth(self) -> int:
        """How many undecodable payloads are parked.  Worth alerting on."""
        return int(self._redis.llen(self._dead_key))

    def depth(self) -> int:
        return int(self._redis.llen(self._key))

    def ping(self) -> bool:
        """True if Redis answers.  Used by ``/health``."""
        try:
            return bool(self._redis.ping())
        except Exception:
            return False


class InMemoryQueue:
    """In-process :class:`RunQueue`.  Used by tests and the in-process tracer.

    Thread-safe: the runner worker runs on its own thread in the e2e test.
    ``timeout_s`` is honoured by waiting on a condition variable, so the
    blocking semantics match Redis closely enough to test against.
    """

    def __init__(self) -> None:
        self._items: deque[str | bytes] = deque()
        self._condition = threading.Condition()
        self.dead_letters: list[bytes] = []
        """Undecodable payloads parked here, mirroring Redis's dead-letter list."""

    def enqueue(self, message: RunJobMessage) -> None:
        with self._condition:
            self._items.append(message.to_wire())
            self._condition.notify()

    def enqueue_raw(self, payload: str | bytes) -> None:
        """Push an arbitrary payload, bypassing the contract.

        Exists so tests can inject the malformed messages a real Redis will
        eventually carry -- a producer at a different schema version, a
        half-written value, a hand-typed ``RPUSH``. Without this, "the worker
        survives a poison message" can only be tested against a *well-formed*
        message, which is how that property came to be asserted without ever
        being exercised.
        """
        with self._condition:
            self._items.append(payload)
            self._condition.notify()

    def dequeue(self, timeout_s: int = DEFAULT_BLOCK_TIMEOUT_S) -> RunJobMessage | None:
        with self._condition:
            if not self._items:
                self._condition.wait(timeout=timeout_s)
            if not self._items:
                return None
            payload = self._items.popleft()
        try:
            return RunJobMessage.from_wire(payload)
        except Exception as exc:
            raw = payload if isinstance(payload, bytes) else str(payload).encode()
            log.error("undecodable queue payload parked: %r (%s)", raw[:200], exc)
            self.dead_letters.append(raw)
            return None

    def depth(self) -> int:
        with self._condition:
            return len(self._items)

    def ping(self) -> bool:
        return True
