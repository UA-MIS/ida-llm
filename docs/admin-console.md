# Admin console: operator runbook

The admin console (`/admin` on the frontend) lets UA-MIS members manage models,
provider keys, benchmark material, classes and units, and runs, without touching
code. This page covers what an operator needs to run it. The design and its
decisions (AD-1 … AD-15) live in the capstone repo's
`artifacts/design/admin-console.md`.

## The switches

| Setting | Where | Default | What it does |
|---|---|---|---|
| `IDA_CONFIG_SOURCE` | ConfigMap (per overlay) | `yaml` | `yaml`: serve models, tasks and curriculum from the image's YAML, exactly as before. `db`: the database is the source of truth. It is seeded **once** from that same YAML and edited at `/admin` after that. |
| `ADMIN_CONSOLE_ENABLED` | ConfigMap (per overlay) | unset | Frontend only. When unset, `/admin` returns 404. Preview never sets it. |
| `IDA_ADMIN_TOKENS` | Vault → `ida-llm-secret` | empty | The admin bearer token. The api and the frontend read the same property. When empty, every `/admin` API route returns 503 `admin_disabled`. |
| `IDA_CREDENTIALS_KEK` | Vault → `ida-llm-secret` | empty | Key-encryption key for admin-entered provider keys. If it is malformed, the api and runner refuse to boot. If it is empty, credentials can't be used and everything else still works. |
| `AUTH_SECRET`, `AUTH_DEX_SECRET` | Vault → `ida-llm-secret` | — | Frontend sign-in (Auth.js session key; the Dex client secret). |
| `AUTH_URL`, `AUTH_DEX_ISSUER`, `AUTH_DEX_ID` | ConfigMap (dev/staging/prod overlays) | — | `AUTH_URL` **must** equal the overlay's ingress host, and Dex must hold the matching redirect URI. |
| `IDA_ADMIN_GROUPS` | ConfigMap (base) | `UA-MIS:ida-llm` | The Dex group allowed to sign in. Matched exactly. |
| `IDA_ADMIN_RUN_MAX_ESTIMATED_USD` | ConfigMap (base) | `25` | Above this estimated spend, an admin launch requires the dollar figure to be typed in. |
| `IDA_TASKS_SPEC_GATED` | ConfigMap | `false` | When true, the full `GET /tasks/{id}` and the transcript route require `author`. Turn it on only after the frontend reads `/tasks/{id}/meta`. Private material can't be added until it is on. |

## Seeding Vault (before C1 syncs)

The chart's secret refs are **not optional**. If a key is missing, its pods sit in
`CreateContainerConfigError`. Seed every environment first, using `patch` and never
`put` (`put` wipes the sibling keys):

```bash
vault kv patch secret/tenants/ida-llm/<env>/app \
  IDA_CREDENTIALS_KEK='k1:<base64url-32-bytes>' \
  IDA_ADMIN_TOKENS='admin-console:<token_urlsafe(32)>' \
  AUTH_SECRET='<openssl rand -base64 32>' \
  AUTH_DEX_SECRET='<the ida-llm Dex client secret>'
```

- Generate the KEK with: `python -c "import secrets,base64;print('k1:'+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`
- Use a **different** KEK and admin token in each environment. Restoring a prod
  database into dev should not let dev decrypt prod's keys.
- `AUTH_DEX_SECRET` is the **same** in all three environments, because there is
  one Dex client. It must match platform-infra's `dex-github` key
  `ida-llm-client-secret`. Rotate both together.

To check without reading any values: `kubectl -n ida-llm-<env> get externalsecret ida-llm-secret`
should be `SecretSynced`, and
`kubectl -n ida-llm-<env> get secret ida-llm-secret -o jsonpath='{.data}' | jq 'keys'`
should list all four names.

## Turning an environment on (C2/C3)

1. Set `IDA_CONFIG_SOURCE: db` in the overlay's ConfigMap patch and sync. On
   start, the api, runner and sweeps seed the configuration tables, but only if
   they have never been seeded. Seeding is serialised by a Postgres advisory
   lock, so only one pod does it. If the YAML fails validation, the pod fails
   readiness and the previous replicas keep serving.
2. **Run the parity check** from an api pod:
   ```bash
   kubectl -n ida-llm-<env> exec deploy/ida-llm-api -- python -m ida_core.configdb diff
   ```
   An empty output (exit 0) means the database serves exactly what the YAML
   did. Every task keeps its `content_sha`, so no score moves and no pair is
   re-enqueued.
3. Set `ADMIN_CONSOLE_ENABLED: "true"` and sync.
4. From a frontend pod, check that Dex is reachable:
   `wget -qO- https://id.capstone.uamishub.com/.well-known/openid-configuration`.
   If it fails, raise a platform netpol change.

**Rollback:** set `IDA_CONFIG_SOURCE: yaml`. The site goes back to serving the
image's YAML. Admin edits stay in the database and are ignored until you flip
back.

## After the switch

- Admin edits go live in every process within `IDA_CONFIG_REFRESH_S` (5 s),
  with no restart.
- Each write appends a `config_revisions` row and an `audit_log` row. Every
  version of every task is kept in `task_revisions`, so any
  `runs.task_content_sha` still resolves to its exact text.
- Once admins start editing, `configdb diff` lists what they changed. That
  output is expected, not an error.
- `GET /admin/export` (from the console) downloads the live configuration as
  YAML: a backup, and a way to pull admin edits back into git. Private families
  are excluded unless you ask for them, and every export is audited.
- `python -m ida_core.configdb import <dir>` replaces the configuration with a
  directory's YAML. It is for dev and tests only, and it refuses to run if
  admins have made edits unless you pass `--force`.

## Rotating the credentials KEK

1. Put the new kid **first** in Vault and keep the old one after it:
   `IDA_CREDENTIALS_KEK='k2:<new>,k1:<old>'`.
2. Restart the api and runner so they pick up the new value.
3. Re-encrypt every stored key under the new kid:
   ```bash
   kubectl -n ida-llm-<env> exec deploy/ida-llm-api -- python -m ida_core.configdb rotate-kek
   ```
4. Remove the old kid from Vault and restart again.

If you lose every KEK, admin-entered provider keys can't be recovered and must be
entered again. Models that use `api_key_env` are unaffected.

## Moving hosts

Change these three together: the overlay's ingress host, the overlay's `AUTH_URL`,
and the redirect URI on the `ida-llm` Dex client in platform-infra. No code
change is needed. If Dex itself moves, also change `AUTH_DEX_ISSUER`.

## Emergencies

- **Revoke everyone's session now:** rotate `AUTH_SECRET`. Everyone is signed out.
- **Lock out the console entirely:** empty `IDA_ADMIN_TOKENS`. The admin API
  returns 503, and the public site is unaffected.
- **Someone was removed from the team:** they keep access until their session
  expires, at most 8 hours (`IDA_ADMIN_SESSION_MAX_AGE_S`). Rotate
  `AUTH_SECRET` to cut that short.
