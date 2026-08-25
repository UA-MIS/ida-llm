"""Queue contract: JSON on the wire, FIFO, versioned, refuses garbage -- and
does not lose a job when the runner holding it dies.

HOW THIS FILE IS ORGANISED
--------------------------
The durability behaviour is written ONCE, in :class:`TestQueueParity`, and run
against **both** :class:`~ida_core.queue.InMemoryQueue` and
:class:`~ida_core.queue.RedisQueue`.  That is not tidiness: ``InMemoryQueue``
is what the unit tests, the API tests and the e2e tracer bullet actually
exercise, so any behaviour it does not share with Redis is behaviour this
project believes it has and does not.  A parity suite is the only thing that
keeps the double honest as the real implementation grows.

Failure paths first (L-1/L-2): the crash, the exhausted retry and the poison
message are the reason this module exists.  The happy path is asserted mostly
to prove the durability machinery did not change it.
"""

from __future__ import annotations

import json
import threading

import pytest
from _queue_fakes import BrokenPipelineRedis, FakeRedis
from pydantic import ValidationError

from ida_core.contracts import RunJobMessage, SamplingParams
from ida_core.db import utcnow
from ida_core.queue import (
    DEAD_LETTER_KEY,
    DEAD_LETTER_KIND_RETRY_EXHAUSTED,
    HEARTBEAT_KEY_PREFIX,
    MAX_DEAD_LETTERS,
    PROCESSING_KEY_PREFIX,
    RUN_QUEUE_KEY,
    InMemoryQueue,
    NackOutcome,
    RedisQueue,
    RunQueue,
    default_consumer_id,
)


def _message(run_id: str = "run_1", **overrides) -> RunJobMessage:
    base = {
        "run_id": run_id,
        "task_id": "demo/t",
        "model_key": "mock",
        "enqueued_at": utcnow(),
    }
    base.update(overrides)
    return RunJobMessage(**base)


class TestWireFormat:
    def test_round_trip(self) -> None:
        original = _message()
        assert RunJobMessage.from_wire(original.to_wire()) == original

    def test_round_trip_from_bytes(self) -> None:
        """Redis hands back bytes, not str."""
        original = _message()
        assert RunJobMessage.from_wire(original.to_wire().encode()) == original

    def test_sampling_override_survives_the_wire(self) -> None:
        original = _message()
        original.sampling_override = SamplingParams(temperature=0.7, max_tokens=64)
        restored = RunJobMessage.from_wire(original.to_wire())
        assert restored.sampling_override is not None
        assert restored.sampling_override.temperature == 0.7

    def test_unknown_schema_version_is_refused(self) -> None:
        """A runner must never guess at a message shape it does not know."""
        payload = json.loads(_message().to_wire())
        payload["schema_version"] = 99
        with pytest.raises(ValidationError):
            RunJobMessage.from_wire(json.dumps(payload))

    def test_unknown_field_is_refused(self) -> None:
        payload = json.loads(_message().to_wire())
        payload["surprise"] = True
        with pytest.raises(ValidationError):
            RunJobMessage.from_wire(json.dumps(payload))

    def test_attempt_is_one_based(self) -> None:
        with pytest.raises(ValidationError):
            RunJobMessage(run_id="r", task_id="t", model_key="m", enqueued_at=utcnow(), attempt=0)

    def test_retrying_is_additive_and_does_not_bump_the_schema(self) -> None:
        """The durability pass rides on `attempt`, which was reserved for it.

        If retrying had needed a new field, every runner replica still rolling
        during a deploy would meet a message it must refuse -- the exact
        CrashLoopBackOff the poison-message handling exists to survive. So the
        version staying at 1 is a compatibility guarantee, not a detail.
        """
        retried = _message().model_copy(update={"attempt": 3})
        restored = RunJobMessage.from_wire(retried.to_wire())
        assert restored.schema_version == 1
        assert restored.attempt == 3


# ---------------------------------------------------------------------------
# The parity harness
# ---------------------------------------------------------------------------


class _World:
    """One queue with several consumers, over either implementation.

    Gives the parity suite the four things it needs and that differ between the
    two: make a consumer, kill a consumer, look at the pending list, look at the
    dead-letter list.  Everything else is the queue's own public API, which is
    the point.
    """

    def consumer(self, name: str) -> RunQueue:
        raise NotImplementedError

    def kill(self, queue) -> None:
        """Make ``queue``'s consumer look like a process that died: its claims
        stay exactly where they are, its liveness does not."""
        raise NotImplementedError

    def push_raw(self, payload: bytes) -> None:
        """Enqueue something that is not a valid message -- a producer at a
        different schema version, a half-written value, a hand-typed RPUSH."""
        raise NotImplementedError

    def pending(self) -> list[bytes]:
        raise NotImplementedError

    def dead_letters(self) -> list[bytes]:
        raise NotImplementedError

    def claims(self, queue) -> list[bytes]:
        raise NotImplementedError


class _InMemoryWorld(_World):
    def __init__(self, max_attempts: int) -> None:
        self._root = InMemoryQueue(consumer_id="runner-a", max_attempts=max_attempts)
        self._consumers: dict[str, InMemoryQueue] = {"runner-a": self._root}

    def consumer(self, name: str) -> RunQueue:
        if name not in self._consumers:
            self._consumers[name] = self._root.for_consumer(name)
        return self._consumers[name]

    def kill(self, queue) -> None:
        queue.simulate_consumer_death()

    def push_raw(self, payload: bytes) -> None:
        self._root.enqueue_raw(payload)

    def pending(self) -> list[bytes]:
        return [p if isinstance(p, bytes) else p.encode() for p in self._root._shared.items]

    def dead_letters(self) -> list[bytes]:
        return list(self._root.dead_letters)

    def claims(self, queue) -> list[bytes]:
        return list(self._root._shared.processing.get(queue.consumer_id, []))


class _RedisWorld(_World):
    def __init__(self, max_attempts: int) -> None:
        self.redis = FakeRedis()
        self._max_attempts = max_attempts
        self._consumers: dict[str, RedisQueue] = {}

    def consumer(self, name: str) -> RunQueue:
        if name not in self._consumers:
            self._consumers[name] = RedisQueue(
                self.redis, consumer_id=name, max_attempts=self._max_attempts
            )
        return self._consumers[name]

    def kill(self, queue) -> None:
        # Exactly what a dead pod looks like to Redis: the TTL on the liveness
        # key elapses; the processing list is untouched.
        self.redis.expire_now(f"{HEARTBEAT_KEY_PREFIX}:{queue.consumer_id}")

    def push_raw(self, payload: bytes) -> None:
        self.redis.rpush(RUN_QUEUE_KEY, payload)

    def pending(self) -> list[bytes]:
        return list(self.redis.lists.get(RUN_QUEUE_KEY, []))

    def dead_letters(self) -> list[bytes]:
        return list(self.redis.lists.get(DEAD_LETTER_KEY, []))

    def claims(self, queue) -> list[bytes]:
        return list(self.redis.lists.get(f"{PROCESSING_KEY_PREFIX}:{queue.consumer_id}", []))


@pytest.fixture(params=["in-memory", "redis"])
def world(request) -> _World:
    """Both implementations, same assertions.  See the module docstring."""
    return _InMemoryWorld(3) if request.param == "in-memory" else _RedisWorld(3)


@pytest.fixture(params=["in-memory", "redis"])
def strict_world(request) -> _World:
    """A world with ``max_attempts=2``, so exhaustion is two lines away."""
    return _InMemoryWorld(2) if request.param == "in-memory" else _RedisWorld(2)


def _attempts(payloads: list[bytes]) -> list[int]:
    return [RunJobMessage.from_wire(p).attempt for p in payloads]


class TestQueueParity:
    """Written once, run against both implementations.  See the module docstring."""

    # ------------------------------------------------------ the happy path --

    def test_ordinary_delivery_is_unchanged(self, world: _World) -> None:
        """The durability machinery must be invisible when nothing goes wrong."""
        queue = world.consumer("runner-a")
        for i in range(3):
            queue.enqueue(_message(f"run_{i}"))
        assert queue.depth() == 3

        seen = []
        for _ in range(3):
            message = queue.dequeue(timeout_s=0)
            assert message is not None
            seen.append(message.run_id)
            assert message.attempt == 1, "a first delivery is attempt 1, as before"
            queue.ack(message)

        assert seen == ["run_0", "run_1", "run_2"], "still FIFO"
        assert queue.depth() == 0
        assert world.claims(queue) == [], "an acked job holds nothing"
        assert world.dead_letters() == []

    def test_dequeue_on_empty_returns_none(self, world: _World) -> None:
        assert world.consumer("runner-a").dequeue(timeout_s=0) is None

    # ---------------------------------------------------- claim before ack --

    def test_a_claimed_job_is_off_the_queue_but_not_gone(self, world: _World) -> None:
        """The whole difference from BLPOP: dequeue moves, it does not delete."""
        queue = world.consumer("runner-a")
        queue.enqueue(_message("run_claimed"))

        message = queue.dequeue(timeout_s=0)

        assert message is not None
        assert world.pending() == [], "no second runner can pick it up"
        assert _attempts(world.claims(queue)) == [1], "and it is still recorded somewhere"

    def test_ack_is_what_finally_removes_it(self, world: _World) -> None:
        queue = world.consumer("runner-a")
        queue.enqueue(_message("run_done"))
        message = queue.dequeue(timeout_s=0)

        queue.ack(message)

        assert world.claims(queue) == []
        assert world.pending() == []
        assert world.dead_letters() == []

    def test_acking_something_never_claimed_is_harmless(self, world: _World) -> None:
        """A retry-after-crash path must not be able to wedge on a stale ack."""
        queue = world.consumer("runner-a")
        queue.ack(_message("run_not_mine"))  # must not raise
        assert world.claims(queue) == []

    # ------------------------------------------------------ THE CRASH PATH --

    def test_a_runner_dying_between_claim_and_ack_does_not_lose_the_job(
        self, world: _World
    ) -> None:
        """B-of-this-story, reproduced: kill -9 after the claim, before the ack.

        Under the old BLPOP loop the message was already deleted at this point
        and the run stayed `running` until a human noticed. The assertion that
        matters is the last one: the job is back on the PENDING list, where some
        other runner will find it.
        """
        dying = world.consumer("runner-a")
        survivor = world.consumer("runner-b")
        dying.enqueue(_message("run_interrupted"))
        claimed = dying.dequeue(timeout_s=0)
        assert claimed is not None and world.pending() == []

        world.kill(dying)  # <-- the pod is gone; no ack, no nack, no cleanup
        report = survivor.recover_abandoned()

        assert report.requeued == ["run_interrupted"]
        assert report.consumers_reaped == ["runner-a"]
        assert _attempts(world.pending()) == [2], "back on the queue, one attempt spent"
        assert world.dead_letters() == [], "nothing was given up on"

    def test_the_recovered_job_can_actually_be_run_by_someone_else(self, world: _World) -> None:
        """Recovery is worth nothing if the message is not consumable again."""
        dying = world.consumer("runner-a")
        survivor = world.consumer("runner-b")
        dying.enqueue(_message("run_interrupted"))
        dying.dequeue(timeout_s=0)
        world.kill(dying)
        survivor.recover_abandoned()

        redelivered = survivor.dequeue(timeout_s=0)

        assert redelivered is not None
        assert redelivered.run_id == "run_interrupted"
        assert redelivered.attempt == 2
        assert redelivered.schema_version == 1, "an older replica could still parse it"
        survivor.ack(redelivered)
        assert world.claims(survivor) == []

    def test_recovery_does_not_touch_a_LIVE_runners_claims(self, world: _World) -> None:
        """The duplicate-work guard.

        Reaping on age alone would re-run every job that legitimately outlives
        the threshold -- and an LLM eval is exactly the kind of job that does.
        A slow runner is not a dead one.
        """
        busy = world.consumer("runner-a")
        reaper = world.consumer("runner-b")
        busy.enqueue(_message("run_long"))
        busy.dequeue(timeout_s=0)  # claimed, still heartbeating

        report = reaper.recover_abandoned()

        assert report.total == 0
        assert report.consumers_reaped == []
        assert _attempts(world.claims(busy)) == [1], "still held by the runner doing it"
        assert world.pending() == [], "and NOT handed to anybody else"

    def test_a_reaper_does_not_reap_itself(self, world: _World) -> None:
        """A consumer running the pass is by definition alive."""
        queue = world.consumer("runner-a")
        queue.enqueue(_message("run_mine"))
        queue.dequeue(timeout_s=0)

        report = queue.recover_abandoned()

        assert report.total == 0
        assert _attempts(world.claims(queue)) == [1]

    def test_live_claims_names_only_what_a_live_runner_holds(self, world: _World) -> None:
        alive = world.consumer("runner-a")
        dead = world.consumer("runner-b")
        observer = world.consumer("runner-c")
        alive.enqueue(_message("run_alive"))
        dead.enqueue(_message("run_dead"))
        alive.dequeue(timeout_s=0)
        dead.dequeue(timeout_s=0)
        world.kill(dead)

        assert observer.live_claims() == {"run_alive"}

    # ------------------------------------------------------ RETRY POLICY ---

    def test_nack_returns_the_job_with_the_next_attempt(self, world: _World) -> None:
        queue = world.consumer("runner-a")
        queue.enqueue(_message("run_flaky"))
        message = queue.dequeue(timeout_s=0)

        outcome = queue.nack(message, "the transport blew up")

        assert outcome is NackOutcome.REQUEUED
        assert _attempts(world.pending()) == [2]
        assert world.claims(queue) == [], "the old claim is released, not duplicated"
        assert world.dead_letters() == []

    def test_retries_are_bounded_and_the_last_one_is_dead_lettered(
        self, strict_world: _World
    ) -> None:
        """Unbounded retry is a permanent invisible tax; this is where it stops.

        With max_attempts=2 the second delivery is the last one.
        """
        world = strict_world
        queue = world.consumer("runner-a")
        queue.enqueue(_message("run_doomed"))

        first = queue.dequeue(timeout_s=0)
        assert queue.nack(first, "boom") is NackOutcome.REQUEUED
        second = queue.dequeue(timeout_s=0)
        assert second.attempt == 2

        outcome = queue.nack(second, "boom again")

        assert outcome is NackOutcome.DEAD_LETTERED
        assert world.pending() == [], "it is not going round again"
        assert world.claims(queue) == [], "and it is not left looking in-flight"
        assert len(world.dead_letters()) == 1

    def test_the_dead_letter_record_says_WHY_and_WHICH_run(self, strict_world: _World) -> None:
        """A reason that only reaches a log is not evidence anyone can find."""
        world = strict_world
        queue = world.consumer("runner-a")
        queue.enqueue(_message("run_doomed"))
        queue.nack(queue.dequeue(timeout_s=0), "boom")
        queue.nack(queue.dequeue(timeout_s=0), "ConnectionError: endpoint unreachable")

        record = json.loads(world.dead_letters()[0])

        assert record["kind"] == DEAD_LETTER_KIND_RETRY_EXHAUSTED
        assert record["run_id"] == "run_doomed"
        assert record["attempts"] == 2
        assert "endpoint unreachable" in record["reason"]
        # The original message is embedded whole, so the job is re-drivable by
        # hand from the dead-letter list alone.
        assert RunJobMessage.model_validate(record["message"]).run_id == "run_doomed"

    def test_a_job_abandoned_too_many_times_is_dead_lettered_not_requeued_forever(
        self, strict_world: _World
    ) -> None:
        """Crash recovery is bounded by the SAME budget as an explicit nack.

        Otherwise a job that reliably kills whichever runner picks it up would
        be recovered, re-delivered and re-killed for ever -- a crash loop with
        extra steps.
        """
        world = strict_world
        dying = world.consumer("runner-a")
        reaper = world.consumer("runner-b")
        dying.enqueue(_message("run_killer", attempt=2))  # already on its last life
        dying.dequeue(timeout_s=0)
        world.kill(dying)

        report = reaper.recover_abandoned()

        assert report.requeued == []
        assert [run_id for run_id, _ in report.dead_lettered] == ["run_killer"]
        assert world.pending() == []
        assert len(world.dead_letters()) == 1
        assert json.loads(world.dead_letters()[0])["run_id"] == "run_killer"

    # ---------------------------------------------------- POISON MESSAGES ---

    @pytest.mark.parametrize(
        "payload",
        [
            b"not json at all",
            b'{"not": "a valid message"}',
            b"",
            b"[]",
            b'{"run_id": "r", "task_id": "t"}',
            b'{"schema_version": 2, "run_id": "r", "task_id": "t", "model_key": "m",'
            b' "enqueued_at": "2026-01-01T00:00:00Z"}',
        ],
        ids=["garbage", "wrong-shape", "empty", "array", "incomplete", "future-version"],
    )
    def test_an_undecodable_payload_is_parked_and_leaves_no_claim(
        self, world: _World, payload: bytes
    ) -> None:
        """Still true after the rewrite -- and now it must not leak a claim.

        A payload nobody can parse sitting on a processing list would be picked
        up by every recovery pass for ever. Parking it is the terminal state.
        """
        queue = world.consumer("runner-a")
        world.push_raw(payload)

        assert queue.dequeue(timeout_s=0) is None, "indistinguishable from an empty queue"
        assert world.dead_letters() == [payload], "parked as the EXACT original bytes"
        assert world.claims(queue) == [], "and not left looking like work in progress"

    def test_the_version_bump_refusal_path_still_ends_in_a_dead_letter(self, world: _World) -> None:
        """The designed forward-compatibility path, pinned separately because it
        is the one a deploy will actually take."""
        queue = world.consumer("runner-a")
        future = json.loads(_message("run_future").to_wire())
        future["schema_version"] = 2
        world.push_raw(json.dumps(future).encode())

        assert queue.dequeue(timeout_s=0) is None
        assert len(world.dead_letters()) == 1
        assert b'"schema_version":2' in world.dead_letters()[0].replace(b" ", b"")

    def test_a_good_message_behind_poison_still_arrives(self, world: _World) -> None:
        queue = world.consumer("runner-a")
        world.push_raw(b"garbage")
        queue.enqueue(_message("run_good"))

        assert queue.dequeue(timeout_s=0) is None  # the poison
        message = queue.dequeue(timeout_s=0)

        assert message is not None and message.run_id == "run_good"

    def test_recovery_parks_an_undecodable_claim_rather_than_re_delivering_it(
        self, world: _World
    ) -> None:
        """Handing a poison payload back to a live runner would spread it."""
        dying = world.consumer("runner-a")
        reaper = world.consumer("runner-b")
        world.push_raw(b"garbage-in-flight")
        dying.dequeue(timeout_s=0)  # parks it immediately; nothing is claimed
        world.push_raw(b"another")
        dying.dequeue(timeout_s=0)
        world.kill(dying)

        report = reaper.recover_abandoned()

        assert report.requeued == []
        assert world.pending() == []

    def test_the_dead_letter_list_is_bounded(self, world: _World) -> None:
        """An unbounded dead-letter list is its own outage."""
        queue = world.consumer("runner-a")
        for i in range(MAX_DEAD_LETTERS + 5):
            world.push_raw(f"garbage-{i}".encode())
            queue.dequeue(timeout_s=0)

        parked = world.dead_letters()
        assert len(parked) == MAX_DEAD_LETTERS
        assert parked[-1] == f"garbage-{MAX_DEAD_LETTERS + 4}".encode(), "newest kept"
        assert parked[0] == b"garbage-5", "oldest trimmed first"


# ---------------------------------------------------------------------------
# Implementation-specific
# ---------------------------------------------------------------------------


class TestInMemoryQueue:
    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(InMemoryQueue(), RunQueue)

    def test_depth(self) -> None:
        queue = InMemoryQueue()
        assert queue.depth() == 0
        queue.enqueue(_message())
        assert queue.depth() == 1

    def test_dequeue_on_empty_returns_none_after_timeout(self) -> None:
        assert InMemoryQueue().dequeue(timeout_s=0) is None

    def test_blocking_dequeue_wakes_on_enqueue(self) -> None:
        queue = InMemoryQueue()
        received: list[RunJobMessage | None] = []

        def consume() -> None:
            received.append(queue.dequeue(timeout_s=5))

        thread = threading.Thread(target=consume)
        thread.start()
        queue.enqueue(_message("run_late"))
        thread.join(timeout=5)
        assert received and received[0] is not None
        assert received[0].run_id == "run_late"

    def test_siblings_share_one_queue(self) -> None:
        """`for_consumer` models a second runner pod, not a second queue."""
        first = InMemoryQueue(consumer_id="a")
        second = first.for_consumer("b")
        first.enqueue(_message("run_shared"))

        assert second.depth() == 1
        assert second.dequeue(timeout_s=0).run_id == "run_shared"
        assert first.depth() == 0


class TestRedisQueue:
    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(RedisQueue(FakeRedis()), RunQueue)

    def test_the_queue_key_is_pinned(self) -> None:
        """Changing this is a breaking deployment change; make it deliberate."""
        assert RUN_QUEUE_KEY == "ida:queue:runs"

    def test_the_consumer_id_identifies_a_PROCESS(self) -> None:
        """A restarted pod must get a new id, or it would silently re-adopt
        claims it knows nothing about instead of them being recovered."""
        assert str(__import__("os").getpid()) in default_consumer_id()

    def test_a_claim_lands_on_this_consumers_own_processing_list(self) -> None:
        redis = FakeRedis()
        queue = RedisQueue(redis, consumer_id="runner-7")
        queue.enqueue(_message("run_x"))

        queue.dequeue(timeout_s=0)

        assert redis.lists[f"{PROCESSING_KEY_PREFIX}:runner-7"]
        assert RUN_QUEUE_KEY not in redis.lists

    def test_dequeue_refreshes_the_liveness_key(self) -> None:
        redis = FakeRedis()
        RedisQueue(redis, consumer_id="runner-7").dequeue(timeout_s=0)
        assert f"{HEARTBEAT_KEY_PREFIX}:runner-7" in redis.strings

    def test_heartbeat_failure_is_not_fatal(self) -> None:
        """Losing observability of liveness must not stop the loop; the worst
        case is that this consumer's claims get recovered early, which
        at-least-once already covers."""

        class NoSet(FakeRedis):
            def set(self, key, value, ex=None):
                raise ConnectionError("redis went away")

        queue = RedisQueue(NoSet(), consumer_id="runner-7")
        queue.heartbeat()  # must not raise
        assert queue.dequeue(timeout_s=0) is None

    def test_recovery_takes_a_claim_with_ONE_atomic_move(self) -> None:
        """The lock-free safety argument, asserted rather than asserted-in-prose.

        If recovery read the list and then removed from it, two reapers racing
        could both requeue the same message and the job would run twice.
        """
        redis = FakeRedis()
        dying = RedisQueue(redis, consumer_id="runner-a")
        reaper = RedisQueue(redis, consumer_id="runner-b")
        dying.enqueue(_message("run_x"))
        dying.dequeue(timeout_s=0)
        redis.expire_now(f"{HEARTBEAT_KEY_PREFIX}:runner-a")
        redis.commands.clear()

        reaper.recover_abandoned()

        assert "lmove" in redis.commands, "the claim was taken atomically"
        assert "lrange" not in redis.commands, "not read-then-take"

    def test_a_drained_consumers_keys_are_cleaned_up(self) -> None:
        """Otherwise every dead pod leaves litter that every scan re-walks."""
        redis = FakeRedis()
        dying = RedisQueue(redis, consumer_id="runner-a")
        reaper = RedisQueue(redis, consumer_id="runner-b")
        dying.enqueue(_message("run_x"))
        dying.dequeue(timeout_s=0)
        redis.expire_now(f"{HEARTBEAT_KEY_PREFIX}:runner-a")

        reaper.recover_abandoned()

        assert f"{PROCESSING_KEY_PREFIX}:runner-a" not in redis.lists

    def test_an_undecodable_payload_goes_to_the_dead_letter_key(self) -> None:
        redis = FakeRedis()
        redis.rpush(RUN_QUEUE_KEY, b'{"not": "a valid message"}')
        queue = RedisQueue(redis)

        assert queue.dequeue(timeout_s=0) is None
        assert redis.lists[DEAD_LETTER_KEY] == [b'{"not": "a valid message"}']
        assert queue.dead_letter_depth() == 1

    def test_a_failing_dead_letter_write_does_not_escalate(self) -> None:
        """Redis being in trouble must not turn a bad message into a dead runner."""
        redis = BrokenPipelineRedis()
        redis.rpush(RUN_QUEUE_KEY, b"garbage")
        assert RedisQueue(redis).dequeue(timeout_s=0) is None  # logged, not raised

    def test_a_failing_requeue_leaves_the_claim_in_place(self) -> None:
        """The safe end of the failure: a message still on a processing list is
        recoverable.  Dropping it because the retry push failed would not be."""
        redis = BrokenPipelineRedis()
        queue = RedisQueue(redis, consumer_id="runner-a")
        redis.rpush(RUN_QUEUE_KEY, _message("run_x").to_wire())
        message = queue.dequeue(timeout_s=0)

        assert queue.nack(message, "boom") is NackOutcome.REQUEUED
        assert redis.lists[f"{PROCESSING_KEY_PREFIX}:runner-a"], "not lost"

    def test_a_recovery_pass_that_cannot_reach_redis_reports_nothing_and_lives(self) -> None:
        """Housekeeping failing must never be an exception the runner has to catch."""

        class NoScan(FakeRedis):
            def scan_iter(self, match=None, count=None):
                raise ConnectionError("redis went away")

        report = RedisQueue(NoScan()).recover_abandoned()
        assert report.total == 0

    def test_ping_reports_redis_health(self) -> None:
        class Down(FakeRedis):
            def ping(self):
                raise ConnectionError("nope")

        assert RedisQueue(FakeRedis()).ping() is True
        assert RedisQueue(Down()).ping() is False

    def test_depth_counts_only_waiting_jobs_not_claimed_ones(self) -> None:
        """`ida_llm_runner_queue_depth` drives capacity thinking; a claimed job
        is being worked on, not waiting for someone to work on it."""
        redis = FakeRedis()
        queue = RedisQueue(redis, consumer_id="runner-a")
        queue.enqueue(_message("run_a"))
        queue.enqueue(_message("run_b"))
        queue.dequeue(timeout_s=0)

        assert queue.depth() == 1
        assert queue.processing_depth() == 1

    def test_a_queue_on_a_DIFFERENT_key_gets_its_own_claim_namespace(self) -> None:
        """Isolation, and the reason it matters.

        Recovery works by scanning for processing lists. If that namespace were
        hard-coded rather than derived from the queue key, any second queue on
        the same Redis -- an integration test, a parallel environment, a
        migration -- would scan over a LIVE runner's claims and hand its
        in-flight jobs to somebody else. Deriving the namespace makes a distinct
        key genuinely distinct.
        """
        redis = FakeRedis()
        production = RedisQueue(redis, consumer_id="runner-a")
        elsewhere = RedisQueue(redis, key="ida:queue:runs-test", consumer_id="runner-b")
        production.enqueue(_message("run_live"))
        production.dequeue(timeout_s=0)  # a live, in-flight claim

        report = elsewhere.recover_abandoned()

        assert report.total == 0, "the other queue's claims are none of its business"
        assert _attempts(redis.lists[f"{PROCESSING_KEY_PREFIX}:runner-a"]) == [1]

    def test_the_published_prefixes_match_what_the_default_queue_actually_uses(self) -> None:
        """The constants are documentation; documentation that drifts is worse
        than none, so pin them to the real behaviour."""
        redis = FakeRedis()
        queue = RedisQueue(redis, consumer_id="runner-a")
        queue.enqueue(_message("run_x"))
        queue.dequeue(timeout_s=0)

        assert f"{PROCESSING_KEY_PREFIX}:runner-a" in redis.lists
        assert f"{HEARTBEAT_KEY_PREFIX}:runner-a" in redis.strings
