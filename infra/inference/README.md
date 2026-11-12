# Off-cluster inference — the campus GB10 box

**Status: live, reachable, and it is ONE machine.** This file previously
described a deferred, unroutable second box called "Sparks". There was never a
second box.

## The correction

Until 2026-11-12 `models.yaml` carried two entries for one piece of hardware:

- `qwen-local`, pointed at `https://local-llm.uamishub.com/v1`, whose comment
  claimed it was "a different box" from
- `sparks-local`, a disabled placeholder for "the DGX-Spark hardware", waiting
  on an egress route that was never opened.

**`local-llm.uamishub.com` IS the DGX-Spark-class box.** It is
`promaxgb10-d62a` — a Dell Pro Max with GB10, 128 GB unified memory, aarch64 —
and the tailnet contains exactly one such machine. Modelling it as two meant a
reader could not tell which entry described the hardware that actually answers,
and it left a permanently-failing placeholder in the registry as if more
capacity were coming.

`sparks-local` is deleted. Its reproducibility fields — `hardware` and the exact
model id, the only things the placeholder existed to carry — now live on
`qwen-local`, along with its `campus` tag (the API derives the FERPA-relevant
residency claim from tags, so dropping it would have silently changed that
claim).

`SPARKS_BASE_URL` and `SPARKS_API_KEY` are consequently dead. They are still
projected by `.devops/chart/` and still listed, commented, in `.env.example`;
removing them from the chart edits the live cluster tenant, so it is deliberately
deferred to the retirement pass described below.

## What actually serves the model

```
harness ──► LiteLLM ──► Ollama ──► qwen3.8:27b-mtp-q4_K_M
            (auth,       (NO auth,   27.3B · Q4_K_M · ctx 262144
             teams,       host        ~19 GB resident · 100% GPU
             budgets)     systemd)    31.6–34.3 tok/s · warm 0.26s
```

Probed live 2026-11-12:

| | |
|---|---|
| `GET /api/version` | `{"version":"0.34.4"}` |
| `GET /v1/models` (LiteLLM) | `qwen3.8-27b-base`, `qwen3.8-27b`, `nomic-embed-text` |
| `ollama show` | `qwen35`, 27.3B params, context 262144, quantization `Q4_K_M` |
| `ollama ps` | `100% GPU`, `UNTIL Forever` (`keep_alive: -1`) |

**The box switched from vLLM to Ollama on 2026-10-24.** `gb10-vllm` is
`Exited(137)`; Ollama runs as a host systemd unit, not a container. The registry
recorded `serving_stack: vllm` / `vllm 0.30.0` for 19 days after that — for a
harness that stamps its serving stack onto every stored result, that was a
correctness bug, not a stale comment. It now records
`serving_stack: ollama` / `ollama 0.34.4`, with the exact backing tag in
`revision`.

No stored results were mislabelled: every `qwen-local` run in dev (0), staging
(1) and prod (28) is dated 2026-10-22, before the switch, so `vllm 0.30.0` is
correct for all of them. A run dated on or after 2026-10-24 carrying `vllm`
would be a genuine mislabel — **report it, do not rewrite it.**

## Two things that will bite you

**`model_id` is a LiteLLM alias, not an Ollama tag.** The registry sends
`qwen3.8-27b`. Sending `qwen3.8:27b-mtp-q4_K_M` to LiteLLM would 404.

**Never address Ollama directly.** `100.103.27.65:11434` has **no
authentication**, so hitting it bypasses keys, teams, budgets and per-team quota
entirely, and the request appears in no spend record. LiteLLM is the only
supported route. Relatedly, on the appliance the provider prefix
`ollama_chat/` is **mandatory** in `litellm-config.yaml`: behind a generic
`openai/` passthrough, `drop_params: true` silently strips `think` and
`num_ctx`, which leaves thinking on and defaults the window to the model maximum
— a ~16 GiB f16 KV cache, 24 of 66 layers spilled to CPU, and throughput down to
~7.8 tok/s. `ollama ps` showing anything other than `100% GPU` is the tell.

**Thinking is off, but this repo no longer enforces it.** The old
`extra.chat_template_kwargs: {enable_thinking: false}` was a *vLLM*
chat-template switch; Ollama does not read it, so after the switch it was a knob
that looked enforced and did nothing. Thinking-off now lives in `think: false`
in the appliance's `litellm-config.yaml`. The honest consequence: an edit to
that file changes benchmark results without anything in this repo moving. The
mitigation is that the appliance config is now committed to git and reconciled
by a timer (`platform-infra appliances/gb10/`), so the setting is auditable
rather than living only on the box's disk.

## Turning the route on

Nothing to turn on from the cluster — `qwen-local` is `enabled: true` and
reachable over the public `:443` hostname that the tenant egress policy already
allows. The netpol change the previous version of this file described is **not
needed** and was never made.

What *is* configurable is which route the harness takes, via
`base_url_env: LOCAL_LLM_BASE_URL`:

| Where the harness runs | `LOCAL_LLM_BASE_URL` | Path |
|---|---|---|
| In the cluster (today) | unset | literal `https://local-llm.uamishub.com/v1` → Cloudflare → tunnel → LiteLLM |
| On the GB10 box | `http://litellm:4000/v1` | straight to LiteLLM over the appliance docker network |

The second route removes two constraints that shaped this design:

- **Cloudflare's ~100 s cut** on a non-streamed `/v1/chat/completions`.
  `extra.stream: true` is nonetheless **kept** — it is still required on the
  public route, and it is inert on-box.
- **The tenant `:443`-only egress fence**, which is why a campus box on any
  other port was unreachable in the first place.

## The relocation

ida-llm is moving onto this box permanently. Phase 1 runs the GB10 stack
**alongside** the live cluster tenant; retirement is a separate, human-gated
pass.

- Design, cutover procedure and what is given up by leaving the cluster:
  `artifacts/design/ida-llm-gb10-relocation.md` in `Capstone-Modernization`.
- The stack itself: `appliances/gb10/ida-llm/` in `platform-infra`.

One consequence worth knowing before you plan work against it: **the box is
aarch64 and every promoted image in Harbor is amd64-only**, with no QEMU
registered, so a promoted image cannot execute there at all. The on-box stack
therefore builds its own images from the commit it reconciles to.

## What lives here

Notes for whoever operates the inference hardware. The hardware itself is **not**
configured from this repo: the appliance's compose file, LiteLLM config,
Prometheus rules and key portal all live in `platform-infra`
`appliances/gb10/`, which is deliberately outside ArgoCD. Putting a launch
manifest in this directory would not deploy anything — nothing reads this path.
