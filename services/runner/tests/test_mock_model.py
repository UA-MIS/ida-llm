"""Tests for the mock endpoint.

Determinism is the property under test. If the mock ever became non-deterministic
CI would flake, people would learn to re-run red builds, and the gate would stop
meaning anything.
"""

from fastapi.testclient import TestClient

from ida_runner.mock_model import app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_completion_is_deterministic():
    first = client.post("/v1/complete", json={"prompt": "hello"}).json()
    second = client.post("/v1/complete", json={"prompt": "hello"}).json()
    assert first["completion"] == second["completion"]


def test_different_prompts_differ():
    a = client.post("/v1/complete", json={"prompt": "hello"}).json()["completion"]
    b = client.post("/v1/complete", json={"prompt": "goodbye"}).json()["completion"]
    assert a != b


def test_reports_the_mock_model_name():
    # A run must never be able to claim a frontier model produced a mock answer.
    assert client.post("/v1/complete", json={"prompt": "x"}).json()["model"] == "mock-echo-v1"
