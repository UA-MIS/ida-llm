"""Transport retry: a Redis restart must cost an in-flight run *nothing*.

WHAT THIS FILE IS DEFENDING
---------------------------
``RedisQueue`` used to be built on a bare ``redis.Redis.from_url(url)``, which
has no command retry at all.  A restart -- ``docker compose restart redis``, a
node drain, a managed-Redis failover -- makes the server answer
``BusyLoadingError`` for the several seconds it spends replaying its AOF, and
drop connections either side of that.  Whichever queue call was in flight took
the exception, and the runner loop above it saw a job that "failed".

The fix is a retry at the **transport** layer.  The point of these tests is the
LAYERING, not the retry: the queue already has a retry budget
(``max_attempts`` / ``nack`` / ``DEAD_LETTER_KIND_RETRY_EXHAUSTED``) and it
counts something completely different -- deliveries of a *job* to a consumer
that then could not finish it.  A server that is briefly not answering has not
delivered anything.  If the two budgets ever met, a routine Redis restart would
dead-letter every run that happened to be in flight, which is a strictly worse
outage than the one being fixed.  :class:`TestTheTwoBudgetsAreSeparate` is
therefore the load-bearing class here, not :class:`TestTransportRetry`.

WHY A SCRIPTED CONNECTION AND NOT A MOCK CLIENT
-----------------------------------------------
The retry loop under test is *redis-py's* (``Retry.call_with_retry``, driven
from ``Redis._execute_command``), not ours -- we only configure it.  A mock
client with a hand-rolled "retry twice" wrapper would assert that a
reimplementation of redis-py works, which proves nothing about production.

So these tests build a **real** ``redis.Redis``, through the real
:func:`~ida_core.queue.redis_client_from_url`, over a real
``redis.connection.Connection`` subclass with the socket removed and a script in
its place.  Everything between the queue call and the wire is production code.
Nothing here needs a server, so it runs in CI, where there is none.

The backoff is flattened to zero *in the tests only* (``backoff_base_s=0``), so
proving ten retries happen costs no wall clock.  The production defaults --
~7s of retry against a ~6s AOF reload -- are asserted separately, as numbers, in
:class:`TestProductionDefaults`.
"""

from __future__ import annotations

import pytest
from _queue_fakes import FakeRedis

from ida_core.contracts import RunJobMessage
from ida_core.db import utcnow
from ida_core.queue import (
    DEAD_LETTER_KEY,
    DEFAULT_HEALTH_CHECK_INTERVAL_S,
    DEFAULT_TRANSPORT_BACKOFF_CAP_S,
    DEFAULT_TRANSPORT_RETRIES,
    RUN_QUEUE_KEY,
    NackOutcome,
    RedisQueue,
    redis_client_from_url,
)

redis = pytest.importorskip("redis")

from redis.connection import Connection  # noqa: E402
from redis.exceptions import BusyLoadingError, ResponseError  # noqa: E402
from redis.exceptions import ConnectionError as RedisConnectionError  # noqa: E402

TEST_URL = "redis://127.0.0.1:6379/15"
"""Never dialled.  The scripted connection below never opens a socket."""


def _message(run_id: str = "run_1", **overrides) -> RunJobMessage:
    base = {
        "run_id": run_id,
        "task_id": "demo/t",
        "model_key": "mock",
        "enqueued_at": utcnow(),
    }
    base.update(overrides)
    return RunJobMessage(**base)


class _Script:
    """The server's side of the conversation, and its fault injection.

    ``faults`` maps a command name to a list of exceptions to raise, one per
    call, before that command starts succeeding -- which is exactly the shape of
    a restart: N failures, then the server is back.  ``sent`` records every
    command the client actually put on the wire, so a test can assert on the
    number of *attempts*, not just on the final answer.  Distinguishing "it
    worked" from "it worked because it was retried" is most of the point.
    """

    def __init__(self, responses: dict, faults: dict | None = None) -> None:
        self.responses = responses
        self.faults = {name: list(errors) for name, errors in (faults or {}).items()}
        self.sent: list[tuple] = []

    def __call__(self, command: tuple):
        self.sent.append(command)
        name = command[0]
        queued = self.faults.get(name)
        if queued:
            raise queued.pop(0)
        if name not in self.responses:  # pragma: no cover - a test wrote a bad script
            raise AssertionError(f"the script has no response for {name!r}")
        return self.responses[name]

    def attempts(self, name: str) -> int:
        return sum(1 for command in self.sent if command[0] == name)

    def names(self) -> list[str]:
        return [
            command[0].decode() if isinstance(command[0], bytes) else str(command[0])
            for command in self.sent
        ]


class ScriptedConnection(Connection):
    """A real redis-py ``Connection`` with the socket swapped for a script.

    Subclassed rather than duck-typed on purpose: ``Connection.__init__`` is
    what turns our ``retry`` / ``retry_on_error`` configuration into the
    ``self.retry`` object that ``Redis._execute_command`` actually calls.  A
    stand-in that skipped it would skip the thing under test.
    """

    def __init__(self, *, script: _Script, **kwargs) -> None:
        self.script = script
        super().__init__(**kwargs)

    def connect(self) -> None:
        self._sock = self._sock or object()

    def disconnect(self, *args, **kwargs) -> None:
        # redis-py disconnects before every retry; that must stay cheap and
        # must not reset the script, or a "retry" would be indistinguishable
        # from a fresh client.
        self._sock = None

    def can_read(self, timeout: float = 0) -> bool:
        return False

    def send_command(self, *args, **kwargs) -> None:
        self._pending = args

    def read_response(self, **kwargs):
        return self.script(self._pending)


def _scripted_client(script: _Script, **overrides):
    """A production client -- same factory, same defaults -- over the script."""
    overrides.setdefault("backoff_base_s", 0)
    overrides.setdefault("backoff_cap_s", 0)
    return redis_client_from_url(
        TEST_URL,
        connection_class=ScriptedConnection,
        script=script,
        **overrides,
    )


class TestProductionDefaults:
    """The numbers, as numbers.  These are what ship; the behavioural tests
    below deliberately flatten the backoff and so cannot assert them."""

    def test_the_retry_window_outlasts_an_aof_reload(self) -> None:
        """~6s of BusyLoadingError is the failure being bought off.  A retry
        budget that expires first would be decoration."""
        span = DEFAULT_TRANSPORT_RETRIES * DEFAULT_TRANSPORT_BACKOFF_CAP_S
        assert span >= 6, "transport retry must outlast a restarting Redis's AOF reload"

    def test_the_retry_window_is_bounded(self) -> None:
        """A runner blocked forever in a queue call never heartbeats, never
        reports and never exits.  Infinite retry trades one outage for a worse
        one."""
        assert 0 < DEFAULT_TRANSPORT_RETRIES < 100

    def test_idle_connections_are_health_checked(self) -> None:
        """Retry heals the command in flight during a restart; the health check
        heals the pooled connections that were idle through it."""
        assert 0 < DEFAULT_HEALTH_CHECK_INTERVAL_S <= 60


class TestClientConfiguration:
    """The wiring, asserted where a caller would actually get it."""

    def test_from_url_builds_a_client_with_transport_retry(self) -> None:
        """`RedisQueue.from_url` is the ONLY constructor the API, the runner and
        the sweep driver use.  Retry configured anywhere else is retry that some
        caller will forget."""
        queue = RedisQueue.from_url(TEST_URL)
        connection = queue._redis.connection_pool.make_connection()

        assert BusyLoadingError in connection.retry_on_error
        assert RedisConnectionError in connection.retry_on_error
        assert connection.health_check_interval == DEFAULT_HEALTH_CHECK_INTERVAL_S
        assert connection.retry._retries == DEFAULT_TRANSPORT_RETRIES

    def test_a_caller_can_still_override(self) -> None:
        """The defaults are a floor for production, not a cage for tests."""
        client = redis_client_from_url(TEST_URL, transport_retries=2, socket_connect_timeout=2)
        connection = client.connection_pool.make_connection()

        assert connection.retry._retries == 2
        assert connection.socket_connect_timeout == 2


class TestTransportRetry:
    """Does redis-py, configured this way, actually retry?"""

    def test_busy_loading_is_retried_until_the_server_finishes_loading(self) -> None:
        """The restart case, exactly: three BusyLoadingErrors, then a server."""
        script = _Script(
            responses={"PING": b"PONG"},
            faults={"PING": [BusyLoadingError("Redis is loading the dataset in memory")] * 3},
        )
        client = _scripted_client(script)

        assert client.ping() is True
        assert script.attempts("PING") == 4, "3 failures + the one that succeeded"

    def test_a_dropped_connection_is_retried(self) -> None:
        """The other half of a restart: the TCP connection goes away either side
        of the reload."""
        script = _Script(
            responses={"PING": b"PONG"},
            faults={"PING": [RedisConnectionError("Connection closed by server")] * 2},
        )
        client = _scripted_client(script)

        assert client.ping() is True
        assert script.attempts("PING") == 3

    def test_retry_is_bounded_and_the_error_still_surfaces(self) -> None:
        """A server that never comes back must raise, not hang.  `retries=2`
        means three attempts total, and then the truth."""
        script = _Script(
            responses={"PING": b"PONG"},
            faults={"PING": [BusyLoadingError("still loading")] * 10},
        )
        client = _scripted_client(script, transport_retries=2)

        with pytest.raises(BusyLoadingError):
            client.ping()
        assert script.attempts("PING") == 3

    def test_an_error_that_is_not_a_transport_failure_is_not_retried(self) -> None:
        """Retry is scoped to "the server was not there".  A command Redis
        actively refused is an answer, and re-sending it just multiplies it."""
        script = _Script(
            responses={},
            faults={"PING": [ResponseError("WRONGTYPE")] * 5},
        )
        client = _scripted_client(script)

        with pytest.raises(ResponseError):
            client.ping()
        assert script.attempts("PING") == 1, "a refusal must cost exactly one round trip"


class TestTheTwoBudgetsAreSeparate:
    """THE LOAD-BEARING CLASS.  Transport retry must be invisible to the job.

    A restart resolved by the transport must not spend a delivery from
    ``max_attempts``, must not go anywhere near ``nack``, and must not park
    anything on the dead-letter list.  If it did, a six-second restart would
    dead-letter every run in flight -- worse than the crash it replaced.
    """

    def _dequeue_over_a_restarting_redis(self, faults: list[Exception]):
        message = _message()
        script = _Script(
            responses={"SET": b"OK", "BLMOVE": message.to_wire().encode()},
            faults={"BLMOVE": faults},
        )
        queue = RedisQueue.from_url(
            TEST_URL,
            client_kwargs={
                "connection_class": ScriptedConnection,
                "script": script,
                "backoff_base_s": 0,
                "backoff_cap_s": 0,
            },
        )
        return queue, script, message

    def test_a_restart_mid_dequeue_delivers_the_job_unharmed(self) -> None:
        queue, script, original = self._dequeue_over_a_restarting_redis(
            [BusyLoadingError("Redis is loading the dataset in memory")] * 3
        )

        claimed = queue.dequeue(timeout_s=5)

        assert claimed is not None, "a restarting server must not look like an empty queue"
        assert claimed.run_id == original.run_id
        assert script.attempts("BLMOVE") == 4, "the transport, not the caller, absorbed the restart"

    def test_a_restart_does_not_spend_one_of_the_job_s_attempts(self) -> None:
        """`attempt` is the job's budget.  The transport may not bill it."""
        queue, _script, original = self._dequeue_over_a_restarting_redis(
            [BusyLoadingError("loading")] * 3
        )

        claimed = queue.dequeue(timeout_s=5)

        # `attempt` is 1-based (`RunJobMessage.attempt` is `ge=1`): 1 means
        # "this is still the first delivery". Compared against the message that
        # was actually enqueued, so the assertion cannot drift with the default.
        assert claimed is not None
        assert claimed.attempt == original.attempt == 1

    def test_a_restart_dead_letters_nothing_and_requeues_nothing(self) -> None:
        """The strongest form of "the queue never saw it": the ONLY commands
        that reached the wire are the heartbeat and the claim.  No LPUSH to the
        dead-letter key, no RPUSH putting the job back -- neither the poison
        path nor the retry-exhausted path ran at all."""
        queue, script, _original = self._dequeue_over_a_restarting_redis(
            [BusyLoadingError("loading"), RedisConnectionError("connection closed")]
        )

        queue.dequeue(timeout_s=5)

        assert set(script.names()) == {"SET", "BLMOVE"}
        assert not any(DEAD_LETTER_KEY in str(command) for command in script.sent)
        assert not any(
            command[0] in {"RPUSH", "LPUSH"} and RUN_QUEUE_KEY in str(command)
            for command in script.sent
        )

    def test_by_contrast_a_failed_job_still_spends_its_attempts(self) -> None:
        """The control.  Transport retry must not have softened the job-level
        budget it sits underneath: a consumer that genuinely could not finish
        the work still burns deliveries and still dead-letters on the last one.

        Over the faithful `FakeRedis`, so this asserts the queue's own logic
        rather than redis-py's."""
        fake = FakeRedis()
        queue = RedisQueue(fake, max_attempts=2, consumer_id="c1")
        queue.enqueue(_message())

        first = queue.dequeue(timeout_s=0)
        assert first is not None
        assert first.attempt == 1
        assert queue.nack(first, "boom") is NackOutcome.REQUEUED

        second = queue.dequeue(timeout_s=0)
        assert second is not None
        assert second.attempt == 2, "a real delivery failure DOES advance the job's budget"
        assert queue.nack(second, "boom") is NackOutcome.DEAD_LETTERED
        assert len(fake.lrange(DEAD_LETTER_KEY, 0, -1)) == 1
