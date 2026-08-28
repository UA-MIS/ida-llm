"""Client selection: which client answers for a given ``models.yaml`` entry.

The point of these tests is that **selection is data, not code**.  Every
assertion here is driven by a ``serving_stack`` value an author writes in YAML;
none of them depends on a provider name appearing in a conditional.

No network: the two tests that actually issue a request use ``MockTransport``.
"""

from __future__ import annotations

import httpx
import pytest

from ida_core.contracts import (
    ChatMessage,
    ModelEntry,
    SamplingParams,
    ServingConfig,
    ServingStack,
)
from ida_core.registry import MissingApiKeyError
from ida_harness.anthropic_client import AnthropicMessagesClient
from ida_harness.client import ModelClient, OpenAICompatibleClient, OpenAIReasoningClient
from ida_harness.factory import build_client, client_class_for

MESSAGES = [ChatMessage(role="user", content="hi")]
SAMPLING = SamplingParams(max_tokens=16)


def _entry(stack: ServingStack, **kwargs) -> ModelEntry:
    return ModelEntry(
        key=kwargs.pop("key", "m"),
        display_name="M",
        base_url=kwargs.pop("base_url", "https://example.test/v1"),
        serving=ServingConfig(model_id="model-1", serving_stack=stack),
        **kwargs,
    )


class TestSelection:
    def test_anthropic_stack_selects_the_messages_client(self) -> None:
        assert client_class_for(_entry(ServingStack.ANTHROPIC_COMPAT)) is AnthropicMessagesClient

    def test_openai_reasoning_stack_selects_the_reasoning_client(self) -> None:
        """`luna` is a GPT-5.6 model: it rejects the legacy `max_tokens` the
        plain client sends, so selecting the wrong one here is a 400 on every
        call, not a subtle difference."""
        assert client_class_for(_entry(ServingStack.OPENAI_REASONING)) is OpenAIReasoningClient

    def test_the_reasoning_stack_is_not_the_default(self) -> None:
        """Guards the row's existence. Delete it from the table and selection
        silently falls through to OpenAICompatibleClient -- which is exactly the
        failure this stack was added to prevent, and it would look fine."""
        assert client_class_for(_entry(ServingStack.OPENAI_REASONING)) is not (
            OpenAICompatibleClient
        )

    @pytest.mark.parametrize(
        "stack",
        [
            ServingStack.OPENAI_API,
            ServingStack.VLLM,
            ServingStack.OLLAMA,
            ServingStack.LLAMA_CPP,
            ServingStack.MOCK,
        ],
    )
    def test_every_other_stack_uses_the_openai_compatible_client(self, stack) -> None:
        """The default is the point: a new vLLM box is a YAML edit, no code."""
        assert client_class_for(_entry(stack)) is OpenAICompatibleClient

    def test_every_serving_stack_resolves_to_some_client(self) -> None:
        """A stack added to the core enum must not fall off the end of the table."""
        for stack in ServingStack:
            assert client_class_for(_entry(stack)) is not None

    def test_built_clients_satisfy_the_protocol(self) -> None:
        for stack in (
            ServingStack.MOCK,
            ServingStack.ANTHROPIC_COMPAT,
            ServingStack.OPENAI_REASONING,
        ):
            client = build_client(_entry(stack), api_key="k")
            with client:
                assert isinstance(client, ModelClient)


class TestKeyResolution:
    def test_a_declared_key_is_read_from_the_environment(self) -> None:
        entry = _entry(ServingStack.ANTHROPIC_COMPAT, api_key_env="ANTHROPIC_API_KEY")
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["key"] = request.headers.get("x-api-key")
            return httpx.Response(
                200, json={"content": [{"type": "text", "text": "ok"}], "model": "model-1"}
            )

        client = build_client(
            entry,
            env={"ANTHROPIC_API_KEY": "sk-ant-from-env"},
            transport=httpx.MockTransport(handler),
        )
        with client:
            client.complete(MESSAGES, SAMPLING)
        assert seen["key"] == "sk-ant-from-env"

    def test_an_explicit_key_wins_over_the_environment(self) -> None:
        """The runner service resolves the key itself so it can fail a job
        before any work starts; passing it must not trigger a second lookup."""
        entry = _entry(ServingStack.ANTHROPIC_COMPAT, api_key_env="ANTHROPIC_API_KEY")
        client = build_client(entry, api_key="explicit", env={})
        client.close()

    def test_missing_key_is_loud_and_names_the_variable(self) -> None:
        entry = _entry(ServingStack.OPENAI_API, api_key_env="OPENAI_API_KEY")
        with pytest.raises(MissingApiKeyError, match="OPENAI_API_KEY"):
            build_client(entry, env={})

    def test_no_key_needed_when_the_entry_declares_none(self) -> None:
        """An unauthenticated endpoint: the mock model, campus vLLM behind a
        NetworkPolicy. Not a fallback -- a declared property of the entry."""
        client = build_client(_entry(ServingStack.MOCK), env={})
        client.close()


class TestNoMockFallback:
    def test_an_unconfigured_provider_fails_instead_of_substituting(self) -> None:
        """A stand-in scored under a frontier model's name poisons the results
        table, and nothing downstream can tell that it did."""
        entry = _entry(ServingStack.ANTHROPIC_COMPAT, api_key_env="ANTHROPIC_API_KEY")
        with pytest.raises(MissingApiKeyError):
            build_client(entry, env={"SOMETHING_ELSE": "x"})

    def test_an_unreachable_endpoint_fails_instead_of_substituting(self) -> None:
        from ida_core.registry import MissingBaseUrlError

        entry = ModelEntry(
            key="sparks",
            display_name="Sparks",
            base_url="",
            base_url_env="SPARKS_BASE_URL",
            serving=ServingConfig(model_id="m", serving_stack=ServingStack.VLLM),
        )
        # `env` governs KEY resolution only; the base URL resolves against the
        # real process environment, where SPARKS_BASE_URL is unset everywhere.
        with pytest.raises(MissingBaseUrlError, match="SPARKS_BASE_URL"):
            build_client(entry)
