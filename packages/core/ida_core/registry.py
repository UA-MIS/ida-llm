"""Load and validate ``models.yaml`` into a :class:`~ida_core.contracts.ModelRegistry`.

Also resolves the two pieces of an entry that are DELIBERATELY not in the YAML:

* the API key -- the file holds only the *name* of an env var (``api_key_env``)
  and the value is read from the process environment at call time.  That is what
  makes the same registry file safe to commit and safe to project from Vault.
* the base URL -- ``base_url_env`` names a variable that overrides the literal
  ``base_url``.  One image is promoted byte-identically across dev, staging and
  prod, so an endpoint that differs per environment cannot be baked in.

Both resolve at **use** time, never at load time.  A developer running only the
mock model must not be forced to hold an Anthropic key, and a `models.yaml` that
refuses to parse because one disabled entry's variable is unset is a file nobody
can edit.
"""

from __future__ import annotations

import os
from pathlib import Path

from ida_core.contracts import ModelEntry, ModelRegistry
from ida_core.validation import load_yaml, validate_models_document


class MissingBaseUrlError(RuntimeError):
    """An entry declares ``base_url_env`` with no ``base_url`` fallback, and the
    named variable is empty.

    Raised at *use* time, with the variable's NAME in the message -- which is the
    whole point of the indirection. ``sparks-local`` is the live example: it is
    unreachable from this cluster today, so selecting it should say
    "SPARKS_BASE_URL is unset", not hang on a connect timeout.
    """


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


def resolve_base_url(entry: ModelEntry, env: dict[str, str] | None = None) -> str:
    """Return the endpoint for ``entry``.

    Resolution order, and each step is deliberate:

    1. ``base_url_env``, when the named variable is set **and non-empty**.
       Emptiness is what makes the safety switch work: staging and prod set
       ``MOCK_MODEL_BASE_URL`` to ``""`` rather than removing the key, so an
       overlay diff shows the switch being thrown rather than a line vanishing.
    2. ``base_url``, the committed literal -- correct for docker-compose.
    3. :class:`MissingBaseUrlError`, naming the variable.

    Mirrors :func:`resolve_api_key` exactly, including raising at use time.
    """
    environ = os.environ if env is None else env
    if entry.base_url_env:
        value = (environ.get(entry.base_url_env) or "").strip()
        if value:
            return value
    if entry.base_url:
        return entry.base_url
    raise MissingBaseUrlError(
        f"model {entry.key!r} has no base_url and env var {entry.base_url_env!r} is unset or empty"
    )
