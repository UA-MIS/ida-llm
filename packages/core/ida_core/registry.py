"""Load and validate ``models.yaml`` into a :class:`~ida_core.contracts.ModelRegistry`.

Also resolves the API key: the YAML holds only the *name* of an env var
(``api_key_env``); the value is read from the process environment at call time.
That is what makes the same registry file safe to commit and safe to project
from Vault in-cluster.
"""

from __future__ import annotations

import os
from pathlib import Path

from ida_core.contracts import ModelEntry, ModelRegistry
from ida_core.validation import load_yaml, validate_models_document


class MissingApiKeyError(RuntimeError):
    """An enabled model names an env var that is not set.

    Raised at *use* time, not load time: a developer running only the mock model
    must not be forced to hold an Anthropic key.
    """


def load_registry(path: Path | str) -> ModelRegistry:
    """Parse, schema-validate, then pydantic-validate ``models.yaml``.

    Both layers run, in that order, so a structural error is reported with a
    JSON-pointer-ish path before pydantic's message.
    """
    path = Path(path)
    document = load_yaml(path)
    validate_models_document(document, path)
    return ModelRegistry.model_validate(document)


def resolve_api_key(entry: ModelEntry, env: dict[str, str] | None = None) -> str | None:
    """Return the API key for ``entry``.

    ``None`` when the entry declares no ``api_key_env`` (an unauthenticated
    endpoint -- the mock model, a campus vLLM behind network policy).  Raises
    :class:`MissingApiKeyError` when a key *is* declared but unset, because
    silently sending an empty ``Authorization`` header produces a confusing
    401 far from the cause.
    """
    if entry.api_key_env is None:
        return None
    environ = os.environ if env is None else env
    value = environ.get(entry.api_key_env)
    if not value:
        raise MissingApiKeyError(
            f"model {entry.key!r} requires env var {entry.api_key_env!r}, which is unset"
        )
    return value
