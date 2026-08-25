# ida-agile

An Azure-DevOps-style sprint and story board, wired into the GitHub repo that
holds the code.

Work items, a kanban board with drag-and-drop, sprints with capacity, assignees
from a GitHub team, branches created from a story, commits and pull requests
flowing back onto the board — plus a **full REST API** so the board can be driven
by a script or an agent, not only by hand.

> **Access is restricted to members of a configured GitHub team.**
> Tenant apps on this platform are public by default, so this app performs its
> own GitHub OAuth and team-membership check. See [Authentication](#authentication).

**Nothing about a particular org, team or repo is hardcoded.** A second instance
for another class is a different set of environment variables and no code change —
see [Deploying another instance](#deploying-another-instance).

---

## Contents

- [Stack](#stack) · [Configuration](#configuration) · [GitHub OAuth app](#github-oauth-app)
- [Authentication](#authentication) · [API](#api)
- [Git integration](#git-integration) · [Webhooks](#webhooks)
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
| Auth | GitHub OAuth + team membership; AES-256-GCM encrypted cookie; board-issued API tokens |
| Files | Any S3-compatible object store (MinIO) — optional |
| Tests | Vitest — unit + integration against real Postgres |

Dependencies are deliberately lean: `pg`, `zod`, `marked`, `sanitize-html`. No
ORM, no auth framework, no drag-and-drop library, no AWS SDK (SigV4 is signed
directly).

---

## Configuration

Everything is an environment variable. Only four are required.

### Required

| Variable | Secret | Description |
|---|---|---|
| `DATABASE_URL` | yes | PostgreSQL DSN. **Must be PostgreSQL**, not MySQL. |
| `GITHUB_CLIENT_ID` | no | OAuth app client id. |
| `GITHUB_CLIENT_SECRET` | **yes** | OAuth app client secret. |
| `SESSION_SECRET` | **yes** | ≥32 chars. `openssl rand -base64 48`. Rotating it signs everyone out and invalidates API tokens' stored GitHub credentials. |

`APP_URL` is required in production (it builds the OAuth callback URL and the
links in PR backlink comments): set it to the exact public origin, e.g.
`https://ida-agile.capstone.uamishub.com`.

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

### Webhooks and polling

| Variable | Default | Description |
|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | — | HMAC secret. **Unset means webhooks are disabled**; the app falls back to polling. |
| `GITHUB_POLL_TOKEN` | — | Credential for the *background* poller. Without it, only on-view refresh runs. |
| `POLL_INTERVAL_SECONDS` | `300` | Background sweep interval. `0` disables. |
| `ONVIEW_REFRESH_SECONDS` | `120` | Throttle for refreshing an item when someone opens it. |

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
| `PGPOOL_MAX` | `10` |
| `RATE_LIMIT_BURST` / `RATE_LIMIT_PER_SECOND` | `240` / `8` |

---

## GitHub OAuth app

Create an OAuth app **in the org** (Settings → Developer settings → OAuth Apps):

- **Homepage URL**: your `APP_URL`
- **Authorization callback URL**: `<APP_URL>/api/auth/callback`

Scopes requested are `read:user read:org` only — no write access. `read:org` is
required to read team membership.

> ⚠️ If the org enforces OAuth app access restrictions, the app must be
> **approved for the org**, or membership lookups return 404 and *everyone* is
> locked out.
>
> ⚠️ Branch creation and PR comments act as the signed-in user, so that user
> needs push/write access to the repo. Failures degrade gracefully — they never
> block a state change.

---

## Authentication

Two credentials, one authorization rule.

**Browser (GitHub OAuth):**

1. `/api/auth/login` redirects to GitHub with a signed, single-use `state`.
2. `/api/auth/callback` verifies `state`, exchanges the code, reads the profile,
   then calls `GET /orgs/{org}/teams/{team}/memberships/{login}`.
3. A session is minted **only** on `state: "active"`. Everything else — 404, a
   pending invite, a 5xx, a network error, an unparseable body — is a denial and
   lands on `/denied`.
4. The session cookie is **AES-256-GCM encrypted** (not merely signed),
   HTTP-only, `SameSite=Lax`, 7-day TTL. Encryption is required because the
   cookie carries the user's GitHub token, used for member and PR lookups.
5. Membership is **re-checked at most every 10 minutes**, so removing someone
   from the team revokes access in ~10 minutes rather than whenever their cookie
   expires.

**Machine (board API tokens):** see [`docs/api.md`](docs/api.md). A token acts as
the human who issued it, is stored only as a SHA-256 hash, and is revoked
automatically if that person leaves the team.

Failure policy is deliberately asymmetric:

| Situation | Sign-in | Revalidating an existing session/token |
|---|---|---|
| Not a member / pending invite | deny | **revoke** |
| GitHub 5xx, network error, bad body | deny (fail closed) | **keep** — the user already proved membership; a GitHub outage must not sign out the whole team |

**The one exempt route** is `POST /api/webhooks/github`: GitHub cannot sign in,
so that endpoint is authenticated by HMAC signature instead. The exemption is
scoped to exactly that path; every other route goes through the team gate.

---

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

Commenting acts as the linking user. A webhook-driven event has **no user in
context**; to have those comment too, supply a GitHub App installation token or
bot PAT via `GITHUB_POLL_TOKEN`. Without it, auto-linking still works — only the
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
`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `SESSION_SECRET`,
`GITHUB_WEBHOOK_SECRET` (optional), plus `APP_URL`. Only `APP_SECRET` and
`DATABASE_URL` are pre-wired in `base/deployments.yaml`, so each new variable
also needs an `env.valueFrom.secretKeyRef` entry.

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
