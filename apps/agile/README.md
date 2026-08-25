# ida-agile

An Azure-DevOps-style sprint and story board, wired into the GitHub repo that
holds the code.

Work items, a kanban board with drag-and-drop, sprints with capacity, assignees
from a GitHub team, branches created from a story, commits and pull requests
flowing back onto the board — plus a **full REST API** so the board can be driven
by a script or an agent, not only by hand.

> **Access is restricted to members of a configured GitHub team.**
> Tenant apps on this platform are public by default, so this app authenticates
> and authorizes on its own — Dex OIDC, gated on the `groups` claim. See
> [Authentication](#authentication).

**Nothing about a particular org, team or repo is hardcoded.** A second instance
for another class is a different set of environment variables and no code change —
see [Deploying another instance](#deploying-another-instance).

---

## Contents

- [Stack](#stack) · [Configuration](#configuration) · [Registering the Dex client](#registering-the-dex-client)
- [Authentication](#authentication) · [API](#api)
- [Homepage](#homepage-living-readme) · [Sprints](#sprints) · [Dependencies and the Ready queue](#dependencies-and-the-ready-queue)
- [Git integration](#git-integration) · [Webhooks](#webhooks) · [Multiple repos](#multiple-repos)
- [State, durability and backup](#state-durability-and-backup)
- [Deploying another instance](#deploying-another-instance)
- [Deployment on this platform](#deployment-on-this-platform)
- [Local development](#local-development) · [Tests](#tests)

---

## Stack

| | |
|---|---|
| Framework | Next.js 16 (App Router) + React 19, TypeScript 6 |
| Database | PostgreSQL, in its own schema (default `agile`) |
| Auth | Dex OIDC (PKCE) gated on the `groups` claim; AES-256-GCM encrypted cookie; board tokens + GitHub-token passthrough for the API |
| Files | Any S3-compatible object store (MinIO) — optional |
| Tests | Vitest — unit + integration against real Postgres |

Dependencies are deliberately lean: `pg`, `zod`, `jose`, `marked`,
`sanitize-html`. No ORM, no auth framework, no drag-and-drop library, no AWS SDK
(SigV4 is signed directly).

---

## Configuration

Everything is an environment variable. Only four are required.

### Required

| Variable | Secret | Description |
|---|---|---|
| `DATABASE_URL` | yes | PostgreSQL DSN. **Must be PostgreSQL**, not MySQL. |
| `OIDC_CLIENT_ID` | no | Dex static client id (or `GITHUB_CLIENT_ID` when `AUTH_PROVIDER=github`). |
| `OIDC_CLIENT_SECRET` | **yes** | Dex client secret (or `GITHUB_CLIENT_SECRET`). |
| `SESSION_SECRET` | **yes** | ≥32 chars. `openssl rand -base64 48`. Rotating it signs everyone out and invalidates API tokens' stored GitHub credentials. |

`APP_URL` is required in production (it builds the OAuth callback URL and the
links in PR backlink comments): set it to the exact public origin, e.g.
`https://ida-agile.capstone.uamishub.com`.

### Web sign-in (Dex OIDC)

| Variable | Default | Description |
|---|---|---|
| `AUTH_PROVIDER` | `oidc` when `OIDC_ISSUER` is set, else `github` | Identity provider. |
| `OIDC_ISSUER` | — | e.g. `https://id.capstone.uamishub.com` |
| `OIDC_CLIENT_ID` | — | Dex static client id. |
| `OIDC_CLIENT_SECRET` | — | **secret** — Dex advertises only `client_secret_basic`/`_post`, so a confidential client is required even with PKCE. |
| `OIDC_REDIRECT_URI` | `<APP_URL>/api/auth/callback` | Must match the Dex client exactly. |
| `OIDC_SCOPES` | `openid profile email groups` | |
| `REQUIRED_GROUP` | `<GITHUB_ORG>:<GITHUB_TEAM>` | The group that grants access, e.g. `UA-MIS:ida-llm`. |

### Identity — who this board is for

| Variable | Default | Description |
|---|---|---|
| `GITHUB_ORG` | `UA-MIS` | Org that owns the team and repos. |
| `GITHUB_TEAM` | `ida-llm` | **Membership of this team is the authorization rule.** |
| `GITHUB_REPOS` | `<org>/<team>` | Comma-separated repos for PR links and branches. First is primary. `GITHUB_REPO` (singular) also accepted. |
| `BOARD_INSTANCE` | `<org>/<team>` | Scopes every row. Change only to run two boards on one database. |

### Branding

| Variable | Default | Description |
|---|---|---|
| `BOARD_TITLE` | `Agile Board` | Shown in the header and browser title. |
| `BOARD_ACCENT` | `#9e1b32` | Accent colour, `#rrggbb`. Invalid values fall back to the default. |

### Automation

| Variable | Default | Description |
|---|---|---|
| `AUTO_BRANCH` | `true` | Offer "Start work" branch creation. |
| `BRANCH_PATTERN` | `{type}/{id}-{slug}` | Placeholders: `{type} {id} {slug} {title} {assignee}`. |
| `AUTO_PROGRESS` | `true` | Master switch for git-driven state changes. |
| `AUTO_PROGRESS_ON_COMMIT` | `true` | First commit moves `New` → `Active`. |
| `AUTO_PROGRESS_ON_PR_OPEN` | `true` | PR opened ensures `Active`. |
| `AUTO_PROGRESS_ON_PR_MERGE` | `true` | PR merged moves to `Resolved`. |
| `PR_BACKLINK_COMMENTS` | `true` | Maintain one backlink comment per linked PR. |
| `PR_COMMIT_STATUS` | `false` | Also publish a commit status showing the linked item. |

### Dependencies and trunk-based signals

| Variable | Default | Description |
|---|---|---|
| `ALLOW_DEPENDENCY_OVERRIDE` | `true` | Allow starting blocked work with a logged reason. |
| `STALE_BRANCH_DAYS` | `5` | Badge a branch open longer than this. `0` disables. |
| `STALE_BRANCH_BEHIND` | `20` | Badge a branch this far behind the default branch. `0` disables. |

### Webhooks and polling

| Variable | Default | Description |
|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | — | HMAC secret. **Unset means webhooks are disabled**; the app falls back to polling. |
| `GITHUB_POLL_TOKEN` | — | **Legacy fallback.** A static PAT. Still honoured, but prefer the GitHub App below — an unrotated static token is how this board once ran for weeks against a placeholder value. |
| `POLL_INTERVAL_SECONDS` | `300` | Background sweep interval. `0` disables. |
| `ONVIEW_REFRESH_SECONDS` | `120` | Throttle for refreshing an item when someone opens it. |

### The board's own GitHub identity (GitHub App)

Under Dex the signed-in session carries **no GitHub token**, so the board needs
an identity of its own to call the API at all. These three variables give it
one. They point at a GitHub App **installed once, org-wide** — the same three
values serve every board this platform provisions, so onboarding a new team is a
copy, not a new App registration.

| Variable | Default | Description |
|---|---|---|
| `GITHUB_APP_ID` | — | The App's numeric id. Not a secret. |
| `GITHUB_APP_INSTALLATION_ID` | — | The App's installation on your org. Not a secret. |
| `GITHUB_APP_PRIVATE_KEY` | — | The App's PEM private key. **The only secret of the three.** |

**Required App permissions** — the minimum for the three features that need one:

| Permission | Level | Needed for |
|---|---|---|
| `members` | read | the assignee picker (team roster) |
| `contents` | write | "Start work" branch creation |
| `pull_requests` | write | PR backlink comments |
| `metadata` | read | implied by the above |

**The token is minted, never stored.** An installation access token lives about
one hour. Storing one in a Secret would give you a board that works for an hour
after each deploy and then quietly stops — the exact failure mode this replaces.
The durable secret is the private key; the app mints a token on demand, holds it
in memory, renews it a few minutes before expiry, and shares a single mint
across concurrent requests. Losing the cache on restart costs one API call.

**⚠ The private key is multi-line, which is the fragile part.** A PEM carried
through Vault → External Secrets → container env is the classic place for a key
to arrive mangled, producing an opaque 401 on every GitHub call. The app
therefore accepts **all four** shapes it might arrive in — real newlines,
`\n`-escaped newlines, CRLF escapes, and base64 of the whole PEM — and treats an
unparsable key as *not configured* rather than configured-and-broken.
**Seed it base64-encoded**; that is the shape that survives every pipeline:

```bash
vault kv patch -method=patch -mount=secret tenants/<team>/<env>/agile \
  GITHUB_APP_ID=<app-id> \
  GITHUB_APP_INSTALLATION_ID=<installation-id> \
  GITHUB_APP_PRIVATE_KEY="$(base64 -w0 < app.private-key.pem)"
```

Use `kv patch`, **not** `kv put` — `put` replaces the whole path and would take
`SESSION_SECRET` and `OIDC_CLIENT_SECRET` with it. Verify by reading the value
back **inside the pod**, not by trusting the write.

**How to tell which credential a board is actually using.** On boot the pod logs
exactly one of:

```
[startup] GitHub credential: GitHub App (app id 4097147, installation 141394298)
[startup] GitHub credential: static GITHUB_POLL_TOKEN (legacy fallback; the GitHub App is preferred)
[startup] GitHub credential: NONE — the assignee picker, branch creation and PR backlink comments are inert. ...
```

That line exists because the failure it diagnoses was **silent**: a placeholder
token produced empty pickers, no error, and nothing in the log. Check it first.

### Object storage (attachments — optional)

Attachments are offered only when all four are set. `MINIO_*` names match this
repo's existing convention; `S3_*` are accepted as aliases.

| Variable | Description |
|---|---|
| `MINIO_ENDPOINT` / `S3_ENDPOINT` | Host (or full URL). |
| `MINIO_PORT`, `MINIO_USE_SSL` | Used to build the URL when only a host is given. |
| `MINIO_BUCKET` / `S3_BUCKET` | Bucket name. |
| `MINIO_ACCESS_KEY` / `S3_ACCESS_KEY_ID` | |
| `MINIO_SECRET_KEY` / `S3_SECRET_ACCESS_KEY` | **secret** |
| `MAX_UPLOAD_BYTES` | Default 25 MB. Keep under the ingress body limit. |

### Other

| Variable | Default |
|---|---|
| `AGILE_DB_SCHEMA` | `agile` |
| `HOME_TEMPLATE` / `HOME_TEMPLATE_PATH` | built-in starter text |
| `PGPOOL_MAX` | `10` |
| `RATE_LIMIT_BURST` / `RATE_LIMIT_PER_SECOND` | `240` / `8` |

---

## Registering the Dex client

A devops owner adds the client in `platform-infra`. Three coordinated edits, per
`platform-services/dex/README.md`:

1. **`platform-services/dex/configmap.yaml`** — a new `staticClients` entry:

   ```yaml
     - id: ida-agile
       name: IDA Agile
       secretEnv: IDA_AGILE_CLIENT_SECRET
       redirectURIs:
         - https://ida-agile.capstone.uamishub.com/api/auth/callback
   ```

2. **`platform-services/dex/deployment.yaml`** — an `env:` entry sourcing
   `IDA_AGILE_CLIENT_SECRET` from the `dex-github` secret (mark `optional: true`
   until the key is sealed, so Dex keeps booting).

3. **Re-seal** `platform-services/dex/sealedsecret.yaml` with the new key, seal
   the identical value for this app, then
   `kubectl -n dex rollout restart deploy/dex` — a ConfigMap change does **not**
   restart Dex on its own.

What this app needs:

| | |
|---|---|
| Redirect URI | `https://ida-agile.capstone.uamishub.com/api/auth/callback` (exact) |
| Client type | **confidential** — Dex advertises only `client_secret_basic`/`_post`; `none` is not offered, so PKCE alone is not enough |
| PKCE | S256, used by this app |
| Scopes | `openid profile email groups` |
| Wildcards | not supported by Dex — one redirect URI per instance |

### Fallback: direct GitHub OAuth

With `AUTH_PROVIDER=github`, register an OAuth app in the org with callback
`<APP_URL>/api/auth/callback` and scopes `read:user read:org`, and set
`GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`.

> ⚠️ Branch creation and PR comments act as the signed-in user, so that user
> needs push access to the repo. Those failures degrade gracefully — they never
> block a state change.

---

## Authentication

**Web sign-in is OIDC against Dex** (authorization code + PKCE). Dex is the
default rather than direct GitHub OAuth because a per-instance GitHub OAuth app
cannot be provisioned zero-touch: GitHub allows one callback URL per app, so a
wizard creating twelve team boards would need twelve manual app registrations.
Dex already federates the GitHub org and is what Harbor/ArgoCD/Grafana use.

The provider is behind one interface (`src/lib/auth/providers/`), so swapping it
is a config change (`AUTH_PROVIDER`), not a rewrite. `github` remains as a
working fallback implementation.

### How authorization works

Dex's GitHub connector is configured with `teamNameField: slug` and
`orgs: [UA-MIS]`, so the `groups` claim contains entries of the form
**`UA-MIS:<team-slug>`** — e.g. `UA-MIS:ida-llm`. Access is granted when the
claim contains `REQUIRED_GROUP` (default `<GITHUB_ORG>:<GITHUB_TEAM>`).

> Verified against the live Dex at `https://id.capstone.uamishub.com`. The bare
> org (`UA-MIS`) is **never** emitted as a group, so "any org member" cannot be
> expressed as a group — which is exactly why the check is on `org:team`.

The ID token is verified properly: signature against Dex's JWKS, plus `issuer`
and `audience`. `groups` is requested as an essential ID-token claim (the same
approach ArgoCD uses against this Dex), with `/userinfo` as a fallback.

### Sessions

The session is an **AES-256-GCM encrypted**, HTTP-only, `SameSite=Lax` cookie
(7-day TTL). Encryption rather than signing because on the GitHub path the
cookie carries a GitHub token.

Revalidation differs by provider, and the difference is deliberate rather than
hidden:

| Provider | Freshness of authorization |
|---|---|
| `github` | Membership re-read from GitHub every ~10 min, so removal revokes access within ~10 min. |
| `oidc` | The groups claim is asserted at sign-in. It is re-checked against `REQUIRED_GROUP` on every request (so changing the required group takes effect immediately), but a user removed from the team **upstream** keeps access until their session expires. **Session TTL is the freshness bound.** Shorten `SESSION_TTL` expectations accordingly, or sign the user out. |

Failure policy on the GitHub path: a provable denial revokes; an inconclusive
lookup (5xx, network) keeps the session, because a GitHub outage must not sign
out the whole team.

### ⚠️ What Dex sign-in means for GitHub features

Under OIDC the board never receives a GitHub token — that is the point, since a
team no longer registers a GitHub OAuth app. Every GitHub-touching path
therefore states where its credential comes from:

**Credential precedence, in order.** Both reads and actions resolve the same
way; the difference is that an action records *which* credential acted.

| # | Source | When | Attribution |
|---|---|---|---|
| 1 | **The acting user's own token** | GitHub-backed session, or a GitHub token sent to the API | The action is genuinely theirs. |
| 2 | **The board's GitHub App installation token** | `GITHUB_APP_*` configured. **The default for a platform-provisioned board, and what makes it work under Dex at all.** | History records *"performed with the board's GitHub credential"*. |
| 3 | **`GITHUB_POLL_TOKEN`** | Only if set, and only when the App is absent or momentarily unmintable | Same note as above. |
| 4 | **Nothing** | none configured | Fails **loudly**, naming `GITHUB_APP_ID` and the rest. |

| Kind of call | Behaviour under Dex |
|---|---|
| **Read** — assignee picker, PR picker, reading a PR to link, reconciliation | Works via the App. Without any credential, degrades to an empty list **with a note naming the variables to set**. |
| **Action** — create a branch, comment on a PR, set a commit status | Works via the App, and says so in item history — attribution is never implied falsely. |
| Neither available | Never a silent no-op, and never a blocked state transition: the state change is applied first and is **not** rolled back by a GitHub failure. |

**So: configure the GitHub App on any Dex-based deployment** (see *The board's
own GitHub identity* above). The board is fully usable without it — items,
board, sprints, dependencies, Ready queue and the whole API are unaffected — but
the three GitHub-integration features will report themselves unavailable.

> **The failure this replaces.** `GITHUB_POLL_TOKEN` was seeded as a literal
> placeholder. Nothing validated it, so the assignee picker was simply empty,
> "Start work" would have failed the first time anyone pressed it, and no log
> line said why. Step 2 above takes the static token off the critical path; the
> startup log line takes away the silence.

### Session revalidation

Each session is revalidated by **the provider that issued it**, so flipping
`AUTH_PROVIDER` does not invalidate sessions minted by the previous one:

| Provider | Rule | Blind spot |
|---|---|---|
| `oidc` | The `groups` claim in the session is re-checked against `REQUIRED_GROUP` on every request. Changing the required group takes effect immediately, and a session lacking the group is denied at once. | An upstream removal from the GitHub team is not visible until the session expires — the claim is only refreshed by a new authorization round trip. **Session TTL (7 days) is the freshness bound.** |
| `github` | Membership re-read from GitHub at most every ~10 minutes. | None; removal revokes within ~10 minutes. |

A verdict of "cannot tell" (for example a GitHub outage) keeps the session — an
inconclusive check must never sign out the team — while a provable denial
revokes immediately.

### API authentication

Two credentials, same authorization rule — full detail in [`docs/api.md`](docs/api.md):

1. **Board-issued tokens** — created in the UI, shown once, stored only as a
   SHA-256 hash, revocable, and auto-revoked if the owner leaves the team.
   Recommended for CI and anything long-lived.
2. **GitHub token passthrough** — `Authorization: Bearer $(gh auth token)`.
   Validated against GitHub, authorized by the same team check. The token is
   **never persisted**; only the derived identity is cached, keyed by a hash of
   the token, for five minutes. Needs the `read:org` scope.

   *Tradeoff, stated plainly:* a GitHub token is a far broader credential than a
   board token. It is the right choice for ad-hoc use from your own machine, and
   the wrong choice for anything shared or long-lived.

Both are distinguishable in item history (`via API` vs `via API (github token)`).

**The one exempt route** is `POST /api/webhooks/github`: GitHub cannot sign in,
so it is authenticated by HMAC signature instead. The exemption is scoped to
exactly that path.

## API

Full reference with copy-paste examples: **[`docs/api.md`](docs/api.md)**.
Machine-readable spec: `GET /api/v1/openapi.json`.

The web UI consumes the same `/api/v1` endpoints an external client does — there
is no privileged internal path, so the two cannot drift apart. Highlights:

- Bulk create (`{"items":[...]}`, up to 100) for seeding a plan in one call
- `Idempotency-Key` header so a retried create never duplicates
- Consistent JSON errors; validation failures name the offending field
- Everything a token does is attributed to its human owner in item history

---

## Git integration

Once an item has a branch, the board tracks it:

| Event | Effect |
|---|---|
| Commit pushed to the item's branch | Recorded on the item; first commit moves `New` → `Active` |
| Commit message or PR text contains `AB#42` | Attaches to item 42 from *any* branch |
| PR opened from the item's branch | Auto-linked; item ensured `Active` |
| PR merged | Item → `Resolved` (**never** `Closed` — accepting stays human) |
| PR closed unmerged | No state change; item shows a warning |
| Checks complete | PR check state updated on the card |

Every automatic move is written to history as *"moved by GitHub (PR #123
merged)"* — nothing moves silently.

**Backlinks into GitHub.** When a PR is linked, the app maintains **one**
comment on that PR pointing at the work item (type, state, assignee, points, and
a direct link). It finds and edits its own prior comment rather than posting a
new one per event. Optionally (`PR_COMMIT_STATUS=true`) it also publishes an
`ida-agile/work-item` commit status, making "is this attached to a story?"
visible in the PR checks list.

Commenting acts as the linking user when they have a token of their own, and as
the board's GitHub App otherwise — a webhook-driven event has **no user in
context**, so the App is what lets those comment at all. Either way the comment
is a courtesy: if it cannot be posted, auto-linking still works and only the
comment is skipped, never the link.

---

## Webhooks

Webhooks are the fast path. Configure in the repo → Settings → Webhooks:

- **Payload URL**: `<APP_URL>/api/webhooks/github`
- **Content type**: `application/json`
- **Secret**: the same value as `GITHUB_WEBHOOK_SECRET`
- **Events**: Pushes, Pull requests, Check suites, Check runs

The receiver verifies `X-Hub-Signature-256` (HMAC-SHA256, constant-time) before
parsing anything, and de-duplicates by `X-GitHub-Delivery` so a redelivery cannot
re-run progression rules.

**Without webhooks the board still works.** Reconciliation degrades in two tiers:

1. **On-view** (zero config) — opening an item refreshes its branch and PRs using
   the viewing member's own GitHub token, throttled per item.
2. **Background sweep** — set `GITHUB_POLL_TOKEN` and `POLL_INTERVAL_SECONDS` to
   reconcile unattended.

So an unconfigured deployment converges when someone looks, rather than instantly.

---

## Homepage (living README)

`/` is the landing route: a project 101 in two halves.

1. **A narrative the team writes** — markdown, edited in the browser by any
   authorized member, stored in Postgres and rendered through the same
   sanitising pipeline as work-item descriptions. **Every save archives the text
   it replaced**, with who changed it and when, so "when did our goal change?"
   stays answerable a semester later. It is writable via the API
   (`PUT /api/v1/pages/home`), so a Claude session can seed it.
2. **A state strip nobody maintains** — current sprint with days remaining,
   counts by state, points done vs remaining, how many items are Ready, how many
   are blocked, recently merged PRs and recently finished items. All derived from
   board data, so it cannot drift the way a status paragraph does.

A fresh instance shows **starter content with an "edit this" prompt**, never a
blank page — every wizard-provisioned team starts here. Override the starter text
per instance with `HOME_TEMPLATE` (inline) or `HOME_TEMPLATE_PATH` (a file).

The board stays one click away and directly linkable at `/board`, so daily use
never bounces through here.

---

## Sprints

Sprints are shown as tabs across the top of the board, with dates and item counts.

**One sprint is the board-wide `current` sprint, and it is shared server-side
state** — not a per-user preference. When anyone sets it, every visitor lands on
that sprint by default. Who set it and when is recorded and shown.

Browsing and setting are deliberately different actions:

- Clicking a sprint tab changes **only your view**.
- **"Set as current sprint"** is a separate, explicitly-labelled control with a
  confirmation, so a casual click cannot reassign the team's default.

The API covers the whole lifecycle — create sprints, assign items, and advance
the current sprint — so a semester can be seeded and driven programmatically.
See the *seed a semester* example in [`docs/api.md`](docs/api.md).

---

## Dependencies and the Ready queue

Work items can declare `depends_on` edges, and **the board enforces them** so the
non-interference scheme is self-serve rather than something to read in a doc.

- **Cycles are rejected** at creation, with the loop named:
  `That dependency would create a cycle: #1 → #4 → #1.`
- **"Start work" is disabled while any dependency is unmet**, and the refusal
  names the specific blockers with links rather than just greying out.
- A dependency counts as satisfied once the blocker is `Resolved` or `Closed`.
  When the last blocker resolves, the item becomes visibly ready.
- **Override, logged** — a hard block with no escape route gets worked around
  outside the tool, so there is an explicit one. It requires a reason and is
  written to item history. Disable with `ALLOW_DEPENDENCY_OVERRIDE=false`.
- **`wave`** is a first-class field on every item, shown on each card and
  filterable — the human-readable fallback so nobody grabs Wave-2 work early even
  where dependencies are not fully encoded.

**The Ready view** (`/ready`, `GET /api/v1/ready`) lists unassigned items whose
dependencies are all satisfied — the self-serve pickup queue — alongside a
blocked list showing what everything else is waiting on.

Bulk seeding can declare the entire graph in the same call that creates the
items, using client-supplied keys. That is the primary use case, and it is
covered in [`docs/api.md`](docs/api.md).

---

## Multiple repos

The data model is repo-aware from the start, because retrofitting it would touch
every git-integration path:

- `GITHUB_REPOS` is a **list**; a single-repo tenant is the one-element case.
- A work item can carry a `repoFullName`. With one repo configured it is filled
  in automatically and the UI never shows a repo picker.
- Branch creation targets the item's repo.
- **PR linking and webhook handling are repo-scoped** — a `push`/`pull_request`
  event is routed only to items belonging to that repository, and `AB#42` in one
  repo will not attach to item 42 if that item belongs to another.

Only single-repo behaviour is exercised today; a maintainer-facing board tracking
several repos is a later instance, not a feature of this one.

---

## State, durability and backup

**Everything durable is in Postgres.** Nothing meaningful is held in memory and
nothing is written to the container filesystem — the image runs fine with a
**read-only root filesystem** (verified).

| Kind of state | Where it lives |
|---|---|
| Work items, sprints, comments, history, PR links, commits | Postgres |
| API tokens (hash only), idempotency records, webhook delivery ids | Postgres |
| Sessions | Nowhere server-side — a stateless encrypted cookie |
| Attachments | Object storage; only metadata in Postgres |
| Team/PR caches, rate-limit buckets | In memory, intentionally — all re-derivable, losing them costs nothing |

**Migrations run automatically at startup** (Next.js `instrumentation.ts`),
before the first request is served:

- A fresh pod against an **empty** database self-initialises.
- A fresh pod against an **existing** database applies only what is missing.
- Concurrent replicas are safe — the runner takes a Postgres advisory lock.
- Everything is created inside the app's own schema, so other tables in the same
  database are never touched.

*Verified by killing a running pod with `SIGKILL` mid-session: a brand-new pod
came up against the same database, all items/comments/sprints were intact, the
user was still signed in with the same cookie, and anonymous requests were still
rejected.*

**Backup** is therefore ordinary Postgres backup (the platform's Velero/MinIO
snapshots cover it) plus the object-storage bucket if attachments are used. There
is no app-specific state to capture.

---

## Deploying another instance

For a different class or team, change environment variables only:

```env
GITHUB_ORG=UA-MIS
GITHUB_TEAM=cs495-fall
GITHUB_REPOS=UA-MIS/cs495-project
BOARD_TITLE=CS495 Board
BOARD_ACCENT=#0b6bcb
APP_URL=https://cs495-agile.capstone.uamishub.com
# ...plus its own DATABASE_URL, SESSION_SECRET and OAuth app
```

Then create an OAuth app whose callback is that instance's `APP_URL`.

Two instances may share a Postgres server. Give each its own database, or its own
`AGILE_DB_SCHEMA`, or (if they must share a schema) its own `BOARD_INSTANCE` —
every user-visible row is scoped by instance key.

> This build is deliberately **single-board**: one deployment serves one team.
> The scoping column exists so a future multi-board mode is a query change rather
> than a migration, but no multi-tenancy is implemented today.

---

## Deployment on this platform

Ships as a component of the `UA-MIS/ida-llm` monorepo under `apps/agile/`.

**`.devops/components.yaml`:**

```yaml
  - name: agile
    kind: backend
    context: .                        # repo root, like every other component
    dockerfile: apps/agile/Dockerfile
    image: ida-llm-agile
    port: 8080
    path: ""                          # it gets its own host, not a path
    needsDb: true
    buildType: container
```

**Host** — `ida-agile.capstone.uamishub.com` is a single label, so it is already
covered by the Cloudflare wildcard Public Hostname and the
`*.capstone.uamishub.com` certificate: no new DNS entry and no new certificate.
It needs a **second rule on the existing `ida-llm` Ingress** (and the host added
to `tls.hosts`) — see `.devops/README.md`, which already documents this.

**Probes** — split by design:

| Probe | Path | Behaviour |
|---|---|---|
| Liveness | `/api/healthz` | Never touches the database. A DB blip must not trigger a restart storm. |
| Readiness | `/api/readyz` | 200 only when migrations are done and Postgres is reachable. |

**Container** — runs as uid `65532`, needs no writable filesystem, listens on
`8080`. No migration initContainer is required; migrations run in-process at
startup.

**Secrets to seed in Vault** at `secret/tenants/ida-llm/prod/app`:

| Variable | Value for this deployment |
|---|---|
| `OIDC_ISSUER` | `https://id.capstone.uamishub.com` |
| `OIDC_CLIENT_ID` | `ida-agile` |
| `OIDC_CLIENT_SECRET` | **secret** — same value sealed into the Dex `dex-github` secret |
| `SESSION_SECRET` | **secret** — `openssl rand -base64 48` |
| `APP_URL` | `https://ida-agile.capstone.uamishub.com` |
| `REQUIRED_GROUP` | `UA-MIS:ida-llm` (also the default) |
| `GITHUB_WEBHOOK_SECRET` | optional; enables the webhook fast path |
| `BOARD_TITLE` | `IDA Agile` |

Only `APP_SECRET` and `DATABASE_URL` are pre-wired in `base/deployments.yaml`, so
each variable above also needs an `env.valueFrom.secretKeyRef` entry.

---

## Local development

```sh
cd apps/agile
cp .env.example .env.local        # fill in the values
docker run -d --name agile-db -e POSTGRES_PASSWORD=agile -e POSTGRES_USER=agile \
  -e POSTGRES_DB=agile -p 5432:5432 postgres:17-alpine
npm install
npm run dev                       # http://localhost:3000
```

Register a second OAuth app with callback `http://localhost:3000/api/auth/callback`
and set `APP_URL=http://localhost:3000`.

Migrations run on boot; `npm run migrate` applies them manually if you prefer.

---

## Tests

```sh
npm test          # unit tests
npm run typecheck
npm run lint

# Integration tests need a database:
TEST_DATABASE_URL=postgres://agile:agile@127.0.0.1:5432/agile npm test
```

Integration tests create and drop their own schemas, so they never touch
application data.

| Suite | Covers |
|---|---|
| `auth-boundary` | **The authorization gate** — non-members, pending invites and every GitHub failure mode are denied |
| `revalidate` | Access is revoked after leaving the team; a GitHub outage signs nobody out |
| `oidc-auth` | Groups-claim authorization (exact `org:team`, no bare-org or prefix match), PKCE, GitHub-token passthrough incl. caching and non-member rejection |
| `dependencies` | Cycle detection, the readiness gate, override semantics, branch staleness |
| `deps-integration` | Gate blocks/opens against real Postgres, override logged, shared current sprint, one-call semester seeding |
| `home-page` | Starter template, edit persistence and attribution, revision history, overridable template, and that the state strip reflects real data (merged PRs count, commits do not) |
| `session` | Cookie encryption, tampering, expiry, open-redirect protection |
| `api-tokens` | Issue/verify/revoke, hash-only storage, expiry, membership-linked revocation |
| `idempotency` | Replay, conflict, per-user scoping, purge |
| `state-machine` | Every legal and illegal transition |
| `progression` | Each auto-progression rule, and the config flags that disable them |
| `webhook-signature` | Valid signatures accepted; missing, forged, wrong-secret and tampered rejected |
| `sync-engine` | Commits attach to the right item, PR events move state, moves attributed to GitHub, replays are idempotent |
| `branch-naming` | Pattern rendering and git ref-name safety |
| `db-integration` | Data layer against real Postgres — CRUD, cascades, filters, schema isolation, migration idempotency |
| `markdown` | XSS hardening of rendered markdown |
| `prs` | PR URL/shorthand parsing and `AB#123` extraction |

---

## Layout

```
apps/agile/
├── docs/api.md              the API reference (written to be machine-actionable)
├── src/
│   ├── app/
│   │   ├── api/v1/…         the REST API — the UI's only backend
│   │   ├── api/webhooks/…   GitHub receiver (signature-authenticated)
│   │   ├── api/auth/…       OAuth login/callback/logout
│   │   └── board|backlog|sprints|items/[id]|tokens|login|denied
│   ├── components/          Board, WorkItemDialog, ItemDetail, Sprints, Tokens, Shell
│   ├── lib/
│   │   ├── api/             route wrapper, errors, idempotency, rate limit, OpenAPI
│   │   ├── auth/            session, OAuth, team gate, API tokens, principal
│   │   ├── db/              pool, migrations, runner
│   │   ├── domain/          model + state machine, queries, mappers
│   │   ├── github/          API client, PR parsing, branch creation
│   │   ├── sync/            webhook verify, progression rules, engine, poller, backlinks
│   │   ├── env.ts           all configuration
│   │   └── storage.ts       S3/MinIO (SigV4, no SDK)
│   └── instrumentation.ts   migrations + background poller at startup
└── tests/
```
