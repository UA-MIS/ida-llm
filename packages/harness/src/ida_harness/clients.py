"""Model client protocol + the mock client.

WHY THE PROTOCOL IS HERE AND THE PROVIDERS ARE NOT: the point of pinning the
interface is that the mock, the cloud providers and the campus vLLM stay
interchangeable, so CI and PR previews can run the REAL harness against a fake
model. The provider bodies are the project's own work.
"""

from __future__ import annotations

from typing import Protocol

import httpx


class ModelClient(Protocol):
    """What every model backend must satisfy."""

    def complete(self, prompt: str, *, max_tokens: int, temperature: float) -> str: ...


class MockClient:
    """Talks to the in-repo stub (`ida-mock-model`).

    Deterministic and free. This is the DEFAULT in CI, in PR previews and in dev --
    not a test-only special case -- which is what guarantees no pull request can
    burn provider credits or reach campus hardware.
    """

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def complete(self, prompt: str, *, max_tokens: int, temperature: float) -> str:
        response = self._client.post(
            "/v1/complete",
            json={"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature},
        )
        response.raise_for_status()
        return response.json()["completion"]

    def close(self) -> None:
        self._client.close()


def build_client(model_spec: dict, env: dict[str, str]) -> ModelClient:
    """Construct the client for a models.yaml entry.

    STUB for real providers -- deliberately raising, with the reason, rather than
    silently degrading to the mock. A benchmark that quietly scored a mock while
    reporting a frontier model's name would invalidate every number in the
    database, which is a far worse failure than a crash.
    """
    provider = model_spec["provider"]

    if provider == "mock":
        base_url = env.get(model_spec.get("base_url_env", "MOCK_MODEL_BASE_URL"), "")
        if not base_url:
            raise RuntimeError(
                "MOCK_MODEL_BASE_URL is unset -- start `ida-mock-model` or point at the "
                "in-cluster mock Service (http://ida-llm-mock-model)"
            )
        return MockClient(base_url)

    if provider == "openai-compatible":
        base_url = env.get(model_spec.get("base_url_env", ""), "")
        if not base_url:
            raise RuntimeError(
                f"{model_spec['id']}: {model_spec.get('base_url_env')} is unset. For the campus "
                "vLLM ('sparks-local') this is EXPECTED today -- the cluster egress policy does "
                "not open a route to it yet (deferred; see .devops/README.md)."
            )

    raise NotImplementedError(
        f"provider {provider!r} is not implemented yet -- implement it in "
        "packages/harness/src/ida_harness/clients.py against the ModelClient protocol"
    )
