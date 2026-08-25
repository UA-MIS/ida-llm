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
``MOCK_JUDGE_MODE``   how to answer an LLM-as-judge prompt: ``json`` (default,
                      well-formed), ``malformed`` or ``out_of_range``.  Lets a
                      failure drill point the harness at a *service* that
                      misbehaves rather than at a stub that pretends to.
``IDA_GIT_SHA``       the commit this image was built from, baked in by
                      ``Dockerfile.python``.  Reported by ``/healthz``.
``IDA_VERSION``       the release string the build was told to claim, baked in
                      by ``Dockerfile.python``.  Reported by ``/healthz``.
"""

from __future__ import annotations

import os
import re
import time
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ida_mock_model import __version__
from ida_mock_model.responder import Responder, estimate_tokens

DEFAULT_MODEL_ID = "mock-echo-1"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
"""The same shape guard as :func:`ida_core.gitmeta.is_sha`, deliberately copied.

⚠ THE COPY IS THE POINT, NOT AN OVERSIGHT.  This service depends on fastapi,
uvicorn and pydantic and NOTHING from the platform (see the package docstring):
that is what lets it stand in for a real model endpoint without dragging
sqlalchemy, boto3 and redis behind it.  Importing ``ida_core`` for one regex
would trade a four-line duplicate for a dependency on the entire contracts
package.  If the rule ever changes, ``ida_core.gitmeta`` is canonical and this
must follow it.
"""


def _build_git_sha() -> str | None:
    """The commit this build was made from, or ``None`` when it cannot be known.

    ENV ONLY -- it never shells out to ``git``, unlike ``ida_core.gitmeta``. A
    stub model server has no business forking a subprocess, and outside an image
    there is no build to identify anyway: ``None`` is the true answer there.

    ⚠ A WRONG SHA LOOKS LIKE A REAL ONE. A pipeline that forgets to substitute a
    variable exports the literal ``$GITHUB_SHA``; a repository with no commits
    makes git print ``HEAD``. Both are rejected here, so ``/healthz`` reports
    ``null`` rather than something SHA-shaped that resolves to nothing.
    """
    candidate = os.environ.get("IDA_GIT_SHA", "").strip()
    return candidate if _SHA_RE.match(candidate) else None


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
        self.responder.judge_mode = os.environ.get("MOCK_JUDGE_MODE", "json")


def create_app() -> FastAPI:
    """Build the mock-model app.  One factory so tests and uvicorn agree."""
    # ── WHAT THIS BUILD HONESTLY IS, RESOLVED ONCE ─────────────────────────
    #
    # `version` used to be `ida_mock_model.__version__` -- a hardcoded "0.1.0"
    # that no release step ever wrote to, so every image ever built introduced
    # itself as 0.1.0. A health endpoint that disagrees with the release it is
    # running is not cosmetic: it is what convinces someone a deploy did not land.
    #
    # Same shape as the api's /healthz, deliberately: `version` is whatever the
    # release process was told to say (IDA_VERSION, baked in by Dockerfile.python,
    # falling back to the packaging version), and `git_sha` is the authority --
    # baked in at build time and correct by construction, needing no pipeline to
    # remember anything.
    #
    # Resolved HERE, at app construction: /healthz is what the chart probes for
    # both liveness and readiness on this Deployment, and per-probe environment
    # reads for a value that cannot change are work for nothing.
    build_version = os.environ.get("IDA_VERSION", "").strip() or __version__
    build_git_sha = _build_git_sha()

    app = FastAPI(
        title="ida-mock-model",
        version=build_version,
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
        return {
            "status": "ok",
            "service": "mock-model",
            "version": build_version,
            "git_sha": build_git_sha,
        }

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
