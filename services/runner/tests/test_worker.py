"""Worker behaviour: job execution, failure policy, loop robustness.

The failure-policy tests matter most: a poisonous job must never crash-loop a
runner pod, and an unresolvable job must leave a *readable* failed run rather
than a silently stuck one.
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest
from tests.conftest import SUBJECTIVE_TASK, VERIFIABLE_TASK

from ida_core.artifacts import eval_log_key, sample_key
from ida_core.contracts import (
    RunJobMessage,
    RunRecord,
    RunStatus,
    SamplingParams,
)
from ida_core.db import session_scope, utcnow
from ida_core.ids import new_run_id
from ida_core.repositories import (
    create_run,
    get_run,
    list_results_for_run,
    result_row_to_record,
    run_row_to_record,
)
from ida_harness.client import OpenAICompatibleClient
from ida_runner.worker import Worker, execute_job


def _seed_run(session_factory, task_id: str = VERIFIABLE_TASK, **overrides) -> str:
    run_id = new_run_id()
    base = {
        "id": run_id,
        "status": RunStatus.QUEUED,
        "task_id": task_id,
        "model_key": "mock",
        "harness_version": "0.1.0",
        "task_git_sha": "e" * 40,
    }
    base.update(overrides)
    with session_scope(session_factory) as session:
        create_run(session, RunRecord(**base))
    return run_id


def _message(run_id: str, task_id: str = VERIFIABLE_TASK, **overrides) -> RunJobMessage:
    base = {
        "run_id": run_id,
        "task_id": task_id,
        "model_key": "mock",
        "enqueued_at": utcnow(),
    }
    base.update(overrides)
    return RunJobMessage(**base)


def _execute(message, *, session_factory, registry, catalog, artifact_store, **kwargs):
    return execute_job(
        message,
        session_factory=session_factory,
        registry=registry,
        catalog=catalog,
        artifact_store=artifact_store,
        **kwargs,
    )


class TestHappyPath:
    def test_run_succeeds_and_scores_every_sample(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        run_id = _seed_run(session_factory)
        record = _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        assert record.status is RunStatus.SUCCEEDED
        assert record.sample_count == 4
        assert record.scored_count == 4
        assert record.mean_score == 1.0, "the mock answers arithmetic correctly"
        assert record.error is None

    def test_persists_the_terminal_state(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        run_id = _seed_run(session_factory)
        _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        with session_scope(session_factory) as session:
            stored = run_row_to_record(get_run(session, run_id))
        assert stored.status is RunStatus.SUCCEEDED
        assert stored.mean_score == 1.0
        assert stored.started_at is not None and stored.finished_at is not None
        assert stored.serving_config is not None

    def test_persists_one_result_row_per_sample_with_artifact_pointers(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        run_id = _seed_run(session_factory)
        _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        with session_scope(session_factory) as session:
            results = [result_row_to_record(r) for r in list_results_for_run(session, run_id)]
        assert len(results) == 4
        for result in results:
            assert result.transcript_uri is not None
            assert artifact_store.exists(sample_key(run_id, result.sample_id))
        assert artifact_store.exists(eval_log_key(run_id))

    def test_token_accounting_is_rolled_up(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        run_id = _seed_run(session_factory)
        record = _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        assert record.total_usage.total_tokens > 0
        with session_scope(session_factory) as session:
            per_sample = sum(
                result_row_to_record(r).usage.total_tokens
                for r in list_results_for_run(session, run_id)
            )
        assert per_sample == record.total_usage.total_tokens

    def test_serving_config_is_recorded_at_claim_time(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """D-1: even a run that later fails must show what it was going to use."""
        run_id = _seed_run(session_factory)
        record = _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        assert record.serving_config is not None
        assert record.serving_config.registry_key == "mock"
        assert record.serving_config.model_id == "mock-echo-1"

    def test_sampling_override_lands_on_the_stored_results(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        run_id = _seed_run(session_factory)
        override = SamplingParams(temperature=0.3, max_tokens=32, seed=5)
        _execute(
            _message(run_id, sampling_override=override),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        with session_scope(session_factory) as session:
            stored = result_row_to_record(list_results_for_run(session, run_id)[0])
        assert stored.serving_config.sampling == override


class TestSubjectiveTask:
    def test_succeeds_with_null_scores_not_zeros(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        run_id = _seed_run(session_factory, task_id=SUBJECTIVE_TASK)
        record = _execute(
            _message(run_id, task_id=SUBJECTIVE_TASK),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        assert record.status is RunStatus.SUCCEEDED
        assert record.sample_count == 2
        assert record.scored_count == 0
        assert record.mean_score is None
        with session_scope(session_factory) as session:
            results = [result_row_to_record(r) for r in list_results_for_run(session, run_id)]
        assert all(r.score is None and r.scorable is False for r in results)
        assert all(r.transcript_uri is not None for r in results)


class TestFailurePolicy:
    def test_unknown_task_fails_the_run_readably(
        self, session_factory, registry, catalog, artifact_store
    ) -> None:
        run_id = _seed_run(session_factory, task_id="ghost/task")
        record = _execute(
            _message(run_id, task_id="ghost/task"),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
        )
        assert record.status is RunStatus.FAILED
        assert "ghost/task" in record.error
        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, run_id)).status is RunStatus.FAILED

    def test_unknown_model_fails_the_run(
        self, session_factory, registry, catalog, artifact_store
    ) -> None:
        run_id = _seed_run(session_factory, model_key="ghost")
        record = _execute(
            _message(run_id, model_key="ghost"),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
        )
        assert record.status is RunStatus.FAILED
        assert "ghost" in record.error

    def test_missing_api_key_fails_the_run_rather_than_sending_an_empty_header(
        self, session_factory, registry, catalog, artifact_store, monkeypatch
    ) -> None:
        monkeypatch.delenv("NEEDED_KEY", raising=False)
        registry.get("mock").api_key_env = "NEEDED_KEY"
        run_id = _seed_run(session_factory)
        record = _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
        )
        assert record.status is RunStatus.FAILED
        assert "NEEDED_KEY" in record.error

    def test_endpoint_down_degrades_samples_and_the_run_says_so(
        self, session_factory, registry, catalog, artifact_store
    ) -> None:
        """A dead endpoint is a per-sample error -- and the run reports FAILED.

        The containment policy is unchanged (every sample still produces a
        record, the loop still finishes). What changed is the verdict: a run in
        which nothing was measured used to be recorded ``succeeded``, which told
        the reader the model had been benchmarked when it had not (B5).
        """

        registry.get("mock").max_retries = 0

        def dead_client_factory() -> OpenAICompatibleClient:
            def handler(request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("connection refused", request=request)

            return OpenAICompatibleClient(
                registry.get("mock"),
                transport=httpx.MockTransport(handler),
                sleep=lambda _s: None,
                jitter=lambda _lo, hi: hi,
            )

        run_id = _seed_run(session_factory)
        record = _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=dead_client_factory,
        )
        assert record.status is RunStatus.FAILED, "nothing was measured"
        assert record.scored_count == 0
        assert record.error_count == 4
        assert record.mean_score is None
        assert record.error is not None and "4/4 samples failed" in record.error
        with session_scope(session_factory) as session:
            results = [result_row_to_record(r) for r in list_results_for_run(session, run_id)]
        assert len(results) == 4, "every sample still produces exactly one record"
        assert all("TransientModelError" in (r.error or "") for r in results)
        assert all(r.scorable is True for r in results), (
            "these are FAILED verifiable samples, not not-yet-scorable ones -- "
            "the distinction the UI needs (B1)"
        )

    def test_message_for_a_missing_run_row_raises_loudly(
        self, session_factory, registry, catalog, artifact_store
    ) -> None:
        """That combination means data loss; silently ignoring it would hide it."""
        with pytest.raises(KeyError, match="data loss"):
            _execute(
                _message("run_never_created"),
                session_factory=session_factory,
                registry=registry,
                catalog=catalog,
                artifact_store=artifact_store,
            )


class TestWorkerLoop:
    def test_consumes_a_queued_job(
        self,
        queue,
        session_factory,
        registry,
        catalog,
        artifact_store,
        mock_transport_factory,
    ) -> None:
        run_id = _seed_run(session_factory)
        queue.enqueue(_message(run_id))
        worker = Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=1,
            client_factory=mock_transport_factory,
        )
        assert worker.run_forever(max_jobs=1) == 1
        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, run_id)).status is RunStatus.SUCCEEDED

    def test_a_job_that_raises_during_processing_does_not_kill_the_loop(
        self,
        queue,
        session_factory,
        registry,
        catalog,
        artifact_store,
        mock_transport_factory,
    ) -> None:
        """A crash-looping runner pod is how you lose a whole sweep.

        NOTE: this covers only the *processing* half. It enqueues a
        structurally VALID message that fails inside `execute_job`, so it
        exercises the protected `_process` path. It was previously named
        `test_a_poisonous_job_does_not_kill_the_loop`, which claimed a property
        it never tested -- the decode path was unprotected and a genuinely
        malformed payload killed the process. The decode half now has its own
        tests in TestPoisonMessages below; the two names must stay distinct so
        neither is mistaken for the other again.
        """
        good_id = _seed_run(session_factory)
        queue.enqueue(_message("run_does_not_exist"))  # execute_job raises KeyError
        queue.enqueue(_message(good_id))
        worker = Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=1,
            client_factory=mock_transport_factory,
        )
        assert worker.run_forever(max_jobs=2) == 2
        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, good_id)).status is RunStatus.SUCCEEDED

    def test_empty_queue_does_not_spin_or_crash(
        self, queue, session_factory, registry, catalog, artifact_store
    ) -> None:
        worker = Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=0,
        )
        thread = threading.Thread(target=worker.run_forever, daemon=True)
        thread.start()
        worker.stop()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert worker.jobs_processed == 0

    def test_stop_is_idempotent(
        self, queue, session_factory, registry, catalog, artifact_store
    ) -> None:
        worker = Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
        )
        worker.stop()
        worker.stop()
        assert worker.stopped
        assert worker.run_forever() == 0


class TestPoisonMessages:
    """B2 — a payload the runner cannot decode must not take the runner down.

    Reproduced before the fix: ``RPUSH ida:queue:runs '{"not":"a valid message"}'``
    against the live stack left ``capstone-ida-runner-1 Exited (1)``, the queue
    stuck, and subsequently enqueued legitimate runs sitting ``queued`` forever.
    The decode happened inside ``dequeue()``, which sat *outside* the loop's
    ``try``, so the exception escaped ``run_forever`` -> ``main()`` -> exit.

    The realistic trigger is not an attacker. It is the **designed** forward
    compatibility path: the moment anyone bumps ``schema_version`` while older
    replicas are still rolling, every old replica meets a message it cannot
    parse. ``RunJobMessage``'s docstring promises it will "refuse loudly"; it
    used to die instead.
    """

    def _worker(self, queue, session_factory, registry, catalog, artifact_store, factory):
        return Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=0,
            client_factory=factory,
        )

    @pytest.mark.parametrize(
        "payload",
        [
            b"not json at all",
            b'{"not": "a valid message"}',
            b"",
            b"[]",
            b'{"run_id": "r", "task_id": "t"}',  # missing required fields
            b'{"schema_version": 2, "run_id": "r", "task_id": "t", "model_key": "m",'
            b' "enqueued_at": "2026-01-01T00:00:00Z"}',  # the version-bump case
        ],
        ids=["garbage", "wrong-shape", "empty", "array", "incomplete", "future-version"],
    )
    def test_the_worker_survives_every_kind_of_bad_payload(
        self,
        payload: bytes,
        queue,
        session_factory,
        registry,
        catalog,
        artifact_store,
        mock_transport_factory,
    ) -> None:
        good_id = _seed_run(session_factory)
        queue.enqueue_raw(payload)
        queue.enqueue(_message(good_id))

        worker = self._worker(
            queue, session_factory, registry, catalog, artifact_store, mock_transport_factory
        )
        worker.run_forever(max_jobs=1)

        # The legitimate job that was queued BEHIND the poison message ran.
        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, good_id)).status is RunStatus.SUCCEEDED

    def test_the_bad_payload_is_parked_not_lost(self, queue) -> None:
        """Dropping it silently loses the evidence of whatever produced it."""
        queue.enqueue_raw(b'{"not": "a valid message"}')
        assert queue.dequeue(timeout_s=0) is None
        assert queue.dead_letters == [b'{"not": "a valid message"}']

    def test_a_bad_payload_is_not_counted_as_a_processed_job(
        self,
        queue,
        session_factory,
        registry,
        catalog,
        artifact_store,
        mock_transport_factory,
    ) -> None:
        queue.enqueue_raw(b"garbage")
        worker = self._worker(
            queue, session_factory, registry, catalog, artifact_store, mock_transport_factory
        )
        worker.stop()
        worker.run_forever()
        assert worker.jobs_processed == 0

    def test_a_burst_of_poison_does_not_stop_consumption(
        self,
        queue,
        session_factory,
        registry,
        catalog,
        artifact_store,
        mock_transport_factory,
    ) -> None:
        """One bad producer must not be able to wedge the whole runner tier."""
        good_id = _seed_run(session_factory)
        for i in range(10):
            queue.enqueue_raw(f"garbage-{i}".encode())
        queue.enqueue(_message(good_id))

        worker = self._worker(
            queue, session_factory, registry, catalog, artifact_store, mock_transport_factory
        )
        worker.run_forever(max_jobs=1)

        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, good_id)).status is RunStatus.SUCCEEDED
        assert len(queue.dead_letters) == 10

    def test_the_loop_survives_a_queue_that_breaks_its_no_raise_contract(
        self, session_factory, registry, catalog, artifact_store
    ) -> None:
        """Defence in depth: even a misbehaving RunQueue must not exit the process."""

        class RaisingQueue:
            def __init__(self) -> None:
                self.reads = 0

            def enqueue(self, message): ...

            def dequeue(self, timeout_s=5):
                self.reads += 1
                raise ConnectionError("redis went away mid-read")

            def depth(self):
                return 0

        queue = RaisingQueue()
        worker = Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=0,
        )

        def stop_soon() -> None:
            while queue.reads < 3:
                time.sleep(0.01)
            worker.stop()

        stopper = threading.Thread(target=stop_soon, daemon=True)
        stopper.start()
        worker.run_forever()
        stopper.join(timeout=5)

        assert worker.dequeue_failures >= 3, "the failures were counted, not fatal"
        assert worker.jobs_processed == 0


class TestRedisDeadLettering:
    """The Redis implementation must park undecodable payloads too.

    Driven through a minimal fake that implements the Redis commands used --
    enough to pin the dead-letter behaviour without a live server. The Redis
    path itself is exercised for real by the compose tracer.
    """

    class _FakeRedis:
        def __init__(self, payloads: list[bytes]) -> None:
            self.lists: dict[str, list[bytes]] = {"ida:queue:runs": list(payloads)}
            self.trimmed = False

        def blpop(self, keys, timeout=0):
            key = keys[0]
            if not self.lists.get(key):
                return None
            return (key.encode(), self.lists[key].pop(0))

        def rpush(self, key, value):
            self.lists.setdefault(key, []).append(value)

        def llen(self, key):
            return len(self.lists.get(key, []))

        def ltrim(self, key, start, end):
            self.trimmed = True

        def pipeline(self):
            outer = self

            class _Pipe:
                def __init__(self):
                    self.ops = []

                def rpush(self, key, value):
                    self.ops.append(lambda: outer.rpush(key, value))
                    return self

                def ltrim(self, key, start, end):
                    self.ops.append(lambda: outer.ltrim(key, start, end))
                    return self

                def execute(self):
                    for op in self.ops:
                        op()

            return _Pipe()

    def test_undecodable_payload_goes_to_the_dead_letter_key(self) -> None:
        from ida_core.queue import DEAD_LETTER_KEY, RedisQueue

        fake = self._FakeRedis([b'{"not": "a valid message"}'])
        queue = RedisQueue(fake)
        assert queue.dequeue(timeout_s=0) is None
        assert fake.lists[DEAD_LETTER_KEY] == [b'{"not": "a valid message"}']
        assert queue.dead_letter_depth() == 1

    def test_the_dead_letter_list_is_bounded(self) -> None:
        """An unbounded dead-letter list is its own outage."""
        from ida_core.queue import RedisQueue

        fake = self._FakeRedis([b"garbage"])
        RedisQueue(fake).dequeue(timeout_s=0)
        assert fake.trimmed, "ltrim must cap the list"

    def test_a_valid_payload_still_decodes(self) -> None:
        from ida_core.queue import RedisQueue

        message = _message("run_ok")
        fake = self._FakeRedis([message.to_wire().encode()])
        assert RedisQueue(fake).dequeue(timeout_s=0).run_id == "run_ok"

    def test_a_failing_dead_letter_write_does_not_escalate(self) -> None:
        """Redis being in trouble must not turn a bad message into a dead runner."""
        from ida_core.queue import RedisQueue

        class BrokenRedis(TestRedisDeadLettering._FakeRedis):
            def pipeline(self):
                raise ConnectionError("redis is down")

        queue = RedisQueue(BrokenRedis([b"garbage"]))
        assert queue.dequeue(timeout_s=0) is None  # logged, not raised


class TestRunRollupHonesty:
    """B5 at the persistence layer: what the UI and the recommender actually read."""

    def test_an_all_errored_run_is_persisted_as_failed(
        self, session_factory, registry, catalog, artifact_store
    ) -> None:
        registry.get("mock").max_retries = 0

        def dead_factory() -> OpenAICompatibleClient:
            def handler(request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("connection refused", request=request)

            return OpenAICompatibleClient(
                registry.get("mock"),
                transport=httpx.MockTransport(handler),
                sleep=lambda _s: None,
                jitter=lambda _lo, hi: hi,
            )

        run_id = _seed_run(session_factory)
        _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=dead_factory,
        )
        with session_scope(session_factory) as session:
            stored = run_row_to_record(get_run(session, run_id))

        assert stored.status is RunStatus.FAILED, "previously recorded as 'succeeded'"
        assert stored.error_count == 4
        assert stored.scored_count == 0
        assert stored.mean_score is None
        assert stored.error is not None and "4/4 samples failed" in stored.error

    def test_a_subjective_run_is_persisted_as_succeeded_with_zero_errors(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """The contrast that B1 depended on being visible in the run row."""
        run_id = _seed_run(session_factory, task_id=SUBJECTIVE_TASK)
        _execute(
            _message(run_id, task_id=SUBJECTIVE_TASK),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        with session_scope(session_factory) as session:
            stored = run_row_to_record(get_run(session, run_id))

        assert stored.status is RunStatus.SUCCEEDED
        assert stored.error_count == 0
        assert stored.scored_count == 0
        assert stored.mean_score is None

    def test_provenance_reaches_the_stored_rows(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """B8/B9 — sweep and task-content hash must survive to the database."""
        run_id = _seed_run(session_factory, sweep_id="swp_test")
        _execute(
            _message(run_id, sweep_id="swp_test"),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        with session_scope(session_factory) as session:
            stored = run_row_to_record(get_run(session, run_id))
            results = [result_row_to_record(r) for r in list_results_for_run(session, run_id)]

        assert stored.sweep_id == "swp_test"
        assert stored.task_content_sha == catalog.get(VERIFIABLE_TASK).content_sha
        assert all(r.task_content_sha == stored.task_content_sha for r in results)
        assert all(r.repeat_index == 0 for r in results)
        assert all(r.cached is False for r in results)
