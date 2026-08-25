"""The reliable-queue path against a REAL Redis.

WHY THIS IS OPT-IN AND NOT PART OF THE DEFAULT RUN
--------------------------------------------------
The python CI job runs no Redis service container -- only ``migrations`` gets a
service, and it gets Postgres (see ``.github/workflows/ci.yml``). Adding one is a
workflow change, and the workflows are not this story's to touch. So these tests
**skip** unless a Redis is offered, and the everyday guarantee is carried by the
parity suite in ``test_queue.py`` against a deliberately faithful fake.

Stated plainly, because it matters when reading a green build: **CI does not run
these.** They run locally, against the Redis in ``docker-compose.yml``:

    docker compose up -d redis
    IDA_TEST_REDIS_URL=redis://127.0.0.1:6379/15 pytest packages/core/tests/test_queue_redis_integration.py

What they are for is the class of bug a fake structurally cannot catch: real
``BLMOVE``/``LREM`` byte-encoding, a real ``SCAN`` cursor, and a real key TTL
actually elapsing -- which is the only thing that makes "the runner died" a fact
rather than a flag a test sets.

SAFETY
------
Every test runs on its own randomised key namespace, and the processing and
liveness namespaces are DERIVED from that key, so nothing here can see -- let
alone reap -- claims belonging to a runner someone has running locally. Keys are
deleted afterwards. Nothing calls ``FLUSHDB``.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from ida_core.contracts import RunJobMessage
from ida_core.db import utcnow
from ida_core.queue import NackOutcome, RedisQueue

REDIS_URL = os.environ.get("IDA_TEST_REDIS_URL", "")

pytestmark = pytest.mark.skipif(
    not REDIS_URL,
    reason="set IDA_TEST_REDIS_URL (e.g. redis://127.0.0.1:6379/15) to run against a real Redis",
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


@pytest.fixture
def redis_client():
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2)
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"no Redis at {REDIS_URL}: {exc}")
    return client


@pytest.fixture
def key(redis_client):
    """A private key namespace, torn down afterwards.  See SAFETY above."""
    name = f"ida:test:queue:{uuid.uuid4().hex}"
    yield name
    for found in redis_client.scan_iter(match=f"{name}*", count=100):
        redis_client.delete(found)


def _queue(redis_client, key: str, consumer_id: str, **kwargs) -> RedisQueue:
    return RedisQueue(
        redis_client,
        key=key,
        dead_key=f"{key}:dead",
        consumer_id=consumer_id,
        **kwargs,
    )


class TestAgainstRealRedis:
    def test_a_claim_survives_a_round_trip_and_the_ack_matches_it(self, redis_client, key) -> None:
        """The byte-encoding trap, against the real encoder.

        The message is pushed as `str` and comes back from BLMOVE as `bytes`;
        the ack removes it with `LREM`. If those did not compare equal in Redis,
        every single job would leak a claim -- and a fake that stored Python
        objects would never notice.
        """
        queue = _queue(redis_client, key, "runner-a")
        queue.enqueue(_message("run_bytes"))

        message = queue.dequeue(timeout_s=1)

        assert message is not None and message.run_id == "run_bytes"
        assert queue.depth() == 0
        assert queue.processing_depth() == 1, "claimed, not consumed"

        queue.ack(message)
        assert queue.processing_depth() == 0, "LREM matched the bytes Redis actually holds"

    def test_a_dead_runners_job_comes_back_after_its_TTL_really_expires(
        self, redis_client, key
    ) -> None:
        """The whole story, with a real clock and a real key expiry.

        A 1-second heartbeat TTL keeps this quick; in production it is 90s. This
        is the one assertion the fake cannot make honestly -- there, "the runner
        died" is a method call.
        """
        dying = _queue(redis_client, key, "runner-a", heartbeat_ttl_s=1)
        survivor = _queue(redis_client, key, "runner-b", heartbeat_ttl_s=60)
        dying.enqueue(_message("run_interrupted"))
        assert dying.dequeue(timeout_s=1) is not None
        assert dying.depth() == 0

        # No ack, no nack -- the pod is simply gone. Wait for Redis to forget it.
        deadline = time.monotonic() + 10
        while redis_client.exists(f"{key}:alive:runner-a") and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not redis_client.exists(f"{key}:alive:runner-a"), "the TTL did not elapse"

        report = survivor.recover_abandoned()

        assert report.requeued == ["run_interrupted"]
        redelivered = survivor.dequeue(timeout_s=1)
        assert redelivered is not None
        assert redelivered.run_id == "run_interrupted"
        assert redelivered.attempt == 2, "one attempt was spent by the runner that died"

    def test_a_live_runners_claim_is_not_touched(self, redis_client, key) -> None:
        """A slow runner is not a dead one -- against a real EXISTS/SCAN."""
        busy = _queue(redis_client, key, "runner-a", heartbeat_ttl_s=60)
        reaper = _queue(redis_client, key, "runner-b", heartbeat_ttl_s=60)
        busy.enqueue(_message("run_long"))
        busy.dequeue(timeout_s=1)

        report = reaper.recover_abandoned()

        assert report.total == 0
        assert busy.processing_depth() == 1
        assert reaper.live_claims() == {"run_long"}

    def test_retries_are_bounded_and_end_on_the_dead_letter_list(self, redis_client, key) -> None:
        queue = _queue(redis_client, key, "runner-a", max_attempts=2)
        queue.enqueue(_message("run_doomed"))

        assert queue.nack(queue.dequeue(timeout_s=1), "boom") is NackOutcome.REQUEUED
        second = queue.dequeue(timeout_s=1)
        assert second.attempt == 2
        assert queue.nack(second, "boom again") is NackOutcome.DEAD_LETTERED

        assert queue.depth() == 0
        assert queue.processing_depth() == 0
        assert queue.dead_letter_depth() == 1

    def test_an_undecodable_payload_is_parked_as_its_exact_bytes(self, redis_client, key) -> None:
        """The schema-bump path, on the real transport."""
        queue = _queue(redis_client, key, "runner-a")
        redis_client.rpush(key, b"\xff\xfe not even valid utf-8")

        assert queue.dequeue(timeout_s=1) is None
        assert queue.processing_depth() == 0
        assert redis_client.lrange(f"{key}:dead", 0, -1) == [b"\xff\xfe not even valid utf-8"]

    def test_a_claim_namespace_is_private_to_its_queue_key(self, redis_client, key) -> None:
        """The isolation this whole test module depends on, verified for real.

        If it did not hold, running these tests against a developer's Redis
        would hand their local runner's in-flight jobs to a test process.
        """
        mine = _queue(redis_client, key, "runner-a", heartbeat_ttl_s=60)
        other_key = f"{key}-other"
        theirs = _queue(redis_client, other_key, "runner-a", heartbeat_ttl_s=60)
        try:
            theirs.enqueue(_message("run_theirs"))
            theirs.dequeue(timeout_s=1)
            redis_client.delete(f"{other_key}:alive:runner-a")  # their runner "dies"

            report = mine.recover_abandoned()

            assert report.total == 0, "another queue key's claims are none of its business"
            assert theirs.processing_depth() == 1
        finally:
            for found in redis_client.scan_iter(match=f"{other_key}*", count=100):
                redis_client.delete(found)
