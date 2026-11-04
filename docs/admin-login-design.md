# Admin login — design proposal

**Status:** proposal, awaiting human decision. Nothing in this document is built.

## 1. Goal

Today the site has one audience: anonymous, read-only visitors of the public
benchmark (`ida-llm.capstone.uamishub.com`). We want a second, much smaller
audience:

- **Admin** — signs in via SSO, holds an admin role, can trigger benchmark runs
  (spends real provider money) and use admin-only features.
- **Public** — everyone else, unauthenticated, read-only. Unchanged.

This replaces the shared-token gate that was scoped in #48 and then dropped —
a static bearer token has no identity behind it, so "who ran this and spent
this money" was always a guess. SSO gives a real person's identity instead.

**Framing:** admin is a small privileged surface bolted onto a product whose
main experience is, and stays, the public read-only benchmark. Nothing here
should make the ordinary visitor experience more complicated — it should not
even be visible to them.

## 2. What's already true (why this is a wiring project, not a build)

The investigation that produced this doc found the hard part already done:

- **`services/api/ida_api/auth.py` is real and ready for this.** It already
  defines roles (`reader`, `runner`, `author`), a `Principal` dependency
  (`current_principal`) that every protected route depends on, and an explicit
  seam for this exact moment — the module docstring says platform SSO/OIDC
  "validates its token here, in this file, and nowhere else." Adding a mode is
  an edit to one file plus a mode name, not a sweep through route handlers.
- **SSO already exists for this org.** Dev and staging sit behind Traefik
  `forwardAuth` → a shared `oauth2-proxy` → Dex, with a GitHub connector
  org-gated to `UA-MIS`. It forwards `X-Auth-Request-User` /
  `-Email` / `-Groups` headers to the app.
- **There's a working precedent in the same monorepo.** `apps/agile` (the
  sprint board) already does its own tenant-app OIDC: a dedicated Dex
  `staticClient`, authorization-code + PKCE, ID-token verification via JWKS,
  and a `groups` claim checked against a required group
  (`UA-MIS:ida-llm`-shaped). Its test suite even anticipates a
  `<team>-admins`-style group name as a near-match that must be *rejected*
  (`hasRequiredGroup(['UA-MIS:ida-llm-admins'], 'UA-MIS:ida-llm') === false`) —
  i.e., the pattern generalizes cleanly to an admin sub-group.

So the question is not "how do we build login" — it's "which of the wiring
options gets an identity from the sign-in event to `current_principal`."

## 3. The prerequisite every option has to solve

**The API has no public Ingress.** Only the frontend (and, prod-only, the
agile board) are routed; `services/api/ida_api/app.py`'s `POST /runs` is
reached only by server-side calls the Next.js frontend makes in-cluster. That
is deliberate containment for run-execution cost (see
`docs/sensitive-material.md` §6) and it stays true no matter which option
below is chosen.

Consequence: **whoever signs in does so at the frontend**, and the frontend
has to relay that identity to the API's `current_principal` on every
server-side call it makes. Two ways to do that:

- **(a) Forwarded header** — the frontend, after establishing its own admin
  session, adds an internal header (e.g. `X-Ida-Admin: <subject>`, only ever
  set by the frontend's own trusted in-cluster call, never accepted from a
  browser) on requests it proxies to the API. `current_principal` reads it,
  the same way it already reads `Authorization: Bearer` today.
- **(b) The API gets its own ingress** and validates the identity itself
  (its own OIDC client, or trusts a forwardAuth header directly). More
  surface, more to secure, and cuts against "the API is internal by design"
  (`ingress.yaml`'s own comment). Not recommended unless a future need
  requires the API to be called from outside the frontend.

All three options in §4 use (a). It is the smaller, more contained change and
matches how the codebase already talks about the API (internal-only, reached
through the frontend).

## 4. Three wiring options

### Option A — config admin-email allowlist + forwarded header

The frontend trusts an upstream `X-Auth-Request-Email` header (already
forwarded by the existing non-prod `oauth2-proxy`), checks it against a
config list of admin emails (env var or small config file), and if it
matches, relays an internal admin header to the API.

| | |
|---|---|
| **Work** | Smallest — a list + a comparison, no new OIDC client. |
| **Pro** | Fast to ship; no new Dex config; reuses headers that already exist non-prod. |
| **Con** | **Prod has no forwardAuth at all** (see §5) — this header simply does not exist in prod, so it cannot gate the one environment where gating matters. Also: an email allowlist is a second, parallel admin list to keep in sync by hand (compare to a GitHub team, which the org already manages) — every new admin is a redeploy. |
| **Verdict** | Rejected as the primary path — see §6 for why prod is the case that matters. |

### Option B — reuse the existing Dex group claim (`X-Auth-Request-Groups`)

The existing shared oauth2-proxy/Dex already emits a `Groups` header for
signed-in users. Check that header for a required admin group and relay it
the same way as Option A.

| | |
|---|---|
| **Work** | Small — no new Dex client, just a header check + group-name decision. |
| **Pro** | Reuses infrastructure that already exists for dev/staging; near-zero new moving parts. |
| **Con** | **Non-prod only, same as Option A** — the platform's `templatePatch` that attaches this forwardAuth applies "only when `env != prod`" by explicit design (see `.devops/chart/base/ingress.yaml` and `.devops/README.md`, both of which document this as deliberate, not an oversight). Prod is public *on purpose* for its results view, but that same absence of forwardAuth means there is no group header to check there either. |
| **Verdict** | Rejected for the same reason as A: cannot cover prod, which is the one environment that's actually public and actually needs an admin gate. |

### Option C — dedicated Dex staticClient for ida-llm (the apps/agile pattern) — **recommended**

Give `ida-llm` its own OIDC client in Dex (a second `staticClient`, alongside
`apps/agile`'s), and have the Next.js frontend run its own
authorization-code + PKCE flow against it — essentially the same shape as
`apps/agile/src/lib/auth/providers/oidc.ts`, ported to the frontend, checking
the `groups` claim for an admin group instead of general team membership.

| | |
|---|---|
| **Work** | Largest of the three — a new Dex `staticClient` (platform-infra PR), a client secret in Vault, a login/callback route pair in the frontend, session handling, and the internal-header relay to the API. |
| **Pro** | **Works in every environment, including prod**, because it does not depend on the platform's non-prod-only forwardAuth at all — it's the app's own auth, self-contained, the same way `apps/agile` already runs its own OIDC independent of that forwardAuth. Has a working, tested precedent in this exact monorepo to copy from (PKCE, JWKS verification, groups-claim check, the near-match test discipline). Doesn't add a second identity source to keep in sync (Option A's email list) — the source of truth stays "GitHub org team," which UA-MIS already manages. |
| **Con** | More to build and more to review — a new OIDC client is a new platform-infra artifact, a new secret, and new frontend code, all of which sit on the boundary the security lens should look at (T2 review floor, `auth`-touching). |
| **Verdict** | **Recommended.** See §6. |

## 5. Why B (and A) can't cover the environment that matters

Dev and staging sit behind the platform's shared `forwardAuth` — but **prod is
deliberately public.** The platform's env `ApplicationSet` applies that
forwardAuth middleware only when `env != prod` (`.devops/chart/base/ingress.yaml`,
`.devops/components.yaml`, `.devops/README.md` all say this explicitly, in
three independent places, as a considered decision — prod carries the public
results view on purpose, per `docs/sensitive-material.md` §1: "a public
benchmark that nobody can read is not a benchmark.")

So options A and B, which both lean on that forwardAuth's headers, can gate
admin access in dev/staging — precisely the two environments where gating
barely matters, because nobody's spending real money there — and gate nothing
in prod, the one environment where a `POST /runs` actually costs a provider
bill. An admin gate that only works where the risk is lowest isn't the
control we're building.

## 6. Recommendation: Option C

**Reasoning, restated plainly:**

1. **Prod is the case that matters.** It's the public, unauthenticated
   environment where an admin gate has a real job to do (gating spend). A and
   B structurally cannot reach it.
2. **Precedent exists and is proven.** `apps/agile` already runs exactly this
   pattern — same Dex instance, same GitHub connector, same PKCE flow, same
   groups-claim check — with a live, verified client (`teamNameField: slug`,
   `orgs: [UA-MIS]`, group shape `UA-MIS:<team-slug>`, confidential client,
   S256 PKCE). Porting it to a second app is known work, not exploration.
3. **Self-contained.** It doesn't depend on a platform behavior (non-prod
   forwardAuth) that was deliberately scoped to exclude the one environment
   we need. The app owns its own auth, the same way `apps/agile` does.

## 7. Admin designation

A GitHub team, e.g. **`UA-MIS/ida-llm-admins`**, checked against the OIDC
`groups` claim the same way `apps/agile` checks `UA-MIS:ida-llm` — Dex emits
team membership as `UA-MIS:<team-slug>`, so the required-group check becomes
`UA-MIS:ida-llm-admins`. This keeps the source of truth in GitHub, where the
org already manages team membership, rather than a second list embedded in
config (Option A's failure mode). `apps/agile`'s own test suite already
treats an `-admins`-suffixed group as a distinct, non-matching group from the
base team — the naming convention this needs already has a guard rail against
being confused with plain `ida-llm` membership.

**Open decision:** is `UA-MIS/ida-llm-admins` the right team name, or does an
existing team already serve this purpose?

## 8. What admin unlocks

The gateable surface is thin today — worth stating plainly so "admin unlocks
features" doesn't imply more exists than actually does:

- **`POST /runs`** (role `runner`) — spends money. **There is no run-trigger
  UI yet** — today this is a curl snippet in the docs. So "admin can trigger
  runs" requires building a **new UI feature** (a run-trigger page/panel),
  not just flipping a role check. This is the headline admin feature.
- **`GET /tasks/{id}?include_targets=true`** (role `author`) — reveals gold
  answers. Already role-gated in code; the open question is only *policy*:
  should admin sign-in also grant `author`, i.e. should signed-in admins be
  able to see answer keys through the UI? (Today nobody holds `author` in any
  deployed mode — see §"Residual question" in `docs/sensitive-material.md`.)
- **Everything else is out of scope as written.** No re-grade, sweep-trigger,
  or config-change HTTP endpoints exist today — calibration and sweeps are
  CLI-only, run by whoever has cluster/CI access, not through the web app.
  Any further admin feature ("re-run this sample," "adjust a sweep") means
  **new endpoints**, which is its own scope to plan separately, not implied
  by this login work.

## 9. Phased implementation plan

1. **Dex client + secret.** platform-infra PR adding a `staticClient` for
   `ida-llm` (mirroring `apps/agile`'s: confidential client,
   `client_secret_basic`/`_post`, S256 PKCE, redirect URI on the ida-llm
   frontend). Client secret minted into Vault
   (`tenants/ida-llm/<env>/app`), synced via ExternalSecret the same way
   `OPENAI_API_KEY` already is.
2. **Frontend OIDC + session + role check.** Port the `apps/agile` OIDC
   provider shape (`start`/`callback`/`revalidate`, PKCE, JWKS verification,
   `groups` claim check against `UA-MIS/ida-llm-admins`) into the ida-llm
   frontend as its own login/callback route pair and session cookie. On
   server-side calls to the API, an authenticated admin session causes the
   frontend to add the internal identity header (§3a); `current_principal`
   in `ida_api/auth.py` gains a new mode (or an additional header-based path
   alongside `token`) that resolves that header to a principal holding
   `reader` + `runner` (+ `author`, pending the §8 decision).
3. **Run-trigger UI.** A new admin-only page/panel that calls `POST /runs`
   with the parameters the curl snippet currently takes by hand — the actual
   payoff feature, and the first thing that makes "admin can trigger runs"
   true in the product rather than only in the API.
4. **Any admin extras** (deferred): re-grade/sweep controls, config views —
   each is new API surface and gets scoped and reviewed on its own once
   there's a concrete need, per §8's "further admin features = new
   endpoints" note.

Each phase should ship and verify independently — the Dex client and session
plumbing are worth landing and confirming (a real sign-in round trip) before
building the run-trigger UI on top of them.

## 10. Open decisions for the human

1. **Which option** — confirm Option C (recommended), or a different call.
2. **The GitHub team name** — `UA-MIS/ida-llm-admins`, or reuse an existing
   team?
3. **Does admin sign-in also grant `author`** (gold-answer visibility), or
   stay `reader` + `runner` only, with answer-key access handled separately
   if ever?
4. **Which admin features ship first** beyond the run-trigger UI — is
   phase 3 (run-trigger UI) sufficient for now, with phase 4 deferred
   entirely until a concrete need appears?

---

*Written by the developer teammate from the completed auth investigation,
2026-08-31 overnight run. No auth code was written as part of producing this
document — see `services/api/ida_api/auth.py`, `services/api/ida_api/app.py`,
and `apps/agile/src/lib/auth/providers/oidc.ts` /
`apps/agile/tests/oidc-auth.test.ts` for the code this proposal is grounded
in.*
