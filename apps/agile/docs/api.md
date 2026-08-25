# ida-agile API

A work-item board (Azure-DevOps style) with a full REST API. **The web UI calls
exactly these endpoints** — there is no privileged internal surface, so anything
a person can do in the browser, a script or an agent can do with a token.

If you are an LLM driving this board: this document is the interface. You need
a base URL and a token, and nothing else.

- **Base URL**: your deployment's origin, e.g. `https://ida-agile.capstone.uamishub.com`
- **All endpoints** are under `/api/v1`
- **Machine-readable spec**: `GET /api/v1/openapi.json` (no auth required)

---

## Authentication

Send a board-issued token as a bearer token:

```
Authorization: Bearer iag_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Get one from the board UI → **Tokens** → *Create token*. It is shown once and
stored only as a hash.

Three things worth knowing:

- A token **acts as the human who created it**. Everything it does is attributed
  to that person in the item history (`source: "api"`), so the audit trail stays
  honest.
- A token **cannot outlive its owner's team membership**. If they leave the
  GitHub team, the token is revoked automatically on next use.
- **GitHub tokens are not accepted** as board credentials, and board tokens
  carry no GitHub privileges.

A few operations need a *browser session* rather than a token, because they act
on GitHub as you: creating a branch (`/start-work`) and linking a pull request
(which reads the PR from GitHub). They return a clear `400`/`403` explaining
this rather than failing obscurely.

```sh
export AGILE=https://ida-agile.capstone.uamishub.com
export TOKEN=iag_...      # keep this out of source control
```

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
| `bad_token` | 401 | Token unknown, malformed, expired or revoked. |
| `not_on_team` | 403 | The token's owner is no longer on the GitHub team. |
| `session_required` | 403 | Needs a browser session, not a token. |
| `not_found` | 404 | No such item/sprint/link. |
| `illegal_transition` | 409 | That state move is not allowed — see **States**. |
| `idempotency_conflict` | 409 | `Idempotency-Key` reused with a different body. |
| `validation_failed` | 422 | Body invalid; `fields` says which field and why. |
| `rate_limited` | 429 | Slow down; the message says for how long. |
| `database_unavailable` | 503 | Board is starting or the database is unreachable. |

Rate limits are generous (a burst of ~240 requests, refilling ~8/second, per
user). Seeding a sprint's worth of stories will not hit them.

---

## Work items

A work item has: `title`, `description` (markdown), `itemType`
(`Story`/`Task`/`Bug`/`Spike`), `state`, `assigneeLogin`, `storyPoints`,
`priority` (1 = highest … 4), `sprintId`, and `tags`.

### List / query

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/items"
```

Filters (combine freely):

| Param | Example | Notes |
|---|---|---|
| `state` | `?state=Active` | |
| `type` | `?type=Bug` | |
| `assignee` | `?assignee=me` | `me` resolves to the token's owner |
| `sprintId` | `?sprintId=3` · `?sprintId=none` · `?sprintId=all` | |
| `tag` | `?tag=backend` | |
| `q` | `?q=ingest` | free text over title + description |
| `limit` / `offset` | `?limit=50&offset=50` | |
| `includeRemoved` | `?includeRemoved=true` | `Removed` items are hidden by default |

**My open items:**

```sh
curl -s -H "Authorization: Bearer $TOKEN" \
  "$AGILE/api/v1/items?assignee=me&state=Active"
```

Response: `{ "items": [ ... ], "count": 12 }`

### Create one

```sh
curl -s -X POST "$AGILE/api/v1/items" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{
        "title": "Refresh judge calibration set",
        "description": "## Why\nDrift since the last run.\n\n## Acceptance\n- [ ] regenerate\n- [ ] compare",
        "itemType": "Story",
        "storyPoints": 5,
        "priority": 2,
        "assigneeLogin": "octocat",
        "tags": ["eval", "backend"]
      }'
```

Only `title` is required. Response: `{ "item": { "id": 42, ... } }`.

### Bulk create (seed a plan in one call)

Send `{ "items": [ ... ] }` with up to 100 entries:

```sh
curl -s -X POST "$AGILE/api/v1/items" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H "Idempotency-Key: sprint-3-seed-v1" \
  -d '{"items":[
        {"title":"Ingest transcripts","itemType":"Story","storyPoints":5},
        {"title":"Chunking strategy spike","itemType":"Spike","storyPoints":3},
        {"title":"Fix token overflow","itemType":"Bug","priority":1}
      ]}'
```

Response: `{ "items": [ ... ], "count": 3 }`.

### Idempotency (make retries safe)

Add `Idempotency-Key: <your-unique-string>` to any create. If the call is
retried with the **same key and the same body**, the original response is
replayed and nothing is created twice. The same key with a *different* body is a
`409 idempotency_conflict` rather than a silent overwrite.

Use it whenever a retry is possible — which, for an agent, is always.

### Read one

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/items/42"
```

Returns the item plus its `comments`, `activity` (full history) and
`attachments`.

### Update

`PATCH` with only the fields you want to change:

```sh
curl -s -X PATCH "$AGILE/api/v1/items/42" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"assigneeLogin":"octocat","storyPoints":8,"sprintId":3}'
```

### Delete

```sh
curl -s -X DELETE "$AGILE/api/v1/items/42" -H "Authorization: Bearer $TOKEN"
```

Prefer moving to state `Removed` instead — it keeps the history.

---

## States

```
New ──▶ Active ──▶ Resolved ──▶ Closed
 │        │  ▲         │           │
 │        │  └─────────┘           │
 │        ▼                        │
 └──▶ Removed ──▶ New       Active ◀┘  (reactivate)
```

| From | May move to |
|---|---|
| `New` | `Active`, `Removed` |
| `Active` | `Resolved`, `New`, `Removed` |
| `Resolved` | `Closed`, `Active` |
| `Closed` | `Active` |
| `Removed` | `New` |

Anything else returns `409 illegal_transition` with a message listing what *is*
allowed. Notably you cannot jump `New → Closed`; go via `Active` and `Resolved`.

### Move an item

```sh
curl -s -X POST "$AGILE/api/v1/items/42/move" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"toState":"Active"}'
```

`orderedIds` is optional and only affects card order within the board column.

---

## Pull requests

```sh
curl -s -X POST "$AGILE/api/v1/items/42/links" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"reference":"https://github.com/UA-MIS/ida-llm/pull/123"}'
```

`reference` accepts a PR URL, `owner/repo#123`, or a bare `123` (which uses the
board's primary repo). Linking posts a backlink comment on the PR.

Unlink with `DELETE /api/v1/items/42/links?linkId=<id>`.

**Most linking is automatic** — see *Git integration* below. You rarely need
this endpoint.

---

## Sprints

```sh
# List, with points/complete stats
curl -s -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/sprints"

# Create
curl -s -X POST "$AGILE/api/v1/sprints" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"Sprint 4","goal":"Ship retrieval","startsOn":"2026-09-01","endsOn":"2026-09-14"}'
```

Assign an item to a sprint by `PATCH`ing its `sprintId`. Deleting a sprint
returns its items to the backlog rather than deleting them.

---

## Comments

```sh
curl -s -X POST "$AGILE/api/v1/items/42/comments" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"body":"Blocked on the eval harness."}'
```

---

## Other endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/members` | Team members (valid `assigneeLogin` values). Session only. |
| `GET /api/v1/prs` | Open PRs, annotated with the item ids they mention. Session only. |
| `GET /api/v1/tokens` | Your tokens (never their values). |
| `DELETE /api/v1/tokens/{id}` | Revoke one. |
| `GET /api/healthz` | Liveness. No auth, no DB. |
| `GET /api/readyz` | Readiness — DB reachable and migrated. No auth. |

---

## Git integration (mostly automatic)

Once a work item has a branch, the board tracks it without being asked:

- Commits pushed to the branch appear on the item.
- A commit message or PR title/body containing `AB#42` attaches to item 42 —
  from *any* branch. (A bare `#42` is deliberately ignored: in a PR body that
  almost always means a GitHub issue.)
- **First commit** on a `New` item → `Active`.
- **PR opened** → `Active`, and auto-linked.
- **PR merged** → `Resolved`. Never `Closed` — accepting work stays a human
  decision.
- **PR closed unmerged** → no state change, but the item shows a warning.

Every automatic move is recorded in the item history as *"moved by GitHub (PR
#123 merged)"*, so a human can always see why something moved. All of this can
be turned off per-rule (see the README's configuration table).

To create a branch for an item (browser session required):

```
POST /api/v1/items/42/start-work
```

Branches are named from `BRANCH_PATTERN`, by default
`{type}/{id}-{slug}` → `story/42-refresh-judge-calibration-set`.

---

## A worked example: seed a sprint from a plan

```sh
export AGILE=https://ida-agile.capstone.uamishub.com
export TOKEN=iag_...

# 1. Create the sprint
SPRINT=$(curl -s -X POST "$AGILE/api/v1/sprints" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"Sprint 5","goal":"Retrieval quality","startsOn":"2026-09-15","endsOn":"2026-09-28"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["sprint"]["id"])')

# 2. Seed the stories into it, idempotently
curl -s -X POST "$AGILE/api/v1/items" \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -H "Idempotency-Key: sprint-5-seed" \
  -d "{\"items\":[
        {\"title\":\"Rerank candidate passages\",\"itemType\":\"Story\",\"storyPoints\":5,\"sprintId\":$SPRINT},
        {\"title\":\"Measure recall@10\",\"itemType\":\"Task\",\"storyPoints\":2,\"sprintId\":$SPRINT},
        {\"title\":\"Hybrid search spike\",\"itemType\":\"Spike\",\"storyPoints\":3,\"sprintId\":$SPRINT}
      ]}"

# 3. Check what landed
curl -s -H "Authorization: Bearer $TOKEN" "$AGILE/api/v1/items?sprintId=$SPRINT" \
  | python3 -m json.tool
```

Re-running step 2 with the same `Idempotency-Key` creates nothing further and
returns the original response.
