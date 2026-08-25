"""Queue contract: JSON on the wire, FIFO, versioned, and refuses garbage."""

from __future__ import annotations

import json
import threading

import pytest
from pydantic import ValidationError

from ida_core.contracts import RunJobMessage, SamplingParams
from ida_core.db import utcnow
from ida_core.queue import RUN_QUEUE_KEY, InMemoryQueue, RunQueue


def _message(run_id: str = "run_1") -> RunJobMessage:
    return RunJobMessage(run_id=run_id, task_id="demo/t", model_key="mock", enqueued_at=utcnow())


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


class TestInMemoryQueue:
    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(InMemoryQueue(), RunQueue)

    def test_fifo_order(self) -> None:
        queue = InMemoryQueue()
        for i in range(3):
            queue.enqueue(_message(f"run_{i}"))
        assert [queue.dequeue(0).run_id for _ in range(3)] == ["run_0", "run_1", "run_2"]

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


def test_queue_key_is_pinned() -> None:
    """Changing this is a breaking deployment change; make it deliberate."""
    assert RUN_QUEUE_KEY == "ida:queue:runs"
