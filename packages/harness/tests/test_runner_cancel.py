"""``should_cancel`` (AD-12): checked before each sample; a cancel stops the
calls, keeps the completed samples (and their spend), and lands ``cancelled``."""

from __future__ import annotations

import httpx

from ida_core.contracts import RunStatus
from ida_harness.client import OpenAICompatibleClient
from ida_harness.runner import run_task

RUN_ID = "run_cancel000000000000000000"


def _client(entry, calls: list[str]) -> OpenAICompatibleClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append("call")
        return httpx.Response(
            200,
            json={
                "id": "x",
                "model": "m",
                "choices": [{"message": {"role": "assistant", "content": "4"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    return OpenAICompatibleClient(
        entry, transport=httpx.MockTransport(handler), sleep=lambda _s: None, jitter=lambda _l, h: h
    )


def test_a_cancel_stops_before_the_next_sample(verifiable_task, model_entry) -> None:
    assert len(verifiable_task.samples) >= 2
    calls: list[str] = []
    answers = iter([False, True])  # first sample runs, then cancelled
    with _client(model_entry, calls) as client:
        log = run_task(
            task=verifiable_task,
            entry=model_entry,
            run_id=RUN_ID,
            client=client,
            should_cancel=lambda: next(answers, True),
        )
    assert log.status is RunStatus.CANCELLED
    assert len(calls) == 1 and len(log.results) == 1
    assert log.results[0].usage.prompt_tokens == 10  # the spend is kept
    assert log.error.startswith("cancelled after 1 of")


def test_cancelled_before_the_first_sample_makes_no_call(verifiable_task, model_entry) -> None:
    calls: list[str] = []
    with _client(model_entry, calls) as client:
        log = run_task(
            task=verifiable_task,
            entry=model_entry,
            run_id=RUN_ID,
            client=client,
            should_cancel=lambda: True,
        )
    assert calls == [] and log.results == [] and log.status is RunStatus.CANCELLED


def test_never_cancelling_is_unchanged(verifiable_task, model_entry) -> None:
    calls: list[str] = []
    with _client(model_entry, calls) as client:
        log = run_task(
            task=verifiable_task,
            entry=model_entry,
            run_id=RUN_ID,
            client=client,
            should_cancel=lambda: False,
        )
    assert log.status is not RunStatus.CANCELLED
    assert len(calls) == len(verifiable_task.samples)
