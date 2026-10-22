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
from ida_harness.preflight import check_entry, check_registry, errors

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


ANTHROPIC_EXAMPLES = [(k, t) for k, t in EXAMPLES if "serving_stack: anthropic_compat" in t]


def test_the_file_actually_contains_examples() -> None:
    """Guards the parser above: a regex that silently matches nothing would make
    every parametrised test below vacuously pass."""
    assert len(EXAMPLES) >= 4
    keys = [key for key, _ in EXAMPLES]
    assert "claude-sonnet-4-6" in keys, "an Anthropic example is the point of this story"
    assert "gpt-5" in keys, "so is the OpenAI one"


def test_the_anthropic_filter_actually_matches_something() -> None:
    """Guards the FILTERED source below, which `EXAMPLES`' own guard does not
    cover: delete every Anthropic example and those tests would silently pass
    on an empty parametrisation instead of failing."""
    assert ANTHROPIC_EXAMPLES, "no anthropic_compat examples -- the tests below are vacuous"


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

    @pytest.mark.parametrize("key,text", ANTHROPIC_EXAMPLES, ids=[k for k, _ in ANTHROPIC_EXAMPLES])
    def test_no_seed_is_declared(self, key: str, text: str) -> None:
        assert _parse(text).serving.sampling.seed is None, (
            f"{key}: the Messages API has no seed parameter and the client refuses to run "
            "with one set"
        )

    def test_the_flagship_example_uses_api_default_sampling(self) -> None:
        """Opus 5 rejects a non-default temperature/top_p with a 400, so an
        example carrying the benchmark default of 0.0 would fail on first use."""
        from ida_core.registry import load_registry

        sampling = load_registry(MODELS_YAML).get("claude-opus-5").serving.sampling
        assert sampling.temperature == 1.0
        assert sampling.top_p == 1.0


CLAUDE_KEYS = {
    "claude-fable-5-1",
    "claude-fable-5",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-sonnet-5-5",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-5-5",
    "claude-haiku-4-5",
}
ALLOWED_ENABLED_KEYS = {"mock", "luna", "qwen-local"} | CLAUDE_KEYS
"""The only entries that may be `enabled: true` in the live ``models.yaml``.

``mock`` is free and deterministic.  ``luna`` is deliberately enabled (issue
#48) against an OpenAI key that is **scoped to that model and carries a $25 hard
cap, for TESTING ONLY** -- it exists so the real provider path can be exercised
end to end, and it is not the finished product's budget.  ``qwen-local`` is the
team's self-hosted endpoint: free per token, so it adds no credit-card exposure.
The ``claude-*`` entries are real Anthropic models on a key with NO hard spend cap,
so they are tagged ``testing-only`` (see TestClaudeEntriesAreHeldOutOfSweeps).

Everything else stays off.  Widening this set is a decision with a credit-card
consequence, so it is written here, once, rather than implied by the absence of
a check.
"""


class TestLiveFileIsUnchangedInSpirit:
    def test_only_the_mock_and_luna_are_enabled(self) -> None:
        """No example is accidentally live. Enabling a hosted model is a
        deliberate act with a credit-card consequence.

        Widened from mock-only to {mock, luna} for #48. The guard is not
        weakened by that: it still fails the moment a SECOND hosted model is
        enabled, which is the accident it was written to catch. Uncommenting
        the gpt-5 example -- 6x Luna's input price and 8x its output price, on
        an unscoped key -- still fails this test.
        """
        from ida_core.registry import load_registry

        assert set(load_registry(MODELS_YAML).enabled_keys()) == ALLOWED_ENABLED_KEYS

    def test_no_other_hosted_model_is_enabled(self) -> None:
        """The same guarantee stated the other way round, so that renaming a key
        cannot quietly satisfy the set-equality check above while turning on
        something expensive."""
        from ida_core.registry import load_registry

        registry = load_registry(MODELS_YAML)
        hosted_and_on = {
            entry.key
            for entry in registry.models
            if entry.enabled and entry.base_url.startswith("https://")
        }
        # qwen-local is https but self-hosted and free; the claude-* trio are
        # paid but pinned individually (and sweep-excluded) below.
        assert hosted_and_on - {"qwen-local"} - CLAUDE_KEYS == {"luna"}

    def test_the_budget_capped_entry_is_tagged_as_such(self) -> None:
        """The $25 cap is an OpenAI-side setting nothing in this repo can read.
        The tag is how an operator scanning the registry learns that selecting
        this entry spends real money from a test allowance."""
        from ida_core.registry import load_registry

        entry = load_registry(MODELS_YAML).get("luna")
        assert "testing-only" in entry.tags
        assert "budget-capped" in entry.tags

    def test_luna_declares_a_key_and_a_nonzero_price(self) -> None:
        """A hosted entry with `api_key_env: null` would send unauthenticated
        requests; one left at the 0.0 default would report every paid run as
        free. Both are checked for the examples already -- luna is live, so it
        matters more here, not less."""
        from ida_core.registry import load_registry

        entry = load_registry(MODELS_YAML).get("luna")
        assert entry.api_key_env == "OPENAI_API_KEY"
        assert entry.cost.input_usd_per_mtok > 0
        assert entry.cost.output_usd_per_mtok > 0

    def test_luna_takes_the_reasoning_client_not_the_plain_one(self) -> None:
        """gpt-5.6 rejects the legacy `max_tokens` that OpenAICompatibleClient
        sends. If this entry ever drifts back to `serving_stack: openai_api` it
        would 400 on every call -- in staging, with a key, having looked fine in
        CI where nothing calls it."""
        from ida_core.registry import load_registry

        entry = load_registry(MODELS_YAML).get("luna")
        assert entry.serving.serving_stack is ServingStack.OPENAI_REASONING
        assert client_class_for(entry).__name__ == "OpenAIReasoningClient"

    def test_luna_samples_at_the_api_default_temperature(self) -> None:
        """A reasoning model rejects a non-default temperature with a 400, so the
        benchmark default of 0.0 cannot be used here. Pinned as a test because
        the value looks wrong to anyone who knows the benchmark convention and
        is exactly the kind of thing a well-meaning edit 'fixes'."""
        from ida_core.registry import load_registry

        sampling = load_registry(MODELS_YAML).get("luna").serving.sampling
        assert sampling.temperature == 1.0
        assert sampling.top_p == 1.0

    def test_the_mock_still_takes_the_openai_compatible_client(self) -> None:
        from ida_core.registry import load_registry

        entry = load_registry(MODELS_YAML).get("mock")
        assert entry.serving.serving_stack is ServingStack.MOCK
        assert client_class_for(entry).__name__ == "OpenAICompatibleClient"


class TestPreflightOverAuthoredEntries:
    """Review B1 wired to the file authors actually edit.

    `check_entry` is the authoring-time guard for the trap where an
    `anthropic_compat` entry omits its `sampling:` block, inherits
    temperature 0.0, and 400s on every current model. Running it here means the
    python CI gate fails the PR that introduces such an entry -- which is the
    only moment it is cheap to fix.
    """

    @pytest.mark.parametrize("key,text", EXAMPLES, ids=[k for k, _ in EXAMPLES])
    def test_no_example_carries_a_configuration_error(self, key: str, text: str) -> None:
        found = errors(check_entry(_parse(text)))
        assert not found, "\n".join(str(p) for p in found)

    def test_the_live_registry_is_error_free(self) -> None:
        from ida_core.registry import load_registry

        found = errors(check_registry(load_registry(MODELS_YAML)))
        assert not found, "\n".join(str(p) for p in found)

    def test_the_flagship_anthropic_example_is_warning_free_too(self) -> None:
        """Opus 5 rejects non-default sampling outright, so the example we hand
        people must be clean at BOTH severities, not merely non-erroring."""
        from ida_core.registry import load_registry

        registry = load_registry(MODELS_YAML)
        for key in sorted(CLAUDE_KEYS):
            assert check_entry(registry.get(key)) == [], key

    def test_the_sonnet_4_6_example_warns_and_that_is_correct(self) -> None:
        """It deliberately sets temperature 0.0 because 4.6 still accepts
        sampling. A warning is the honest signal: right here, wrong if the
        model_id is ever bumped to a model that rejects it."""
        text = next(t for k, t in EXAMPLES if k == "claude-sonnet-4-6")
        problems = check_entry(_parse(text))
        assert [p.severity for p in problems] == ["warning"]
        assert errors(problems) == []


class TestQwenLocalEntry:
    def test_streams_and_has_thinking_off(self) -> None:
        """Cloudflare cuts non-streamed responses at ~30s, and the owner decided
        thinking stays off; both live in `extra` so they are recorded per result."""
        from ida_core.registry import load_registry

        extra = load_registry(MODELS_YAML).get("qwen-local").serving.extra
        assert extra["stream"] is True
        assert extra["chat_template_kwargs"] == {"enable_thinking": False}


class TestClaudeEntriesAreHeldOutOfSweeps:
    """The Anthropic key has no provider-side cap, unlike luna's. The only thing
    stopping a nightly sweep from spending it is the ``testing-only`` tag."""

    @pytest.mark.parametrize("key", sorted(CLAUDE_KEYS))
    def test_tagged_testing_only_and_wired_to_the_messages_client(self, key: str) -> None:
        from ida_core.registry import load_registry

        entry = load_registry(MODELS_YAML).get(key)
        assert "testing-only" in entry.tags
        assert entry.serving.serving_stack == ServingStack.ANTHROPIC_COMPAT
        assert entry.base_url == "https://api.anthropic.com/v1"
        assert entry.api_key_env == "ANTHROPIC_API_KEY"
        assert entry.serving.sampling.seed is None
        assert entry.cost.input_usd_per_mtok > 0
        assert entry.cost.output_usd_per_mtok > 0

    def test_pricing_matches_the_published_rates(self) -> None:
        from ida_core.registry import load_registry

        registry = load_registry(MODELS_YAML)
        rates = {
            k: (registry.get(k).cost.input_usd_per_mtok, registry.get(k).cost.output_usd_per_mtok)
            for k in CLAUDE_KEYS
        }
        assert rates == {
            "claude-fable-5-1": (10.0, 50.0),
            "claude-fable-5": (10.0, 50.0),
            "claude-opus-5-5": (4.0, 20.0),
            "claude-opus-5": (5.0, 25.0),
            "claude-opus-4-8": (5.0, 25.0),
            "claude-opus-4-7": (5.0, 25.0),
            "claude-opus-4-6": (5.0, 25.0),
            "claude-opus-4-5": (5.0, 25.0),
            "claude-sonnet-5-5": (2.0, 10.0),
            "claude-sonnet-5": (2.0, 10.0),
            "claude-sonnet-4-6": (3.0, 15.0),
            "claude-sonnet-4-5": (3.0, 15.0),
            "claude-haiku-5-5": (0.1, 0.5),
            "claude-haiku-4-5": (1.0, 5.0),
        }
        assert registry.get("claude-haiku-4-5").serving.model_id == "claude-haiku-4-5-20251001"
