# Model clients

How a row in `models.yaml` becomes an HTTP request, and why there are two
clients instead of one.

## The shape

```
models.yaml entry
      |
      |  serving.serving_stack
      v
ida_harness.factory.build_client()      <- the ONE place a provider is named
      |
      +-- anthropic_compat --> AnthropicMessagesClient   POST {base}/messages
      |
      +-- everything else  --> OpenAICompatibleClient    POST {base}/chat/completions
                               (openai_api, vllm, ollama, llama_cpp, mock)
```

Both are `BaseChatClient` subclasses and both satisfy the `ModelClient`
protocol. The base owns everything that is not wire format: transport and
connection pooling, timeouts, the retry loop, backoff with full jitter,
`Retry-After`, status classification, JSON guarding, latency measurement. A
subclass supplies four things — `PATH`, `_headers`, `_build_payload`, `_parse` —
and nothing else.

`run_task()` calls `build_client()` when no client is injected, so the runner
service gets provider selection without knowing that providers exist.

## Adding a model

Edit `models.yaml`. That is the whole procedure for any OpenAI-compatible
endpoint — a new campus vLLM deployment, a laptop llama.cpp server, a different
hosted provider — because they all fall through to the default client. There is
no code change and no new file.

Adding a genuinely new *wire format* is a new `BaseChatClient` subclass plus one
row in `CLIENT_BY_SERVING_STACK` — done twice so far, for the Anthropic Messages
API and for the OpenAI reasoning dialect. Adding a model that *uses* an existing
wire format is still only a `models.yaml` edit, including a hosted one: `luna`
picks its client by writing `serving_stack: openai_reasoning`.

If the model needs a key, [`provider-keys.md`](provider-keys.md) is the rest of
the procedure — naming the variable is step 1 of 6, and the last five are in
Vault and the chart.

## Why three clients (the D-13 resolution)

The scaffold asserted "there is no per-provider code anywhere", and `models.yaml`
carried a commented example claiming Anthropic "exposes an OpenAI-compatible
surface, so it needs no special-casing".

The first claim is a statement about **change cost** — adding a model must not be
a code change — and it still holds exactly as written.

The second is a statement about **wire format**, and it is not true of the
Messages API, which is what this project benchmarks against:

| chat/completions | Messages API |
|---|---|
| `Authorization: Bearer` | `x-api-key` + a required `anthropic-version` |
| system prompt is a message | `system` is a top-level field |
| `max_tokens` optional | `max_tokens` required |
| `choices[0].message.content` | `content` is a list of typed blocks |
| `usage.prompt_tokens` | `usage.input_tokens` |

Anthropic does publish an OpenAI-compatibility shim, and routing through it would
have preserved the single-client story. It was rejected: the shim is a
translation layer in front of the real API, so every stored number would describe
a surface we did not choose, cannot version, and cannot cite. For a project whose
entire premise is that a result is worthless unless you can say exactly what
produced it (D-13), that is the wrong trade. Two subclasses of one base is the
smaller cost.

**Known wart.** `ServingStack.ANTHROPIC_COMPAT` (`"anthropic_compat"`) now selects
the Anthropic-*native* client, so its name reads slightly wrong. Renaming it is a
`packages/core` contract change — the enum, `models.schema.json`, and every
`serving_config` JSON blob already written to the `results` table — so it was
deliberately left alone rather than done as a side effect of this story.

### The third: `openai_reasoning`

Added for #48, when `luna` (`gpt-5.6-luna`) became the first hosted model this
project enables. Same URL, same headers, same response shape as
chat-completions — so `OpenAIReasoningClient` subclasses `OpenAICompatibleClient`
and overrides the request body and one parse-time refusal, nothing else.

| chat/completions | the reasoning dialect |
|---|---|
| `max_tokens` | `max_completion_tokens` — and `max_tokens` is a 400 |
| bounds visible output | bounds visible output **plus reasoning tokens** |
| any `temperature`/`top_p` | only the API default (1.0); anything else is a 400 |

Why a separate stack rather than a flag on the shared client: because a flag
would put one provider's quirks inside the client every *other*
OpenAI-compatible server also uses — a campus vLLM box, a laptop llama.cpp —
and those accept the legacy name. A wire format is exactly what `serving_stack`
selects, so this is the seam that already existed.

The same D-13 test applies and passes: adding Luna was a `models.yaml` edit plus
one subclass, **no code anywhere names "luna" or "gpt-5.6"**, and no client
contains an `if provider == ...`. Selecting the dialect is a value an author
writes in YAML.

## Things that will bite you against real endpoints

These are documented rather than worked around, because the correct workaround is
not knowable without a key and a real call, and a guessed one is worse than a
stated gap.

**Anthropic — sampling parameters.** Anthropic's defaults are `temperature=1.0`
and `top_p=1.0`. Current models (Opus 5, Sonnet 5, Opus 4.8/4.7) reject a
*non-default* `temperature`/`top_p` with a 400, and Claude 4.x rejects both being
sent together. The client therefore omits a parameter that already sits at
Anthropic's default. That is not a silent drop: the omitted value is exactly the
value the endpoint then uses, so the `ServingConfig` stamped on the result stays
true. A non-default value is always sent, and if the model rejects it the
operator gets Anthropic's own 400 text naming the field — never a benchmark
quietly run at a temperature nobody chose.

**Anthropic — the dangerous default.** `SamplingParams.temperature` defaults to
`0.0` (the *benchmark* default), and current Claude models reject a non-default
`temperature` with a 400. An `anthropic_compat` entry that simply omits its
`sampling:` block therefore inherits `0.0` and fails every call — a mistake that
is invisible in the YAML, because it is a line nobody wrote.

`ida_harness.preflight.check_entry()` catches this at **authoring** time, and the
test suite runs it over every entry in `models.yaml`, so a bad entry fails the PR
rather than the benchmark. It is deliberately *not* a runtime guard: `seed` can be
refused in the client forever because the Messages API has no such parameter,
whereas `temperature` merely happens to be restricted on today's models — a hard
raise would be wrong the day one accepts it again. Severities follow that logic:

| | |
|---|---|
| `seed` set | **error** — no Anthropic model has ever had one |
| both `temperature` and `top_p` non-default | **error** — no Claude model accepts the pair |
| one of them non-default | **warning** — correct against Sonnet 4.6 / Haiku 4.5, wrong against Opus 5 |

**Anthropic — no seed.** The Messages API has no seed parameter. Rather than drop
a declared one, the client refuses to run: a stored result claiming a seeded,
reproducible run that was never seeded is precisely the fabricated measurement
D-13 exists to prevent. Set `serving.sampling.seed: null` on Anthropic entries.

**Anthropic — cache tokens.** `usage.input_tokens` excludes
`cache_creation_input_tokens` and `cache_read_input_tokens`, which bill at
different rates. The harness never sends `cache_control`, so those are zero;
they are preserved verbatim in the archived `raw` response rather than folded
into `prompt_tokens`, because summing them at the standard rate would misreport
cost the moment that changes.

**OpenAI — `max_tokens` vs `max_completion_tokens`.** OpenAI has deprecated
`max_tokens` in favour of `max_completion_tokens`, and the reasoning families —
the o-series and GPT-5/5.4/5.5/5.6 — reject it outright:

```
Unsupported parameter: 'max_tokens' is not supported with this model.
Use 'max_completion_tokens' instead.
```

**This is now handled, and the fix is a third client** (#48, added when `luna` /
`gpt-5.6-luna` was enabled — see [Why three clients](#why-three-clients-the-d-13-resolution)).

The earlier note here said sending either name per entry was the right fix but
was not implemented, because "the exact set of affected OpenAI models is not
documented, and inventing the boundary would be a guess baked into a benchmark".
That reasoning was right and is **unchanged**: nothing added since then guesses
the boundary. `OpenAIReasoningClient` does not sniff model ids. The registry
author *declares* the dialect by writing `serving_stack: openai_reasoning`, which
is the same mechanism that already chose between chat-completions and the
Messages API. We did not discover the boundary; we stopped needing to know it.

The shared `OpenAICompatibleClient` still sends `max_tokens`, and must: vLLM,
llama.cpp, Ollama and the mock model all take that name and most do not accept
the new one. Note the direction of the default — an unrecognised stack gets the
*legacy* name. That is the right failure. A local server that has never heard of
`max_completion_tokens` would break confusingly under the new name, whereas a
hosted model that rejects `max_tokens` says so in one loud, self-describing 400.

**The output cap means something different in the reasoning dialect.**
`max_completion_tokens` bounds visible output tokens **plus reasoning tokens**.
Two consequences worth knowing before you author an entry:

- A cap that is comfortable for a non-reasoning model can be consumed entirely
  by thinking, leaving `content: ""` with `finish_reason: "length"`. That
  response is perfectly well-formed, so the scorer would grade it **0.0** and
  store "the model got it wrong" — a fabricated measurement. `OpenAIReasoningClient`
  refuses it instead, with a `PermanentModelError` naming the parameter to raise.
  The check is narrow on purpose: a *truncated but non-empty* answer is a real
  response and is returned, and an *empty* answer that stopped normally is honest
  emptiness (a refusal) and is also returned.
- Numbers from a reasoning model are not comparable to a non-reasoning model's
  at the same nominal cap, because the two caps are not measuring the same thing.

**Sampling cannot be pinned on a reasoning model.** They accept only OpenAI's
default `temperature`/`top_p` of 1.0, so the benchmark default of 0.0 is a 400.
A parameter already at the default is therefore omitted from the body — the same
contract the Anthropic client makes, and true for the same reason: the omitted
value is exactly the value the endpoint then uses, so the stored `ServingConfig`
still describes what happened. A **non-default** value is always sent, so an
author who pins 0.0 gets OpenAI's own 400 naming the parameter rather than a
benchmark quietly run at a temperature nobody chose. `ida_harness.preflight`
warns about the combination at authoring time, where it is cheap to fix.

The practical consequence: **runs against a reasoning model are not
bit-reproducible** the way a mock or a seeded vLLM run is. That is a property of
the model, not a gap in this harness, and it belongs in the interpretation of any
number produced from one.

## Failure behaviour

**Retryable** (`TransientModelError`): 408, 409, 425, 429, 500, 502, 503, 504,
**529**. 529 is Anthropic's `overloaded_error` — absent from the IANA registry
and easy to misclassify as permanent, which would fail an entire benchmark run
over a capacity blip.

**Not retryable** (`PermanentModelError`): everything else in 4xx/5xx, non-JSON
bodies, unparseable response shapes. Retrying a 401 burns rate limit and delays
the real error.

**`Retry-After`** raises the floor of the next delay (`max(backoff, retry_after)`,
so full jitter survives and a 0.1s header cannot reset a long backoff). Only the
delta-seconds form is honoured; the HTTP-date form is legal but neither provider
sends it, and reading it means trusting our clock against theirs. A value over
`MAX_HONOURED_RETRY_AFTER_S` (120s) stops the retry loop instead of parking a
worker on a quota that will not return in time — the error says how long was
asked for.

**Provider error text is surfaced.** `returned HTTP 400` points nowhere;
`temperature: Extra inputs are not permitted` points at the `models.yaml` line
that caused it. Both providers nest the message identically
(`{"error": {"message": ...}}`), so reading it is one shape, not a branch.

## No mock fallback, ever

A missing key raises at client construction, naming the variable and where it
comes from. An unresolvable base URL raises naming the variable. Neither ever
degrades to the mock model.

This is the rule the rest of the design bends around. A deterministic stand-in
scored under a frontier model's name would land in the `results` table
indistinguishable from a real measurement, and nothing downstream — not the API,
not the UI, not a citation — could tell. A failed run is recoverable; a poisoned
row is not.

## Testing

Every client test drives real `httpx` machinery through an `httpx.MockTransport`:
genuine request building, status handling and parsing, with no socket, no key and
no spend. **No test in the harness makes a network call.**

Response fixtures are copied from the providers' own published examples with the
source URL and retrieval date recorded next to them
(`tests/test_anthropic_client.py`, `tests/test_client.py`). A fixture invented to
match our parser only proves the parser matches itself.

`tests/test_registry_examples.py` uncomments the example entries in `models.yaml`
and validates them, so a commented-out example cannot rot into something that
fails the first time somebody uncomments it with a credit card attached.

## Still parked

Real staging verification — one real call per provider, against a real key, with
credits attached. Nothing in this repo has yet talked to Anthropic or OpenAI.
The mocked tests prove we send what the documentation describes and read what it
returns; they cannot prove the documentation is complete.

This is now unblocked for **one** provider and is the explicit next step for
`luna`: `OPENAI_API_KEY` is in Vault and projected into the deployed runner, so
the bounded smoke test happens **in staging, after deploy** — never from a dev
box, which holds no key by design. What it would prove that no mocked test can:
that `gpt-5.6-luna` accepts `max_completion_tokens` and the omitted sampling
params, that its response parses, and that reported token counts produce a
sensible `cost_usd`. Until it has been run, treat "luna works end to end" as
*designed and unit-proven*, not *observed*. See
[`provider-keys.md`](provider-keys.md) and [`calibration.md`](calibration.md).
