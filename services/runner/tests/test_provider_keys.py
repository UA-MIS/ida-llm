"""The registry-to-deployment key contract (#49).

``models.yaml`` names an environment variable; it never holds a value.  The
value arrives from Vault, through an ExternalSecret, into ``ida-llm-secret``,
and is projected into the runner's container environment by the Deployment.
:func:`ida_core.registry.resolve_api_key` then reads it at *use* time.

Every hop of that chain is in a different file, owned by different people, and
none of them fails at start-up when a link is missing.  The failure shows up as
a run that dies with "requires env var 'X', which is unset" -- in staging, after
a deploy, on the first job that selects the model.

So these tests read the actual manifests and assert the chain joins up.  They
are cheap, they run in the ordinary python gate, and they fail in the PR that
breaks the link rather than in the environment that needed it.

Nothing here makes a network call, reads a real secret, or needs a key.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ida_core.registry import MissingApiKeyError, load_registry, resolve_api_key

REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS_YAML = REPO_ROOT / "models.yaml"
DEPLOYMENTS = REPO_ROOT / ".devops/chart/base/deployments.yaml"
CRONJOBS = REPO_ROOT / ".devops/chart/base/cronjobs.yaml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

RUNNER_NAME = "ida-llm-runner"


def _documents(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]


def _containers(document: dict) -> list[dict]:
    """Every container spec inside a Deployment or a CronJob."""
    spec = document.get("spec", {})
    if document.get("kind") == "CronJob":
        spec = spec.get("jobTemplate", {}).get("spec", {})
    return spec.get("template", {}).get("spec", {}).get("containers", []) or []


def _projected_env_names(containers: list[dict]) -> set[str]:
    return {var["name"] for container in containers for var in container.get("env", []) or []}


def _runner_containers() -> list[dict]:
    for document in _documents(DEPLOYMENTS):
        if document.get("kind") == "Deployment" and document["metadata"]["name"] == RUNNER_NAME:
            return _containers(document)
    raise AssertionError(f"no Deployment named {RUNNER_NAME} in {DEPLOYMENTS}")


ENABLED_KEY_VARS = sorted(
    {
        entry.api_key_env
        for entry in load_registry(MODELS_YAML).models
        if entry.enabled and entry.api_key_env
    }
)
"""The env vars the live registry will actually try to read.

Computed from the file rather than hardcoded: enabling a model is supposed to be
a ``models.yaml`` edit, so the test that says "and its key must be deployed" has
to follow that edit automatically or it is not a guard at all.
"""


def test_there_is_something_to_check() -> None:
    """Guards the comprehension above. If it silently produced an empty list,
    every parametrised test below would pass vacuously -- which is exactly the
    state this suite exists to detect."""
    assert ENABLED_KEY_VARS, "no enabled entry names an api_key_env; is models.yaml intact?"


@pytest.mark.parametrize("variable", ENABLED_KEY_VARS)
class TestEveryEnabledModelsKeyReachesTheRunner:
    def test_the_runner_deployment_projects_it(self, variable: str) -> None:
        """The runner is the only process that calls a model. A key it cannot see
        makes every job selecting that model fail, one job at a time."""
        assert variable in _projected_env_names(_runner_containers()), (
            f"{variable} is named by an ENABLED entry in models.yaml but is not projected "
            f"into the runner container in {DEPLOYMENTS.relative_to(REPO_ROOT)}"
        )

    def test_it_comes_from_the_app_secret_not_a_literal(self, variable: str) -> None:
        """A literal value here would be a committed secret. `secretKeyRef` is
        the only acceptable source."""
        for container in _runner_containers():
            for var in container.get("env", []) or []:
                if var["name"] == variable:
                    assert "value" not in var, f"{variable} carries a literal value in the chart"
                    ref = var.get("valueFrom", {}).get("secretKeyRef", {})
                    assert ref.get("name") == "ida-llm-secret"
                    assert ref.get("key") == variable

    def test_the_env_example_documents_it(self, variable: str) -> None:
        """A developer who wants to run against this model locally needs to know
        the variable exists. An undocumented one is found by reading source."""
        assert f"{variable}=" in ENV_EXAMPLE.read_text(), (
            f"{variable} is not listed in .env.example"
        )


class TestTheNightlySweepsCanUseWhatTheRegistryEnables:
    """The sweeps are the way a model gets selected *without a human present*.

    ``models.yaml`` already documents the live instance of this trap: the
    CronJobs receive ANTHROPIC_API_KEY and OPENAI_API_KEY but **not**
    SPARKS_API_KEY, so a nightly sweep selecting ``sparks-local`` dies on an
    unset key. That is fine while the entry is disabled -- and becomes a nightly
    failing job the moment it is not.
    """

    @pytest.mark.parametrize("variable", ENABLED_KEY_VARS)
    def test_every_cronjob_projects_it(self, variable: str) -> None:
        missing = [
            document["metadata"]["name"]
            for document in _documents(CRONJOBS)
            if document.get("kind") == "CronJob"
            and variable not in _projected_env_names(_containers(document))
        ]
        assert not missing, (
            f"{variable} is enabled in models.yaml but missing from CronJob(s) {missing}; "
            "a scheduled sweep selecting that model would fail on an unset key"
        )


class TestLunaSpecifically:
    """#48/#49: the first hosted model this project actually turns on."""

    def test_luna_names_the_openai_variable(self) -> None:
        entry = load_registry(MODELS_YAML).get("luna")
        assert entry.enabled
        assert entry.api_key_env == "OPENAI_API_KEY"

    def test_the_key_is_read_at_use_time_from_the_environment(self) -> None:
        """Not at load time. A developer holding no OpenAI key must still be able
        to parse models.yaml and run the mock -- which is why the whole file
        loads fine above with nothing set."""
        entry = load_registry(MODELS_YAML).get("luna")
        assert resolve_api_key(entry, {"OPENAI_API_KEY": "sk-test"}) == "sk-test"

    def test_a_missing_key_fails_loudly_and_names_the_variable(self) -> None:
        """This is the error a dev box SHOULD get: OPENAI_API_KEY is deliberately
        unset locally and in CI, so selecting luna there cannot spend money. It
        must say why rather than 401-ing somewhere far from the cause."""
        entry = load_registry(MODELS_YAML).get("luna")
        with pytest.raises(MissingApiKeyError, match="OPENAI_API_KEY"):
            resolve_api_key(entry, {})

    def test_an_empty_string_counts_as_missing(self) -> None:
        """`.env.example` ships `OPENAI_API_KEY=` empty. If empty resolved as a
        key we would send an empty Authorization header and get a confusing 401
        instead of the honest local error above."""
        entry = load_registry(MODELS_YAML).get("luna")
        with pytest.raises(MissingApiKeyError):
            resolve_api_key(entry, {"OPENAI_API_KEY": ""})

    def test_no_key_material_is_committed_anywhere_near_the_entry(self) -> None:
        """models.yaml names variables and never holds values. A pasted key is
        the single most expensive mistake available in this file."""
        text = MODELS_YAML.read_text()
        assert "sk-" not in text, "models.yaml appears to contain an API key"
