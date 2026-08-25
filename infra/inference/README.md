# Off-cluster inference — the campus "Sparks" vLLM

**Status: deferred by decision, and not reachable from the cluster today.**

The benchmark harness is designed to call campus-hosted vLLM hardware in addition
to cloud providers. That route is **not open**, and the reason is worth stating
plainly so nobody "fixes" it by guessing:

The tenant's egress policy grants `:443` to the internet and nothing else. Sparks
needs its own address and port, and those were never pinned down — is it on the
campus LAN or the tailnet? which port does the OpenAI-compatible listener use?
Writing a placeholder CIDR would have been *inventing* a security boundary rather
than implementing one, so the placeholder is a fully-specified comment instead.

## Turning it on

Two changes, in either order:

**1. The egress route** — in `platform-infra`, append one block per namespace to
`platform-services/ida-llm-egress/netpol.yaml`. That file's header carries the
exact YAML and the three traps:

- use a `/32`, not the enclosing subnet — a block no narrower than the existing
  `:443` rule buys nothing;
- if the port turns out to be **443**, the block is redundant and implies a fence
  that is not there (vLLM defaults to `:8000`, which is why this is a real gap);
- if Sparks sits on the node LAN or the tailnet, the inert-`except` caveat in that
  header applies — the block documents intent before it enforces, and only becomes
  real with Cilium `policyCIDRMatchMode: nodes` plus Host Firewall.

**2. The app side** — set `SPARKS_BASE_URL` in
`.devops/chart/base/configmap.yaml` (or per-overlay), seed `SPARKS_API_KEY` at
`secret/tenants/ida-llm/<env>/app`, and replace the `PLACEHOLDER-...` model name
in [`models.yaml`](../../models.yaml) with the real served model id.

Until then, selecting the `sparks-local` model **fails fast** with a clear message
rather than hanging until a dropped connection times out. That is deliberate — the
`base_url_env` key is present and empty rather than absent for exactly this reason.

## What lives here

vLLM launch configuration, served-model manifests, and the notes for whoever
operates the hardware. Deployed by hand — it is not part of the cluster's GitOps.
