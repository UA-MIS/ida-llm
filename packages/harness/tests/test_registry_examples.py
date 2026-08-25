"""The commented example entries in ``models.yaml`` must actually work.

A commented-out example is documentation that nobody runs, which is how it rots:
the schema gains a field, an enum value is renamed, a client changes what it
needs -- and the example still *looks* right until someone uncomments it at
2am with a credit card attached.

So this test uncomments them and puts them through the same two-layer validation
``load_registry`` uses on the live file, then asserts each one resolves to a real
client.  Nothing here makes a network call or needs a key: no client is
constructed, only selected.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ida_core.contracts import ModelEntry, ServingStack
from ida_core.validation import validate_models_document
from ida_harness.factory import client_class_for

REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS_YAML = REPO_ROOT / "models.yaml"

# A commented entry starts at `  # - key: ...` and runs until the next line that
# is neither a continuation comment nor blank.
_ENTRY_START = re.compile(r"^ {2}# - key: ")
_COMMENT_BODY = re.compile(r"^ {2}#(?: |$)")


def _uncommented_example_entries() -> list[tuple[str, str]]:
    """Every commented ``- key:`` block, as (key, yaml-text) pairs."""
    blocks: list[tuple[str, str]] = []
    lines = MODELS_YAML.read_text().splitlines()
    i = 0
    while i < len(lines):
        if not _ENTRY_START.match(lines[i]):
            i += 1
            continue
        body: list[str] = []
        while i < len(lines) and _COMMENT_BODY.match(lines[i]):
            stripped = re.sub(r"^ {2}# ?", "", lines[i])
            if not stripped.strip():
                break  # a bare `  #` separator line ends the entry
            body.append(stripped)
            i += 1
        text = "\n".join(body)
        key = re.search(r"^- key: (\S+)", text).group(1)
        blocks.append((key, text))
    return blocks


EXAMPLES = _uncommented_example_entries()


def _parse(text: str) -> ModelEntry:
    """One commented block -> a validated entry, through both layers.

    Same order ``load_registry`` uses: JSON Schema first, so a structural error
    reports a path, then pydantic.
    """
    import yaml

    document = {"version": 1, "models": yaml.safe_load(text)}
    validate_models_document(document, MODELS_YAML)
    return ModelEntry.model_validate(document["models"][0])


def test_the_file_actually_contains_examples() -> None:
    """Guards the parser above: a regex that silently matches nothing would make
    every parametrised test below vacuously pass."""
    assert len(EXAMPLES) >= 4
    keys = [key for key, _ in EXAMPLES]
    assert "claude-opus-5" in keys, "the Anthropic example is the point of this story"
    assert "gpt-5" in keys, "so is the OpenAI one"


@pytest.mark.parametrize("key,text", EXAMPLES, ids=[k for k, _ in EXAMPLES])
class TestEachExampleWouldWork:
    def _entry(self, text: str) -> ModelEntry:
        return _parse(text)

    def test_validates_against_schema_and_contracts(self, key: str, text: str) -> None:
        assert self._entry(text).key == key

    def test_resolves_to_a_real_client(self, key: str, text: str) -> None:
        assert client_class_for(self._entry(text)) is not None

    def test_a_hosted_entry_names_a_key_variable(self, key: str, text: str) -> None:
        """A hosted API with `api_key_env: null` would send unauthenticated
        requests. The client refuses to do that silently, but the example
        should not tempt anyone into it in the first place."""
        entry = self._entry(text)
        if entry.base_url.startswith("https://"):
            assert entry.api_key_env, f"{key} is a hosted endpoint with no api_key_env"

    def test_a_paid_entry_declares_nonzero_pricing(self, key: str, text: str) -> None:
        """Cost accounting reads these two numbers and nothing else. A hosted
        model left at the 0.0 default reports every run as free, which is worse
        than reporting nothing."""
        entry = self._entry(text)
        if entry.base_url.startswith("https://"):
            assert entry.cost.input_usd_per_mtok > 0, f"{key} would bill as free"
            assert entry.cost.output_usd_per_mtok > 0, f"{key} would bill as free"


class TestAnthropicExamplesRespectTheMessagesApi:
    """The two constraints an author is most likely to get wrong, and which cost
    a real 400 (or a fabricated reproducibility record) to discover."""

    @pytest.mark.parametrize(
        "key,text",
        [(k, t) for k, t in EXAMPLES if "serving_stack: anthropic_compat" in t],
        ids=[k for k, t in EXAMPLES if "serving_stack: anthropic_compat" in t],
    )
    def test_no_seed_is_declared(self, key: str, text: str) -> None:
        assert _parse(text).serving.sampling.seed is None, (
            f"{key}: the Messages API has no seed parameter and the client refuses to run "
            "with one set"
        )

    def test_the_flagship_example_uses_api_default_sampling(self) -> None:
        """Opus 5 rejects a non-default temperature/top_p with a 400, so an
        example carrying the benchmark default of 0.0 would fail on first use."""
        text = next(t for k, t in EXAMPLES if k == "claude-opus-5")
        sampling = _parse(text).serving.sampling
        assert sampling.temperature == 1.0
        assert sampling.top_p == 1.0


class TestLiveFileIsUnchangedInSpirit:
    def test_only_the_mock_is_enabled(self) -> None:
        """No example is accidentally live. Enabling a hosted model is a
        deliberate act with a credit-card consequence."""
        from ida_core.registry import load_registry

        assert load_registry(MODELS_YAML).enabled_keys() == ["mock"]

    def test_the_mock_still_takes_the_openai_compatible_client(self) -> None:
        from ida_core.registry import load_registry

        entry = load_registry(MODELS_YAML).get("mock")
        assert entry.serving.serving_stack is ServingStack.MOCK
        assert client_class_for(entry).__name__ == "OpenAICompatibleClient"
