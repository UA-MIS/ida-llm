# Local model serving — running open models on our own hardware

**Status: research + direction, no code (board #36, formerly framed as #52
"Local-model serving research").** This answers three questions: which open
models are realistic candidates, how we would actually serve them, and how
that connects to the privacy pitch this project is already making to
researchers ([`docs/researcher-track.md`](researcher-track.md) §0 and §4). It
does not choose a model, and it does not turn anything on — `sparks-local` in
[`models.yaml`](../models.yaml) stays disabled until the blockers below are
actually cleared.

**A note on recency, up front.** Open-weight models ship new frontier
generations every few months, from an expanding set of labs. The families
named below are the ones with primary-sourced facts (license files, model
cards, vendor docs) as of this research — treat them as a snapshot, not a
permanent shortlist, and re-check each model's current card and license
before an actual procurement or deployment decision. Confidence levels are
called out per section rather than assumed uniform: license text and hardware
specs are high-confidence (primary sources, linked); capacity arithmetic is
my own estimate from public quantization rules of thumb (medium confidence —
verify before sizing a real deployment on it); which model best fits which
research task is a reasoned inference, not a measurement (low confidence, and
exactly the kind of claim this project's own benchmark exists to replace with
a real one).

---

## 0. Why this document exists

[`docs/sensitive-material.md`](sensitive-material.md) §5 states the FERPA-side
rule plainly: local inference "is now a capability we want, not a precondition
we are blocked on." [`docs/researcher-track.md`](researcher-track.md) §4 states
the research-side analogue and its honest gap: *"there is no local inference
surface available today,"* so the sensitive branch of the research-privacy rule
currently has no model to recommend. Both documents point here. This is the
research that is supposed to close that gap — not by building it, but by
narrowing "local inference, eventually" down to a short list of real choices.

---

## 1. Which open models are viable candidates

The comparison is scoped to what actually matters for this project's task mix
— subjective scholarly writing and synthesis (`research-synthesis`,
`scholarly-writing`), quantitative research-methods reasoning
(`research-analysis`), and general SLO-style capability/assist tasks — not
coding-agent or multimodal benchmarks, which dominate most "best open model"
roundups and are not what this benchmark measures.

| family | sizes that matter here | license | context | why it's here | fits on one campus GPU box (see §2)? |
|---|---|---|---|---|---|
| **Qwen2.5 / Qwen3** (Alibaba) | dense 0.6B–32B; MoE 30B-A3B, 235B-A22B | Apache 2.0 across the line[^qwen] | up to 128K | strong general reasoning + writing, and Qwen3 has a togglable step-by-step "thinking" mode that suits the quantitative-reasoning ladder in `research-analysis` | 32B dense: yes, comfortably. 235B-A22B MoE: tight at 4-bit once KV-cache is added — the case for the two-box linked configuration |
| **gpt-oss-120b / gpt-oss-20b** (OpenAI) | 116.8B total / 5.1B active; 20.9B total / 3.6B active | Apache 2.0[^gptoss] | 128K | OpenAI's own open-weight release, from the same lab as the hosted `luna` entry already in `models.yaml` — reasoning-tuned, and 120b is stated to run on a single 80GB GPU | 120b: yes, comfortably inside 128GB unified memory. 20b: yes, trivially |
| **DeepSeek-R1** (full + official distills) | full: 671B MoE. Distills: 1.5B/7B/8B/14B/32B/70B, distilled onto Qwen2.5 or Llama 3.1 bases | weights: MIT[^dsr1] | varies by base (up to 128K on the larger bases) | the strongest of this set at step-by-step quantitative reasoning — a plausible match for the effect-size / power-and-sample-size / analysis-code-trace rungs in `research-analysis` | 32B/70B Qwen-based distill: yes. Full 671B: no, not on one box |
| **Llama 3.1 / 3.3** (Meta) | 8B, 70B, 405B | Llama Community License — custom, not OSI-approved; requires "Built with Llama" attribution and "Llama" in any derivative model's name; carries an EU carve-out for the multimodal variants[^llama] | 128K | the most mature tooling/eval ecosystem of any family here | 70B: yes at 4-bit. 405B: no, needs the linked two-box config |
| **Mistral / Mixtral** (Mistral AI) | 7B, 8x7B, 8x22B (the original line) | Apache 2.0 for the originals — but some newer Mistral releases have shipped under a non-commercial research license, so check the *specific* checkpoint, not the family name | 32K–128K depending on release | efficient MoE, solid writing quality at lower compute cost than a same-quality dense model | yes |
| **Gemma** (Google) / **Phi-4** (Microsoft) | Gemma 2B–27B; Phi-4 ≈14B | Gemma: Google's own terms of use, with field-of-use restrictions (not OSI-approved). Phi-4: MIT | 8K–128K | cheap, fast, "good enough" — not primary picks for this project's heaviest tasks (long-form scholarly writing, multi-step analysis), but a reasonable pick for a lightweight, always-on secondary role | yes, trivially |

**A note on the DeepSeek-based distills specifically:** prefer the **Qwen-based**
checkpoints over the Llama-based ones. DeepSeek's own added weights are MIT,
but the Llama-based distills sit on top of a Llama 3.1 base, and the community
has flagged the resulting license stack (MIT weights, Llama-licensed base) as
unresolved rather than settled[^dsr1]. The Qwen2.5 base is Apache 2.0, so the
Qwen-based distills have no equivalent tangle.

**A note that is a policy question, not a technical one:** DeepSeek is a
China-based lab. Several US institutions apply extra procurement and
data-governance review to models of Chinese origin, independent of how
permissive the license text is. That is worth raising with OIT/IDA leadership
before standardizing on a DeepSeek checkpoint — named here so it doesn't get
decided by default, not decided.

**On "which model is actually best for our tasks":** nobody in this
document has run one. The honest answer is in §7 — decide with the benchmark
itself, once any local model is wired in, rather than from a spec sheet.

---

## 2. Where these would run: the hardware already named in this repo

The hardware nickname this project already uses — "Sparks" — and the one
populated hardware value in `models.yaml`'s disabled `sparks-local` entry
(`hardware: 1x DGX Spark GB10 128GB unified`) both point at the same real
product: **NVIDIA's DGX Spark**, a desktop unit built around the GB10 Grace
Blackwell Superchip.

Specs, as marketed at launch — high confidence, primary/trade-press sourced:

- 20-core Arm CPU (10 Cortex-X925 performance + 10 Cortex-A725 efficiency
  cores) paired with a Blackwell GPU on one superchip.[^spark]
- **128GB of LPDDR5x memory, unified between CPU and GPU** — no PCIe transfer
  between "system RAM" and "VRAM," which matters for inference specifically
  because the whole model can be resident without a copy step.[^spark]
- Up to 1 PFLOP of sparse FP4 tensor performance.[^spark]
- NVIDIA's own positioning: inference on models **up to ~200B parameters** on
  one unit, and **up to ~405B parameters** across **two units linked** via
  ConnectX networking.[^spark]

**Capacity arithmetic (medium confidence — my own estimate, verify before
relying on it):** as a rule of thumb, weights occupy roughly 2 bytes/parameter
at 16-bit, ~1 byte/parameter at 8-bit, and ~0.5–0.6 bytes/parameter at 4-bit
(the AWQ/GPTQ quantization the repo's own commented-out example already
assumes for `vllm-spark-qwen3-32b`). At 4-bit that puts a 32B dense model at
roughly 18–20GB of weights, a 70B dense model at roughly 38–42GB, and
gpt-oss-120b inside the ~80GB OpenAI itself cites for a single GPU — all
comfortably inside 128GB with room left for KV-cache and a real context
window. A 235B-class MoE model (Qwen3's largest) is where the arithmetic gets
tight against 128GB once cache is counted — the point at which the two-unit
linked configuration stops being a nice-to-have and becomes the realistic
answer.

---

## 3. How these would be served: the tooling decision is mostly already made

| tool | throughput / concurrency | OpenAI-compatible endpoint? | best fit here |
|---|---|---|---|
| **vLLM** | continuous batching, built for many concurrent requests | yes, natively | the shared campus tier — this is what `infra/inference/README.md` and every commented `models.yaml` example already assume |
| **Ollama** | single-user convenience; not built for concurrent load | yes, via its `/v1` endpoint | a researcher's own laptop, not a shared service |
| **llama.cpp server** | runs on CPU-only or modest hardware via GGUF quantization; the most portable option | yes | the same personal-machine tier as Ollama — genuinely offline |
| **TGI** (Hugging Face) | production-grade, comparable to vLLM | yes | not evaluated further — this repo has already standardized on vLLM, and nothing suggests it's inadequate |

This is the least contested part of this document: **the serving-stack
decision is essentially already made.** `infra/inference/README.md` names
vLLM, `models.yaml`'s `sparks-local` and the commented `vllm-spark-qwen3-32b`
example both assume it, and every candidate in §1 is servable through vLLM's
standard OpenAI-compatible `/v1/chat/completions` endpoint — the same wire
format `docs/model-clients.md` already documents a client for. **No new
provider client is implied by anything in this document, for any model in
§1.** What's actually open is the model pick and the network path (§4), not
the tooling.

---

## 4. Two tiers of "local," and why the second is available today

**Tier A — the shared campus GPU tier (Sparks + vLLM).** Centrally operated,
the highest capability ceiling of the two tiers, and currently blocked on
infrastructure that is already named and not a mystery:
`infra/inference/README.md` documents the exact gap — the tenant egress policy
opens `:443` only, vLLM defaults to `:8000`, and the NetworkPolicy change lives
in `platform-infra`, not this repo. Turning it on is two changes "in either
order," per that document: the egress route, and `SPARKS_BASE_URL` /
`SPARKS_API_KEY` plus a real `model_id` in `models.yaml`.

**Tier B — the researcher's own machine (Ollama or llama.cpp, an 8B–14B pick
from §1).** Weaker capability ceiling, but genuinely available **today**, with
**zero dependency on this project's blocked infrastructure work.** No
NetworkPolicy change, no Vault key, no PR. "Nothing left this laptop" is also a
*stronger* privacy claim than "nothing left the university network" — it has
no dependency on this project's infrastructure being correct, either.

This matters for the positioning in
[`docs/researcher-track.md`](researcher-track.md) §0: the privacy pitch does
not have to wait on Tier A closing. A researcher who needs a local option now,
not once egress is unblocked, can be told honestly today: install Ollama, pull
an open 8B–14B model, use it for drafting or triage help on the most sensitive
material, at a real but currently unmeasured capability cost — and this
platform's own benchmark, once it can reach any local model at all, is exactly
the tool that could tell them how large that cost actually is, rather than
leaving them to guess.

---

## 5. Integration path into this repo

`models.yaml` already carries the `sparks-local` entry, disabled, fully
commented, with named placeholders (`base_url_env: SPARKS_BASE_URL`,
`api_key_env: SPARKS_API_KEY`, `model_id: TODO-PLACEHOLDER-sparks-model-id`),
plus a second, fully-specified commented example
(`vllm-spark-qwen3-32b`) that already assumes vLLM serving a Qwen3-32B AWQ
checkpoint. Turning either on is, per `infra/inference/README.md` and the
comments in `models.yaml` itself:

1. the platform-infra egress NetworkPolicy change (Tier A only — not needed
   for anyone testing Tier B on their own machine);
2. `SPARKS_BASE_URL` / `SPARKS_API_KEY` seeded in Vault and the environment
   overlay;
3. replacing the placeholder `model_id` with whatever is actually loaded, and
   filling in `serving_version` / `quantization` / `revision` once they're
   knowable (the registry's reproducibility fields exist precisely so a served
   local model is as fully specified as a hosted one).

No code change is implied by any of this — the registry's own comments already
say adding a model is a YAML edit, and §3 above is why that stays true for
every family in §1.

There is no integration path for Tier B today, and there doesn't need to be
one: it is guidance for a researcher's own workflow outside the benchmark, not
a `models.yaml` entry. If it's ever worth *benchmarking* what a researcher can
run at home — "how much capability does the personal-machine tier actually
cost you" — that would be a new registry entry pointed at a documented local
endpoint, which is still a YAML edit, not new code.

---

## 6. Cost

Every entry in §1, like `mock` and the existing `sparks-local` placeholder,
costs `$0.0` per token once the hardware exists — no `$25`-style hard cap, no
`testing-only` sweep-exclusion bookkeeping of the kind `luna` has needed twice
already in this project's history. That is not the same as free: campus GPU
time and depreciation are real costs, and Tier B costs the researcher's own
machine time. Neither shows up as a per-token invoice, though, which is
precisely the operational overhead a metered hosted model generates — this is
a metered-and-capped cost traded for an unmetered-but-capital one, not a cost
eliminated.

---

## 7. Open questions

- **Which model should Tier A actually standardize on?** This document names
  candidates and tradeoff axes; it does not decide. The right way to decide is
  empirically — wire in any one candidate and run it through this project's
  own benchmark — rather than from a spec sheet. That is the project's own
  thesis, applied to itself.
- **Does the right pick even depend on which researcher is asking?** A
  literature-synthesis-heavy researcher and a quantitative-analysis-heavy one
  might favor different families in §1. **Provisional, pending interviews**
  (#23/#43) — this document has no data yet on the actual task mix researchers
  would send to a local model.
- **The DeepSeek-origin procurement question** (§1) needs an OIT/IDA policy
  answer, not a technical one.
- **Is Tier B worth an official, supported how-to for researchers, or does it
  stay informal advice?** A product decision, not a technical one — flagged
  for the team, not resolved here.
- **The frontier moves fast.** Re-verify the specific families, sizes and
  licenses above against current model cards before an actual procurement or
  deployment decision — this document is a snapshot of what was verifiable
  now, not a standing recommendation with an expiration date attached.

---

## Sources

- [NVIDIA DGX Spark product page](https://www.nvidia.com/en-us/products/workstations/dgx-spark/)
- [NVIDIA DGX Spark In-Depth Review — LMSYS Org](https://www.lmsys.org/blog/2025-10-13-nvidia-dgx-spark/)
- [NVIDIA DGX Spark Review — ServeTheHome](https://www.servethehome.com/nvidia-dgx-spark-review-the-gb10-machine-is-so-freaking-cool/2/)
- [gpt-oss-120b — Apache 2.0 LICENSE, GitHub](https://github.com/gpt-oss/gpt-oss-120b/blob/main/LICENSE)
- [gpt-oss-120b & gpt-oss-20b Model Card — OpenAI](https://openai.com/index/gpt-oss-model-card/)
- [openai/gpt-oss-120b — Hugging Face](https://huggingface.co/openai/gpt-oss-120b)
- [Qwen3 — GitHub, QwenLM](https://github.com/qwenLM/qwen3)
- [Qwen3: Think Deeper, Act Faster — Qwen blog](https://qwenlm.github.io/blog/qwen3/)
- [DeepSeek-R1 — GitHub, deepseek-ai](https://github.com/deepseek-ai/deepseek-r1)
- [DeepSeek-R1 and exploring DeepSeek-R1-Distill-Llama-8B — Simon Willison](https://simonwillison.net/2025/Jan/20/deepseek-r1/)
- [Llama 3.3 Community License — Meta](https://github.com/meta-llama/llama-models/blob/main/models/llama3_3/LICENSE)
- [Llama 3.3 Acceptable Use Policy — Meta](https://www.llama.com/llama3_3/use-policy/)

[^qwen]: Qwen2.5 and Qwen3's open-weighted dense and MoE checkpoints are released under Apache 2.0; see the Qwen3 GitHub repo and blog post above.
[^gptoss]: gpt-oss-120b and gpt-oss-20b ship under Apache 2.0 per OpenAI's own GitHub LICENSE file and model card, both linked above.
[^dsr1]: DeepSeek-R1's own weights are MIT-licensed; the officially released distills sit on Qwen2.5 (Apache 2.0) or Llama 3.1 (Llama Community License) bases, and community discussion has flagged the Llama-based distills' resulting license stack as unresolved rather than settled — see the Simon Willison writeup above.
[^llama]: The Llama 3.3 Community License requires "Built with Llama" attribution, requires "Llama" to appear in the name of any derivative model that is distributed, and does not grant rights for the multimodal variants to individuals or companies domiciled in the EU — see Meta's LICENSE and Acceptable Use Policy above.
[^spark]: DGX Spark specs (GB10 Superchip, 128GB unified LPDDR5x, up to 1 PFLOP sparse FP4, ~200B-parameter single-unit / ~405B-parameter two-unit inference ceiling) per NVIDIA's product page and independent reviews (LMSYS, ServeTheHome), linked above.
