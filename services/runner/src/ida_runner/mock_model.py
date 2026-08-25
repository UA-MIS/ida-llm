"""The in-repo MOCK MODEL ENDPOINT.

THIS IS A SAFETY DEVICE, not a test fixture. It is the default target in CI, in
PR previews and in dev, which is what makes the guarantee "no pull request can
burn provider credits or reach campus hardware" true by construction rather than
by everyone remembering.

It is deliberately dumb and deterministic: same prompt in, same completion out,
no network, no state. Determinism matters -- a mock that varied its output would
make CI flaky and teach people to ignore red.

Speaks the same tiny shape MockClient calls (`POST /v1/complete`). It is NOT an
OpenAI-compatible server; if you need that shape later, add it alongside rather
than changing this one, because CI pins to this contract.
"""

from __future__ import annotations

import hashlib

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from ida_core.settings import get_settings

app = FastAPI(title="IDA-LLM mock model", version="0.1.0")


class CompleteRequest(BaseModel):
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.0


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/complete")
def complete(request: CompleteRequest) -> dict[str, object]:
    """Return a deterministic pseudo-completion.

    The digest makes the reply prompt-dependent (so a test can tell two prompts
    apart) while staying byte-identical across runs (so CI never flakes).
    """
    digest = hashlib.sha256(request.prompt.encode()).hexdigest()[:12]
    return {
        "completion": f"[mock:{digest}] {request.prompt.strip()[:200]}",
        "model": "mock-echo-v1",
        "usage": {"prompt_tokens": len(request.prompt.split()), "completion_tokens": 8},
    }


def main() -> None:
    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
