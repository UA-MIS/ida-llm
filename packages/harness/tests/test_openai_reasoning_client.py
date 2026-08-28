"""The OpenAI **reasoning** dialect: what differs from plain chat-completions.

Every assertion here is a claim about the wire, and each one costs a real 400 to
discover the hard way.  The two that matter most:

* ``max_tokens`` is rejected outright by the reasoning families -- *"Unsupported
  parameter: 'max_tokens' is not supported with this model. Use
  'max_completion_tokens' instead."*  The whole reason this client exists.
* a **non-default** ``temperature``/``top_p`` is rejected too, so a parameter
  already sitting at the API default is omitted rather than sent.

The omission is the same contract the Anthropic client makes, and for the same
reason: the value we omit is exactly the value the endpoint then uses, so the
``ServingConfig`` stamped on every result still describes what happened.  A
non-default value is always SENT, so that an author who pins temperature 0.0 on
a model that refuses it gets OpenAI's own 400 naming the parameter -- not a
benchmark quietly run at a temperature nobody chose.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ida_core.contracts import (
    ChatMessage,
    ModelEntry,
    SamplingParams,
    ServingConfig,
    ServingStack,
)
from ida_harness.client import (
    OPENAI_REASONING_DEFAULT_TEMPERATURE,
    OPENAI_REASONING_DEFAULT_TOP_P,
    OpenAICompatibleClient,
    OpenAIReasoningClient,
)

OK_BODY = {
    "id": "chatcmpl-luna-1",
    "model": "gpt-5.6-luna",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "42"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
}

MESSAGES = [ChatMessage(role="user", content="What is 40 + 2?")]


def _entry(**sampling) -> ModelEntry:
    return ModelEntry(
        key="luna",
        display_name="Luna",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        serving=ServingConfig(
            model_id="gpt-5.6-luna",
            serving_stack=ServingStack.OPENAI_REASONING,
            sampling=SamplingParams(**sampling),
        ),
    )


def _send(entry: ModelEntry, sampling: SamplingParams) -> dict:
    """Issue one completion through a MockTransport and return the request body."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=OK_BODY)

    client = OpenAIReasoningClient(
        entry,
        api_key="sk-test",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        jitter=lambda _lo, hi: hi,
    )
    with client:
        client.complete(MESSAGES, sampling)
    return seen


class TestTheOutputCap:
    def test_the_cap_is_sent_as_max_completion_tokens(self) -> None:
        """The single fact this client exists for."""
        seen = _send(_entry(), SamplingParams(max_tokens=64))
        assert seen["body"]["max_completion_tokens"] == 64

    def test_the_legacy_max_tokens_is_never_sent(self) -> None:
        """Sending it alongside the new name still 400s -- it is the presence of
        the key that is rejected, not a conflict between the two."""
        seen = _send(_entry(), SamplingParams(max_tokens=64))
        assert "max_tokens" not in seen["body"]

    def test_it_still_posts_to_chat_completions_with_the_registry_model_id(self) -> None:
        """Same endpoint and same response shape as the plain client: only the
        request dialect differs, which is why this is a subclass."""
        seen = _send(_entry(), SamplingParams(max_tokens=16))
        assert seen["url"] == "https://api.openai.com/v1/chat/completions"
        assert seen["body"]["model"] == "gpt-5.6-luna"
        assert seen["body"]["messages"] == [{"role": "user", "content": "What is 40 + 2?"}]
        assert seen["body"]["stream"] is False


class TestSampling:
    def test_default_temperature_and_top_p_are_omitted(self) -> None:
        """Reasoning models accept only the API default, so sending it explicitly
        buys nothing and omitting it is what the Anthropic client already does."""
        sampling = SamplingParams(
            temperature=OPENAI_REASONING_DEFAULT_TEMPERATURE,
            top_p=OPENAI_REASONING_DEFAULT_TOP_P,
            max_tokens=16,
        )
        seen = _send(_entry(), sampling)
        assert "temperature" not in seen["body"]
        assert "top_p" not in seen["body"]

    def test_a_non_default_temperature_is_sent_anyway(self) -> None:
        """Deliberately NOT silently dropped. A stored ServingConfig claiming
        temperature 0.0 on a run that was made at 1.0 is a fabricated
        measurement -- exactly what D-13 exists to prevent. Send it and let the
        provider's own 400 name the parameter."""
        seen = _send(_entry(), SamplingParams(temperature=0.0, max_tokens=16))
        assert seen["body"]["temperature"] == 0.0

    def test_a_non_default_top_p_is_sent_anyway(self) -> None:
        seen = _send(_entry(), SamplingParams(top_p=0.5, max_tokens=16))
        assert seen["body"]["top_p"] == 0.5

    def test_a_seed_is_still_forwarded_when_set(self) -> None:
        """Unlike Anthropic's Messages API, chat-completions HAS a seed field.
        It is best-effort on hosted models, but it is a real parameter, so
        refusing it here would be a statement about the protocol that is false."""
        seen = _send(_entry(), SamplingParams(max_tokens=16, seed=7))
        assert seen["body"]["seed"] == 7

    def test_an_unset_seed_is_omitted_not_nulled(self) -> None:
        seen = _send(_entry(), SamplingParams(max_tokens=16))
        assert "seed" not in seen["body"]

    def test_stop_sequences_are_forwarded_when_set(self) -> None:
        seen = _send(_entry(), SamplingParams(max_tokens=16, stop=["END"]))
        assert seen["body"]["stop"] == ["END"]


class TestItIsStillAnOpenAiClient:
    def test_it_subclasses_the_openai_compatible_client(self) -> None:
        """Response parsing, retry, backoff, status classification and usage
        accounting are all inherited -- this subclass is request-shape only."""
        assert issubclass(OpenAIReasoningClient, OpenAICompatibleClient)

    def test_the_response_is_parsed_by_the_inherited_parser(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=OK_BODY)

        client = OpenAIReasoningClient(
            _entry(),
            api_key="sk-test",
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
            jitter=lambda _lo, hi: hi,
        )
        with client:
            completion = client.complete(MESSAGES, SamplingParams(max_tokens=16))
        assert completion.content == "42"
        assert completion.usage.prompt_tokens == 11
        assert completion.usage.completion_tokens == 2
        assert completion.model == "gpt-5.6-luna"

    def test_the_key_is_presented_as_a_bearer_token(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json=OK_BODY)

        client = OpenAIReasoningClient(
            _entry(),
            api_key="sk-test",
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
            jitter=lambda _lo, hi: hi,
        )
        with client:
            client.complete(MESSAGES, SamplingParams(max_tokens=16))
        assert seen["auth"] == "Bearer sk-test"


class TestTheDefaultsAreTheApiDefaults:
    """If these drift from OpenAI's documented defaults the omission logic starts
    dropping values that are NOT what the endpoint would use, which turns the
    recorded ServingConfig into a lie."""

    def test_temperature_default_is_one(self) -> None:
        assert OPENAI_REASONING_DEFAULT_TEMPERATURE == 1.0

    def test_top_p_default_is_one(self) -> None:
        assert OPENAI_REASONING_DEFAULT_TOP_P == 1.0

    def test_the_benchmark_default_is_not_the_api_default(self) -> None:
        """The trap this whole client guards: SamplingParams defaults temperature
        to 0.0 (the *benchmark* default), which a reasoning model rejects. An
        author who writes no `sampling:` block inherits it."""
        assert SamplingParams().temperature != OPENAI_REASONING_DEFAULT_TEMPERATURE


@pytest.mark.parametrize("cap", [1, 2048, 131_072])
def test_the_cap_is_forwarded_verbatim_at_every_magnitude(cap: int) -> None:
    """A reasoning model spends thinking tokens inside this budget, so the number
    an author writes must reach the wire unmodified -- silently halving it to
    'leave room' would be us inventing the reproducibility record."""
    seen = _send(_entry(), SamplingParams(max_tokens=cap))
    assert seen["body"]["max_completion_tokens"] == cap


class TestAnEmptyAnswerThatRanOutOfBudget:
    """The failure mode unique to reasoning models, and the reason this client
    overrides ``_parse`` at all.

    ``max_completion_tokens`` is shared between thinking and the visible answer.
    Set it too low and the model spends the entire budget reasoning, then stops
    with ``finish_reason: "length"`` and ``content: ""``.  Nothing about that
    response is malformed, so the inherited parser returns a perfectly valid
    empty completion -- which a scorer grades **0.0** and stores as "the model
    got it wrong".

    It did not get it wrong.  We never gave it room to answer.  A benchmark that
    cannot tell those apart is producing fabricated measurements, so this is an
    error, not a zero.
    """

    def _body(self, *, content, finish_reason: str) -> dict:
        return {
            "id": "chatcmpl-luna-2",
            "model": "gpt-5.6-luna",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 4096, "total_tokens": 4107},
        }

    def _complete(self, body: dict):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        client = OpenAIReasoningClient(
            _entry(),
            api_key="sk-test",
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
            jitter=lambda _lo, hi: hi,
        )
        with client:
            return client.complete(MESSAGES, SamplingParams(max_tokens=4096))

    def test_it_refuses_rather_than_returning_an_empty_answer(self) -> None:
        from ida_harness.errors import PermanentModelError

        with pytest.raises(PermanentModelError):
            self._complete(self._body(content="", finish_reason="length"))

    def test_the_error_names_the_parameter_to_raise(self) -> None:
        """An operator hitting this needs the fix, not a diagnosis."""
        from ida_harness.errors import PermanentModelError

        with pytest.raises(PermanentModelError, match="max_completion_tokens"):
            self._complete(self._body(content="", finish_reason="length"))

    def test_it_is_permanent_not_transient(self) -> None:
        """Retrying spends the same budget to reach the same wall. The retry loop
        must not burn four attempts' worth of thinking tokens on it."""
        from ida_harness.errors import PermanentModelError, TransientModelError

        with pytest.raises(PermanentModelError) as caught:
            self._complete(self._body(content="", finish_reason="length"))
        assert not isinstance(caught.value, TransientModelError)

    def test_a_null_content_that_ran_out_of_budget_is_caught_too(self) -> None:
        """The API may send `content: null` rather than "". The inherited parser
        normalises that to "", so the guard must run after normalisation."""
        from ida_harness.errors import PermanentModelError

        with pytest.raises(PermanentModelError):
            self._complete(self._body(content=None, finish_reason="length"))

    def test_a_truncated_but_NONempty_answer_is_still_returned(self) -> None:
        """Deliberately narrow. A partial answer is evidence -- the scorer may
        well mark it wrong, and that is a real measurement of a real response.
        Only the empty case is indistinguishable from 'we never asked'."""
        completion = self._complete(self._body(content="the answer is 4", finish_reason="length"))
        assert completion.content == "the answer is 4"

    def test_an_empty_answer_that_stopped_NORMALLY_is_still_returned(self) -> None:
        """An empty completion with finish_reason 'stop' is honest emptiness -- a
        refusal, or a model that genuinely said nothing. That IS the measurement,
        and turning it into an error would discard a real result."""
        completion = self._complete(self._body(content="", finish_reason="stop"))
        assert completion.content == ""

    def test_a_response_with_no_finish_reason_is_left_alone(self) -> None:
        """Several OpenAI-compatible servers omit the field. Absence is not
        evidence of truncation, and guessing would fail live runs."""
        body = self._body(content="", finish_reason="stop")
        del body["choices"][0]["finish_reason"]
        assert self._complete(body).content == ""
