# ida-agile API

A work-item board (Azure-DevOps style) with a full REST API. **The web UI calls
exactly these endpoints** — there is no privileged internal surface, so anything
a person can do in the browser, a script or an agent can do with a token.

If you are an LLM driving this board: this document is the interface. You need a
base URL and a token, and nothing else.

- **Base URL**: your deployment's origin, e.g. `https://ida-agile.capstone.uamishub.com`
- **All endpoints** live under `/api/v1`
- **Machine-readable spec**: `GET /api/v1/openapi.json` (no auth required)

```sh
export AGILE=https://ida-agile.capstone.uamishub.com
```

---

## Authentication

Two credentials are accepted. Both resolve to the same identity and the same
authorization rule (membership of the configured GitHub team).

### 1. A GitHub token — the zero-setup path

If you have `gh` installed and are a member of the team, you are already
authenticated. This is the fastest way to drive the board from a script or a
Claude session:

```sh
curl -H "Authorization: Bearer $(gh auth token)" "$AGILE/api/v1/items"
```

The token needs the **`read:org`** scope, which is what the team-membership check
uses. (`gh auth login -s read:org` if yours predates that scope.)

The board **never stores your GitHub token**. It validates it, derives your
identity, and caches only that derived identity — keyed by a hash of the token —
for five minutes.

### 2. A board-issued token — for anything long-lived

Create one in the UI under **Tokens**. It is shown once and stored only as a
hash.

```sh
export TOKEN=iag_...
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/items"
```

### Which to use

| | GitHub token | Board token |
|---|---|---|
| Setup | none (`gh auth token`) | create in the UI |
| Scope | **broad** — grants everything your GitHub account can do | this board only |
| Revocation | revoke in GitHub (affects everything) | revoke in the UI |
| Best for | interactive/ad-hoc use from your own machine | CI, shared automation, anything long-lived |

**Prefer a board token for anything shared or long-lived.** A GitHub token is a
much broader credential; leaking one is a bigger problem than leaking a board
token.

Both are attributed to you in item history, and the two are distinguishable —
a board token records *"via API"*, a GitHub token records *"via API (github
token)"*.

A few operations need a **browser session** rather than a token, because they act
on GitHub as you: creating a branch (`/start-work`) and linking a PR. They return
a clear error explaining this.

---

## Errors

Every error has the same shape. Branch on `code`; show `message` to a human.

```json
{ "error": { "code": "validation_failed",
             "message": "The request body is not valid (title: Title is required).",
             "fields": { "title": ["Title is required"] } } }
```

| Code | Status | Meaning |
|---|---|---|
| `anonymous` | 401 | No credential supplied. |
| `bad_token` | 401 | Token unknown, malformed, expired, revoked, or rejected by GitHub. |
| `not_on_team` | 403 | You are not a member of the configured team. |
| `session_required` | 403 | Needs a browser session, not a token. |
| `not_found` | 404 | No such item/sprint/link. |
| `illegal_transition` | 409 | That state move is not allowed — see **States**. |
| `blocked_by_dependencies` | 409 | Unmet dependencies; the body lists them. |
| `dependency_cycle` | 409 | The edge would create a loop; the message names it. |
| `idempotency_conflict` | 409 | `Idempotency-Key` reused with a different body. |
| `validation_failed` | 422 | Body invalid; `fields` says which field and why. |
| `rate_limited` | 429 | Slow down; the message says for how long. |

Rate limits are generous (~240 burst, refilling ~8/s, per user). Seeding a
semester will not hit them.

---

## Seed a semester — the headline flow

`POST /api/v1/seed` creates **sprints, work items, their sprint assignments, and
the dependency graph between them, in one call**.

Items reference each other by a **client-supplied `key`** (ids do not exist yet),
and reference sprints by `sprintKey`. Keys are local to the request and are not
stored.

```sh
cat > backlog.json <<'JSON'
{
  "sprints": [
    {"key":"s1","name":"Sprint 1","goal":"Foundations","startsOn":"2026-08-25","endsOn":"2026-09-07"},
    {"key":"s2","name":"Sprint 2","goal":"Runner + schema","startsOn":"2026-09-08","endsOn":"2026-09-21"},
    {"key":"s3","name":"Sprint 3","goal":"Results UI","startsOn":"2026-09-22","endsOn":"2026-10-05"}
  ],
  "items": [
    {"key":"core",   "title":"Harness core",       "sprintKey":"s1","wave":"Wave 1","storyPoints":8,"priority":1},
    {"key":"schema", "title":"Task schema",        "sprintKey":"s1","wave":"Wave 1","storyPoints":3},
    {"key":"mock",   "title":"Mock model service", "sprintKey":"s1","wave":"Wave 1","storyPoints":2},

    {"key":"runner", "title":"Runner",             "sprintKey":"s2","wave":"Wave 2","storyPoints":5,
     "dependsOn":["core","schema"]},
    {"key":"store",  "title":"Results store",      "sprintKey":"s2","wave":"Wave 2","storyPoints":5,
     "dependsOn":["schema"]},

    {"key":"ui",     "title":"Results UI",         "sprintKey":"s3","wave":"Wave 3","storyPoints":8,
     "dependsOn":["runner","store"]}
  ],
  "currentSprintKey": "s1"
}
JSON

curl -X POST "$AGILE/api/v1/seed" \
  -H "Authorization: Bearer $(gh auth token)" \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: semester-2026-fall-v1' \
  -d @backlog.json
```

Response:

```json
{
  "sprints": [{ "key": "s1", "id": 1, "name": "Sprint 1", ... }],
  "items":   [{ "key": "core", "id": 1, "title": "Harness core", ... }],
  "counts":  { "sprints": 3, "items": 6, "dependencies": 5 },
  "currentSprintId": 1
}
```

Notes that matter:

- **The whole dependency graph is validated for cycles before any edge is
  written.** A cyclic plan is rejected with the loop named, not half-applied.
- `dependsOn` also accepts **numeric ids** of items that already exist, so you can
  extend an existing backlog.
- `currentSprintKey` sets the **shared** current sprint (see below) in the same call.
- With `Idempotency-Key`, re-running the exact same seed is a no-op that replays
  the original response — safe to retry, safe to run from a script twice.

Limits: 50 sprints and 500 items per call.

---

## Work items

Fields: `title`, `description` (markdown), `itemType`
(`Story`/`Task`/`Bug`/`Spike`), `state`, `assigneeLogin`, `storyPoints`,
`priority` (1 = highest … 4), `sprintId`, `tags`, `wave`, `repoFullName`.

### List / query

```sh
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/items?state=Active&assignee=me"
```

| Param | Example | Notes |
|---|---|---|
| `state` | `?state=Active` | |
| `type` | `?type=Bug` | |
| `assignee` | `?assignee=me` | `me` resolves to the caller |
| `sprintId` | `?sprintId=3` · `none` · `all` | |
| `wave` | `?wave=Wave%201` | |
| `tag` | `?tag=backend` | |
| `q` | `?q=ingest` | free text over title + description |
| `limit` / `offset` | `?limit=50&offset=50` | |
| `includeRemoved` | `?includeRemoved=true` | `Removed` hidden by default |

Each item comes back with a `readiness` object: `{ ready, blockers[], overridden }`.

### Create

```sh
curl -X POST "$AGILE/api/v1/items" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"title":"Refresh judge calibration set","itemType":"Story","storyPoints":5,
       "wave":"Wave 2","tags":["eval"]}'
```

Only `title` is required. For many at once use `/seed` (above), or
`{"items":[ ... ]}` on this endpoint when you do not need sprints or dependencies.

### Update / delete

```sh
curl -X PATCH "$AGILE/api/v1/items/42" -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"assigneeLogin":"octocat","sprintId":3}'

curl -X DELETE "$AGILE/api/v1/items/42" -H "Authorization: Bearer $TOKEN"
```

Prefer state `Removed` over deletion — it keeps the history.

**Move an item to another sprint** by patching `sprintId` (`null` = backlog).

---

## States

```
New ──▶ Active ──▶ Resolved ──▶ Closed
 │        │  ▲         │           │
 │        │  └─────────┘           │
 ▼        ▼                        │
Removed ──▶ New            Active ◀┘  (reactivate)
```

| From | May move to |
|---|---|
| `New` | `Active`, `Removed` |
| `Active` | `Resolved`, `New`, `Removed` |
| `Resolved` | `Closed`, `Active` |
| `Closed` | `Active` |
| `Removed` | `New` |

Anything else returns `409 illegal_transition` listing what *is* allowed.

```sh
curl -X POST "$AGILE/api/v1/items/42/move" -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"toState":"Active"}'
```

---

## Dependencies and the Ready queue

An item can be blocked by others. **Blocked work cannot be started** — the board
enforces it, so nobody has to read a doc to know what is safe to pick up.

```sh
# #42 is blocked by #12
curl -X POST "$AGILE/api/v1/items/42/dependencies" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"dependsOn":12}'

# What blocks it, what it blocks, and whether it is ready
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/items/42/dependencies"

# Remove an edge
curl -X DELETE "$AGILE/api/v1/items/42/dependencies?dependsOn=12" \
  -H "Authorization: Bearer $TOKEN"
```

A dependency is **satisfied** once the blocker is `Resolved` or `Closed`. Cycles
are rejected at creation with the loop named:
`That dependency would create a cycle: #1 → #4 → #1.`

### The Ready queue — the self-serve pickup list

```sh
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/ready?wave=Wave%202"
```

Returns unassigned items whose dependencies are **all** satisfied, plus a
`blocked` summary explaining what everything else is waiting on. This is the most
useful endpoint for "what should I work on next?".

### Override — the logged escape hatch

A hard block with no way through gets worked around outside the tool, so there is
an explicit one. It **requires a reason** and is written to item history.

```sh
curl -X POST "$AGILE/api/v1/items/42/override" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"reason":"Spiking the UI shell ahead of the runner, agreed in standup"}'
```

`DELETE` the same path to withdraw the override and re-apply the gate.

---

## Sprints

```sh
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/sprints"

curl -X POST "$AGILE/api/v1/sprints" -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name":"Sprint 4","goal":"Ship retrieval","startsOn":"2026-10-06","endsOn":"2026-10-19"}'
```

### The current sprint is SHARED

One sprint is the board's **current** sprint. It lives in the database, not in
anyone's session — when you set it, **every visitor lands on that sprint by
default**.

```sh
# Read it (includes who set it, and when)
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/sprints/current"

# Advance the whole team to Sprint 2
curl -X PUT "$AGILE/api/v1/sprints/current" -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"sprintId":2}'
```

In the UI, *browsing* another sprint is a local view change; *setting* the
current sprint is a separate, explicitly-labelled action.

---

## Comments

```sh
curl -X POST "$AGILE/api/v1/items/42/comments" -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"body":"Blocked on the eval harness."}'
```

---

## The homepage (living README)

The landing page has two halves: a **narrative** the team writes, and a **state
strip** generated from board data. Both are reachable from the API, so a Claude
session can seed the narrative when a board is first provisioned.

```sh
# Read it (returns the starter template, with isTemplate:true, until first edit)
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/pages/home"

# Write it — markdown, same renderer and sanitiser as work-item descriptions
curl -X PUT "$AGILE/api/v1/pages/home" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"body":"# IDA-LLM\n\n## What this project is\n\nAn LLM benchmark harness.\n\n## Goals\n\n- Reproducible evaluation across models\n- A results UI the class can read"}'

# Prior versions: who changed it and when
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/pages/home/revisions"
```

Each save archives the text it replaced, so "when did our goal change?" stays
answerable. Saving identical text records no revision.

The generated half is available on its own:

```sh
curl -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/summary"
```

```json
{
  "currentSprint": { "sprint": { "name": "Sprint 1", ... }, "daysRemaining": 13, "setBy": "clayton" },
  "states": { "New": 12, "Active": 4, "Resolved": 2, "Closed": 7, "Removed": 0 },
  "points": { "total": 68, "done": 21, "remaining": 47 },
  "readyCount": 5, "blockedCount": 3, "mergedPrCount": 9,
  "recentMergedPrs": [ ... ], "recentlyResolved": [ ... ]
}
```

Progress here is **merged PRs and finished items**. Commit counts and branch age
appear elsewhere as activity and are deliberately excluded.

---

## Other endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/ready` | Unblocked, unassigned work |
| `GET /api/v1/members` | Team members (valid `assigneeLogin` values). Session only. |
| `GET /api/v1/prs` | Open PRs annotated with the item ids they mention. Session only. |
| `POST /api/v1/items/{id}/links` | Attach a PR (URL, `owner/repo#123`, or `123`) |
| `POST /api/v1/items/{id}/start-work` | Activate + create the branch. Session only. |
| `GET`/`PUT /api/v1/pages/home` | The living README |
| `GET /api/v1/summary` | Generated board state |
| `GET`/`DELETE /api/v1/tokens` | Manage your board tokens |
| `GET /api/healthz` · `GET /api/readyz` | Liveness · readiness. No auth. |

---

## Git integration (automatic)

Delivery here is **trunk-based**, so a board-created branch is short-lived by
design. The board reflects that:

- **Merged PRs are progress.** Commits are shown as *activity* and never count
  toward progress or burndown.
- A branch open too long, or too far behind the default branch, gets a
  **"branch stale"** badge.

| Event | Effect |
|---|---|
| Commit pushed to the item's branch | Recorded; first commit moves `New` → `Active` |
| Commit message or PR text contains `AB#42` | Attaches to item 42 (scoped to that repo) |
| PR opened from the item's branch | Auto-linked; item ensured `Active` |
| PR merged | Item → `Resolved` (**never** `Closed` — accepting stays human) |
| PR closed unmerged | No state change; item shows a warning |

Every automatic move is recorded as *"moved by GitHub (PR #123 merged)"*.

Linking a PR also maintains **one** comment on that PR pointing back at the work
item, so the link is discoverable from GitHub.

---

## Worked example: advance the semester

```sh
export AGILE=https://ida-agile.capstone.uamishub.com
export GH="Authorization: Bearer $(gh auth token)"

# What is unblocked right now?
curl -s -H "$GH" "$AGILE/api/v1/ready" | python3 -m json.tool

# Take something
curl -s -X PATCH "$AGILE/api/v1/items/3" -H "$GH" \
  -H 'content-type: application/json' -d '{"assigneeLogin":"'"$(gh api user --jq .login)"'"}'

# Move it along
curl -s -X POST "$AGILE/api/v1/items/3/move" -H "$GH" \
  -H 'content-type: application/json' -d '{"toState":"Active"}'

# End of sprint: advance the whole team
curl -s -X PUT "$AGILE/api/v1/sprints/current" -H "$GH" \
  -H 'content-type: application/json' -d '{"sprintId":2}'
```
