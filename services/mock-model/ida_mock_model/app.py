"""FastAPI app exposing an OpenAI-compatible ``/v1/chat/completions``.

Only the subset the harness actually uses is implemented, and the response
shape matches OpenAI's closely enough that
:class:`ida_harness.client.OpenAICompatibleClient` cannot tell the difference --
which is the point: if the client works against this, it works against vLLM.

Configuration (env)
-------------------
``MOCK_LATENCY_MS``   artificial per-request latency in ms (default 0).
``MOCK_FAIL_RATE``    fraction of requests answered with a 503, for exercising
                      the retry path.  Deterministic per request index, not
                      random, so a test can rely on it.
``MOCK_MODEL_ID``     the id echoed back in ``model`` (default ``mock-echo-1``).
"""

from __future__ import annotations

import os
import time
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ida_mock_model import __version__
from ida_mock_model.responder import Responder, estimate_tokens

DEFAULT_MODEL_ID = "mock-echo-1"


class _Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    """The subset of the OpenAI request body this mock honours."""

    model: str
    messages: list[_Message] = Field(min_length=1)
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: Annotated[int, Field(ge=1)] = 1024
    stream: bool = False
    seed: int | None = None
    stop: list[str] = Field(default_factory=list)


class MockState:
    """Mutable server state.  Held on ``app.state`` so tests can reach it."""

    def __init__(self) -> None:
        self.responder = Responder()
        self.request_count = 0
        self.latency_ms = float(os.environ.get("MOCK_LATENCY_MS", "0"))
        self.fail_every = int(os.environ.get("MOCK_FAIL_EVERY", "0"))
        """Fail every Nth request with 503.  0 disables.  Deterministic by design."""

        self.model_id = os.environ.get("MOCK_MODEL_ID", DEFAULT_MODEL_ID)


def create_app() -> FastAPI:
    """Build the mock-model app.  One factory so tests and uvicorn agree."""
    app = FastAPI(
        title="ida-mock-model",
        version=__version__,
        description="Deterministic OpenAI-compatible endpoint for Capstone-IDA.",
    )
    app.state.mock = MockState()

    @app.get("/healthz")
    @app.get("/health")
    def health() -> dict:
        """Liveness AND readiness -- trivially both, since there are no dependencies.

        TWO PATHS, ONE BODY, and both are load-bearing:

        * ``/healthz`` is what the chart's `ida-llm-mock-model` Deployment probes
          for BOTH liveness and readiness.
        * ``/health`` is what the docker-compose healthcheck and the tracer use.

        The api splits these two paths because it HAS dependencies and liveness
        must not touch them. This service has none, so there is nothing to split
        -- and inventing a difference would only invite someone to "fix" it.
        """
        return {"status": "ok", "service": "mock-model", "version": __version__}

    @app.get("/v1/models")
    def list_models() -> dict:
        """OpenAI-compatible model listing.  Some clients probe this first."""
        state: MockState = app.state.mock
        return {
            "object": "list",
            "data": [{"id": state.model_id, "object": "model", "owned_by": "capstone-ida"}],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(request: ChatCompletionRequest) -> dict:
        """Answer one chat completion deterministically."""
        state: MockState = app.state.mock
        state.request_count += 1

        if state.fail_every and state.request_count % state.fail_every == 0:
            # Deterministic transient failure so the retry path is testable.
            raise HTTPException(status_code=503, detail="mock: injected transient failure")

        if request.stream:
            raise HTTPException(status_code=400, detail="mock-model does not implement streaming")

        if state.latency_ms > 0:
            time.sleep(state.latency_ms / 1000.0)

        user_messages = [m for m in request.messages if m.role == "user"]
        if not user_messages:
            raise HTTPException(status_code=400, detail="no user message in request")

        answer = state.responder.answer(user_messages[-1].content)
        prompt_tokens = sum(estimate_tokens(m.content) for m in request.messages)
        completion_tokens = estimate_tokens(answer)

        return {
            "id": f"chatcmpl-mock-{state.request_count:08d}",
            "object": "chat.completion",
            "created": 0,
            "model": state.model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    return app


app = create_app()
