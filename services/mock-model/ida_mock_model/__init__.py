"""``ida_mock_model`` -- a deterministic OpenAI-compatible endpoint.

It exists so that the entire pipeline (api -> queue -> runner -> harness ->
Postgres -> MinIO -> UI) can be exercised end-to-end with **no** API key, **no**
GPU and **no** network egress -- in CI, on a laptop, and in the dev cluster.

It is deterministic on purpose: given the same prompt it returns the same
answer, so a tracer-bullet assertion on a score is a real assertion and not a
flake.  See :mod:`ida_mock_model.responder` for the answering rules.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
