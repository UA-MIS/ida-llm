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
row in `CLIENT_BY_SERVING_STACK`.

## Why two clients (the D-1 resolution)

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
produced it (D-1), that is the wrong trade. Two subclasses of one base is the
smaller cost.

**Known wart.** `ServingStack.ANTHROPIC_COMPAT` (`"anthropic_compat"`) now selects
the Anthropic-*native* client, so its name reads slightly wrong. Renaming it is a
`packages/core` contract change — the enum, `models.schema.json`, and every
`serving_config` JSON blob already written to the `results` table — so it was
deliberately left alone rather than done as a side effect of this story.

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

**Anthropic — no seed.** The Messages API has no seed parameter. Rather than drop
a declared one, the client refuses to run: a stored result claiming a seeded,
reproducible run that was never seeded is precisely the fabricated measurement
D-1 exists to prevent. Set `serving.sampling.seed: null` on Anthropic entries.

**Anthropic — cache tokens.** `usage.input_tokens` excludes
`cache_creation_input_tokens` and `cache_read_input_tokens`, which bill at
different rates. The harness never sends `cache_control`, so those are zero;
they are preserved verbatim in the archived `raw` response rather than folded
into `prompt_tokens`, because summing them at the standard rate would misreport
cost the moment that changes.

**OpenAI — `max_tokens` vs `max_completion_tokens`.** OpenAI has deprecated
`max_tokens` in favour of `max_completion_tokens`, and the o-series rejects it
outright:

```
Unsupported parameter: 'max_tokens' is not supported with this model.
Use 'max_completion_tokens' instead.
```

The shared client still sends `max_tokens`, because vLLM, llama.cpp, Ollama and
the mock model all take that name and most do not accept the new one. Sending
either name per entry is the right fix and is **not** implemented here — the
exact set of affected OpenAI models is not documented, and inventing the
boundary would be a guess baked into a benchmark. Until then, prefer a
non-reasoning chat model, and note that the provider's own error now reaches the
operator verbatim.

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
