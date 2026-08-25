"""Worker behaviour: job execution, failure policy, loop robustness.

The failure-policy tests matter most: a poisonous job must never crash-loop a
runner pod, and an unresolvable job must leave a *readable* failed run rather
than a silently stuck one.
"""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest
from _runner_helpers import (
    SUBJECTIVE_TASK,
    VERIFIABLE_TASK,
)
from _runner_helpers import (
    job_message as _message,
)
from _runner_helpers import (
    seed_run as _seed_run,
)

from ida_core.artifacts import eval_log_key, sample_key
from ida_core.contracts import (
    RunStatus,
    SamplingParams,
)
from ida_core.db import session_scope, utcnow
from ida_core.queue import InMemoryQueue
from ida_core.repositories import (
    get_run,
    list_results_for_run,
    result_row_to_record,
    run_row_to_record,
)
from ida_harness.client import OpenAICompatibleClient
from ida_runner.reaper import Reaper
from ida_runner.worker import Worker, execute_job


def _drain(worker: Worker, *, jobs: int, timeout: float = 10.0) -> None:
    """Run the loop for ``jobs`` messages, turning a HANG into a failure.

    `run_forever(max_jobs=N)` with a zero poll timeout spins until N messages
    have been consumed. That is fine while the code is correct -- and it means a
    regression that stops a message being requeued does not fail these tests, it
    WEDGES them, and CI reports a job timeout with no indication of which
    property broke. Found the hard way: mutating out the worker's nack hung the
    suite instead of failing it.

    A test that cannot fail loudly is not a test.
    """
    thread = threading.Thread(target=worker.run_forever, kwargs={"max_jobs": jobs}, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        worker.stop()
        thread.join(timeout=5)
        pytest.fail(
            f"the loop was still waiting for job {worker.jobs_processed + 1} of {jobs} "
            f"after {timeout}s -- a message that should have been requeued was not"
        )


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


# NOTE: the Redis implementation's own tests -- dead-lettering, claim/ack,
# recovery -- now live in `packages/core/tests/test_queue.py`, next to the
# contract they belong to and next to the parity suite that runs the SAME
# assertions against InMemoryQueue. They were here because there was nowhere
# else; keeping two half-fakes of Redis in two distributions is how the double
# and the real thing come to disagree.


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


class TestClaimAckAndRetry:
    """What the worker does with a claim -- the half the queue cannot decide.

    The queue owns "retry or park"; the worker owns the run ROW. A message put
    back on the queue while its row still says `running`, or dead-lettered while
    its row says `running` for ever, is only half a fix -- and the half that is
    missing is the half a human reads.
    """

    def _worker(self, queue, session_factory, registry, catalog, artifact_store, **kwargs):
        kwargs.setdefault("poll_timeout_s", 0)
        kwargs.setdefault("heartbeat_interval_s", 0)  # no thread unless a test wants one
        return Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            **kwargs,
        )

    def test_a_finished_run_releases_its_claim(
        self, queue, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """A terminal verdict is a finished job; holding the claim would only
        get it re-delivered and re-run for the same answer."""
        run_id = _seed_run(session_factory)
        queue.enqueue(_message(run_id))

        worker = self._worker(
            queue,
            session_factory,
            registry,
            catalog,
            artifact_store,
            client_factory=mock_transport_factory,
        )
        worker.run_forever(max_jobs=1)

        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, run_id)).status is RunStatus.SUCCEEDED
        assert queue.processing_depth() == 0, "acked"
        assert queue.depth() == 0

    def test_an_UNRESOLVABLE_job_is_acked_not_retried(
        self, queue, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """A verdict of 'failed' is still a verdict.

        `execute_job` turns an unknown task/model into a persisted `failed` run
        on purpose. Retrying that would produce the identical verdict three
        times and park a message about a question already answered.
        """
        run_id = _seed_run(session_factory, task_id="demo/no-such-task")
        queue.enqueue(_message(run_id, task_id="demo/no-such-task"))

        worker = self._worker(
            queue,
            session_factory,
            registry,
            catalog,
            artifact_store,
            client_factory=mock_transport_factory,
        )
        worker.run_forever(max_jobs=1)

        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, run_id)).status is RunStatus.FAILED
        assert worker.jobs_retried == 0
        assert queue.depth() == 0 and queue.processing_depth() == 0
        assert queue.dead_letters == []

    def test_an_unexpected_explosion_returns_the_job_and_un_runs_the_row(
        self, session_factory, registry, catalog, artifact_store, monkeypatch
    ) -> None:
        """A pod that falls over mid-job must leave the run WAITING, not running."""
        queue = InMemoryQueue(consumer_id="runner-a", max_attempts=3)
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        queue.enqueue(_message(run_id))

        def _explode(*_args, **_kwargs):
            raise RuntimeError("pod OOMKilled")

        monkeypatch.setattr("ida_runner.worker.execute_job", _explode)
        worker = self._worker(queue, session_factory, registry, catalog, artifact_store)
        worker.run_forever(max_jobs=1)

        assert worker.jobs_retried == 1
        assert queue.depth() == 1, "back on the queue for someone to try again"
        assert queue.processing_depth() == 0
        with session_scope(session_factory) as session:
            record = run_row_to_record(get_run(session, run_id))
        assert record.status is RunStatus.QUEUED, "waiting, not 'running' with nobody on it"
        assert record.started_at is None

    def test_retry_exhaustion_ends_in_a_FAILED_run_and_a_dead_letter(
        self, session_factory, registry, catalog, artifact_store, monkeypatch
    ) -> None:
        """The end of the line has to be honest and has to be visible.

        Two deliveries, then the queue gives up. The run must say `failed` with
        a reason -- never `running`, which is the status the old loop left
        behind and which a dashboard repeats to a human indefinitely.
        """
        queue = InMemoryQueue(consumer_id="runner-a", max_attempts=2)
        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        queue.enqueue(_message(run_id))

        def _explode(*_args, **_kwargs):
            raise ConnectionError("the endpoint is gone")

        monkeypatch.setattr("ida_runner.worker.execute_job", _explode)
        worker = self._worker(queue, session_factory, registry, catalog, artifact_store)
        _drain(worker, jobs=2)

        assert worker.jobs_retried == 1
        assert worker.jobs_dead_lettered == 1
        assert queue.depth() == 0, "it is not going round for ever"

        with session_scope(session_factory) as session:
            record = run_row_to_record(get_run(session, run_id))
        assert record.status is RunStatus.FAILED
        assert record.error and "gave up after 2 attempt(s)" in record.error
        assert "the endpoint is gone" in record.error, "the ORIGINAL cause survives"
        assert record.finished_at is not None

        parked = json.loads(queue.dead_letters[0])
        assert parked["run_id"] == run_id
        assert parked["attempts"] == 2

    def test_the_loop_survives_a_queue_that_cannot_retry(
        self, session_factory, registry, catalog, artifact_store, monkeypatch
    ) -> None:
        """Defence in depth, and an honest fallback.

        A RunQueue implementation predating claims (or a partial test double)
        has no `nack`. The worker must not crash on the missing method -- and
        must still close the run out rather than leave it 'running'.
        """

        class ClaimlessQueue:
            def __init__(self, message) -> None:
                self._messages = [message]

            def enqueue(self, message):
                self._messages.append(message)

            def dequeue(self, timeout_s=5):
                return self._messages.pop(0) if self._messages else None

            def depth(self):
                return len(self._messages)

        run_id = _seed_run(session_factory, status=RunStatus.RUNNING, started_at=utcnow())
        queue = ClaimlessQueue(_message(run_id))

        def _explode(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("ida_runner.worker.execute_job", _explode)
        worker = self._worker(queue, session_factory, registry, catalog, artifact_store)
        worker.run_forever(max_jobs=1)

        with session_scope(session_factory) as session:
            record = run_row_to_record(get_run(session, run_id))
        assert record.status is RunStatus.FAILED, "closed out, not abandoned as 'running'"

    def test_an_ack_that_fails_is_counted_not_fatal(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """A failed ack means the job is re-delivered later: wasteful, never
        lost, and never a reason to kill the runner."""

        class UnackableQueue(InMemoryQueue):
            def ack(self, message):
                raise ConnectionError("redis went away at the worst moment")

        queue = UnackableQueue(consumer_id="runner-a")
        run_id = _seed_run(session_factory)
        queue.enqueue(_message(run_id))

        worker = self._worker(
            queue,
            session_factory,
            registry,
            catalog,
            artifact_store,
            client_factory=mock_transport_factory,
        )
        worker.run_forever(max_jobs=1)

        assert worker.ack_failures == 1
        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, run_id)).status is RunStatus.SUCCEEDED


class TestCrashRecoveryEndToEnd:
    """kill -9 between the claim and the ack -- and the job still gets run."""

    def test_a_job_claimed_by_a_runner_that_dies_is_completed_by_another(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """The whole story, end to end, at the level a human cares about.

        Runner A takes the job and its pod is destroyed before it does anything.
        Under the old BLPOP loop that run was gone -- no message, no result, and
        a row saying `running` until somebody noticed. Here, runner B's reaper
        finds it and runner B finishes it.
        """
        queue_a = InMemoryQueue(consumer_id="runner-a", max_attempts=3)
        queue_b = queue_a.for_consumer("runner-b")
        run_id = _seed_run(session_factory)
        queue_a.enqueue(_message(run_id))

        claimed = queue_a.dequeue(timeout_s=0)  # runner-a claims it...
        assert claimed is not None and queue_a.depth() == 0
        queue_a.simulate_consumer_death()  # ...and is killed right here.

        Reaper(queue=queue_b, session_factory=session_factory, stale_run_ttl_s=3600).sweep()

        worker_b = Worker(
            queue=queue_b,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=0,
            heartbeat_interval_s=0,
            client_factory=mock_transport_factory,
        )
        assert worker_b.run_forever(max_jobs=1) == 1

        with session_scope(session_factory) as session:
            record = run_row_to_record(get_run(session, run_id))
        assert record.status is RunStatus.SUCCEEDED, "the work was not lost"
        assert record.sample_count == 4 and record.scored_count == 4
        assert queue_b.processing_depth() == 0, "and runner-b acked it"
        assert queue_b.dead_letters == []


class TestHousekeepingInTheLoop:
    """The reaper and the heartbeat run alongside consumption, and cannot stop it."""

    class _StubReaper:
        def __init__(self, explode: bool = False) -> None:
            self.sweeps = 0
            self._explode = explode

        def sweep(self):
            self.sweeps += 1
            if self._explode:
                raise ConnectionError("redis is unreachable")
            from ida_runner.reaper import ReaperReport

            return ReaperReport()

    def _worker(self, queue, session_factory, registry, catalog, artifact_store, **kwargs):
        return Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=0,
            heartbeat_interval_s=0,
            **kwargs,
        )

    def test_the_reaper_runs_from_the_consume_loop(
        self, queue, session_factory, registry, catalog, artifact_store
    ) -> None:
        reaper = self._StubReaper()
        worker = self._worker(
            queue,
            session_factory,
            registry,
            catalog,
            artifact_store,
            reaper=reaper,
            reaper_interval_s=0,
        )
        worker.stop()
        worker.run_forever()  # stopped before the first iteration
        assert reaper.sweeps == 0

        worker2 = self._worker(
            queue,
            session_factory,
            registry,
            catalog,
            artifact_store,
            reaper=reaper,
            reaper_interval_s=0,
        )
        thread = threading.Thread(target=worker2.run_forever, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while reaper.sweeps < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        worker2.stop()
        thread.join(timeout=5)
        assert reaper.sweeps >= 2, "it is periodic, not once-per-process"

    def test_a_reaper_that_is_not_due_yet_is_not_run(
        self, queue, session_factory, registry, catalog, artifact_store
    ) -> None:
        """Every replica does this pass; doing it on every single poll would
        turn an idle tier into a Redis scan loop."""
        reaper = self._StubReaper()
        worker = self._worker(
            queue,
            session_factory,
            registry,
            catalog,
            artifact_store,
            reaper=reaper,
            reaper_interval_s=3600,
        )
        thread = threading.Thread(target=worker.run_forever, daemon=True)
        thread.start()
        # Wait for the entry sweep rather than sleeping a guessed interval: a
        # timing assumption is how a test like this becomes flaky in CI.
        deadline = time.monotonic() + 5
        while reaper.sweeps < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)  # ...and now give a SECOND sweep every chance to happen
        worker.stop()
        thread.join(timeout=5)
        assert reaper.sweeps == 1, "once on entry, then not again for an hour"

    def test_a_FAILING_reaper_does_not_stop_the_runner_draining_the_queue(
        self, queue, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """Housekeeping is not the job.  Losing it must not lose the work."""
        run_id = _seed_run(session_factory)
        queue.enqueue(_message(run_id))
        reaper = self._StubReaper(explode=True)

        worker = self._worker(
            queue,
            session_factory,
            registry,
            catalog,
            artifact_store,
            reaper=reaper,
            reaper_interval_s=0,
            client_factory=mock_transport_factory,
        )
        worker.run_forever(max_jobs=1)

        assert worker.reaper_failures >= 1
        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, run_id)).status is RunStatus.SUCCEEDED

    def test_the_heartbeat_keeps_beating_while_a_long_job_runs(
        self, session_factory, registry, catalog, artifact_store, monkeypatch
    ) -> None:
        """Without this, a job that outlives the heartbeat TTL makes a HEALTHY
        runner look dead -- and its claim is recovered and run a second time.

        The loop's own dequeue heartbeats when idle; a runner is least idle
        exactly when it most needs to look alive.
        """
        beats = threading.Event()
        counter = {"n": 0}

        class CountingQueue(InMemoryQueue):
            def heartbeat(self):
                super().heartbeat()
                counter["n"] += 1
                if counter["n"] >= 3:
                    beats.set()

        queue = CountingQueue(consumer_id="runner-a")
        run_id = _seed_run(session_factory)
        queue.enqueue(_message(run_id))

        def _slow(*_args, **_kwargs):
            beats.wait(timeout=5)  # the "job" lasts as long as the beating needs
            raise RuntimeError("done pretending")

        monkeypatch.setattr("ida_runner.worker.execute_job", _slow)
        worker = Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=0,
            heartbeat_interval_s=0.02,
        )
        worker.run_forever(max_jobs=1)

        assert beats.is_set(), "the heartbeat thread ran DURING the job, not only between jobs"

    def test_the_heartbeat_thread_does_not_outlive_the_loop(
        self, queue, session_factory, registry, catalog, artifact_store
    ) -> None:
        worker = Worker(
            queue=queue,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            poll_timeout_s=0,
            heartbeat_interval_s=0.01,
        )
        worker.stop()
        worker.run_forever()
        assert worker._heartbeat_thread is None


class TestAtLeastOnceIsSafe:
    """Re-delivery is a FEATURE of the durability pass -- and its sharpest edge.

    A runner that commits a finished run and dies before acking will meet that
    message again. Running it twice would append a second full set of result
    rows for one run, and results are the citable evidence behind every
    recommendation (D-3): duplicating them corrupts the output quietly and
    permanently. The old at-most-once queue could not do this; this queue can,
    so the guard is part of the same change.
    """

    def test_a_re_delivered_FINISHED_run_is_not_run_again(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        run_id = _seed_run(session_factory)
        message = _message(run_id)

        first = _execute(
            message,
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )
        assert first.status is RunStatus.SUCCEEDED
        with session_scope(session_factory) as session:
            results_after_one = len(list_results_for_run(session, run_id))
        assert results_after_one == 4

        # ...the ack never landed, so the message comes back.
        again = _execute(
            message.model_copy(update={"attempt": 2}),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )

        assert again.status is RunStatus.SUCCEEDED, "reported, so the worker acks it"
        with session_scope(session_factory) as session:
            assert len(list_results_for_run(session, run_id)) == results_after_one, (
                "the citable evidence was NOT duplicated"
            )

    @pytest.mark.parametrize("status", [RunStatus.SUCCEEDED, RunStatus.PARTIAL, RunStatus.FAILED])
    def test_every_terminal_status_is_treated_as_work_already_done(
        self, status, session_factory, registry, catalog, artifact_store
    ) -> None:
        """Including `failed`: a run that failed for a real reason must keep that
        reason, not have it overwritten by a second opinion."""
        run_id = _seed_run(session_factory, status=status, error="the original reason")

        record = _execute(
            _message(run_id),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
        )

        assert record.status is status
        with session_scope(session_factory) as session:
            assert run_row_to_record(get_run(session, run_id)).error == "the original reason"

    def test_a_REQUEUED_run_is_not_mistaken_for_a_finished_one(
        self, session_factory, registry, catalog, artifact_store, mock_transport_factory
    ) -> None:
        """The guard must not swallow a legitimate retry.

        A recovered or nacked run goes back to `queued`, which is precisely why
        the reaper resets the row instead of leaving it alone.
        """
        run_id = _seed_run(session_factory, status=RunStatus.QUEUED)

        record = _execute(
            _message(run_id, attempt=2),
            session_factory=session_factory,
            registry=registry,
            catalog=catalog,
            artifact_store=artifact_store,
            client_factory=mock_transport_factory,
        )

        assert record.status is RunStatus.SUCCEEDED, "the retry actually ran"
        assert record.sample_count == 4
