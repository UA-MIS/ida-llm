-- ida-agile schema.
--
-- Everything lives in its own schema (default `agile`) so it can never collide
-- with the product's own tables in a shared tenant database.
--
-- `instance_key` scopes every user-visible row to one board. One deploy is one
-- board today; the column exists so that a future multi-board mode is a query
-- change rather than a migration.

CREATE TABLE IF NOT EXISTS sprints (
  id            SERIAL PRIMARY KEY,
  instance_key  TEXT        NOT NULL,
  name          TEXT        NOT NULL,
  goal          TEXT        NOT NULL DEFAULT '',
  starts_on     DATE        NOT NULL,
  ends_on       DATE        NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT sprint_dates_ordered CHECK (ends_on >= starts_on),
  CONSTRAINT sprint_name_unique_per_instance UNIQUE (instance_key, name)
);

CREATE TABLE IF NOT EXISTS work_items (
  id                  SERIAL PRIMARY KEY,
  instance_key        TEXT        NOT NULL,
  title               TEXT        NOT NULL CHECK (length(btrim(title)) > 0),
  description         TEXT        NOT NULL DEFAULT '',
  item_type           TEXT        NOT NULL DEFAULT 'Story'
                        CHECK (item_type IN ('Story','Task','Bug','Spike')),
  state               TEXT        NOT NULL DEFAULT 'New'
                        CHECK (state IN ('New','Active','Resolved','Closed','Removed')),
  assignee_login      TEXT,
  assignee_avatar_url TEXT,
  story_points        INTEGER     CHECK (story_points IS NULL OR story_points >= 0),
  priority            INTEGER     NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 4),
  sprint_id           INTEGER     REFERENCES sprints(id) ON DELETE SET NULL,
  board_rank          DOUBLE PRECISION NOT NULL DEFAULT 0,
  -- Branch created by "Start work".
  branch_name         TEXT,
  branch_repo         TEXT,
  branch_url          TEXT,
  branch_created_at   TIMESTAMPTZ,
  created_by          TEXT        NOT NULL DEFAULT '',
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS work_items_instance_idx ON work_items (instance_key);
CREATE INDEX IF NOT EXISTS work_items_state_idx    ON work_items (instance_key, state);
CREATE INDEX IF NOT EXISTS work_items_sprint_idx   ON work_items (sprint_id);
CREATE INDEX IF NOT EXISTS work_items_assignee_idx ON work_items (instance_key, assignee_login);
CREATE INDEX IF NOT EXISTS work_items_board_idx    ON work_items (instance_key, state, board_rank);
CREATE INDEX IF NOT EXISTS work_items_branch_idx   ON work_items (branch_repo, branch_name);

CREATE TABLE IF NOT EXISTS work_item_tags (
  item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  tag     TEXT    NOT NULL CHECK (length(btrim(tag)) > 0),
  PRIMARY KEY (item_id, tag)
);

CREATE TABLE IF NOT EXISTS pull_request_links (
  id                  SERIAL PRIMARY KEY,
  item_id             INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  repo_full_name      TEXT    NOT NULL,
  pr_number           INTEGER NOT NULL CHECK (pr_number > 0),
  url                 TEXT    NOT NULL,
  title               TEXT    NOT NULL DEFAULT '',
  pr_state            TEXT    NOT NULL DEFAULT 'open',
  merged              BOOLEAN NOT NULL DEFAULT false,
  draft               BOOLEAN NOT NULL DEFAULT false,
  head_ref            TEXT    NOT NULL DEFAULT '',
  base_ref            TEXT    NOT NULL DEFAULT '',
  checks_state        TEXT,
  behind_by           INTEGER,
  -- id of the backlink comment this app maintains on the PR, so it edits
  -- its own comment instead of posting a new one on every event.
  backlink_comment_id BIGINT,
  linked_by           TEXT    NOT NULL DEFAULT '',
  last_synced_at      TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (item_id, repo_full_name, pr_number)
);

CREATE INDEX IF NOT EXISTS pr_links_item_idx ON pull_request_links (item_id);
CREATE INDEX IF NOT EXISTS pr_links_pr_idx   ON pull_request_links (repo_full_name, pr_number);

CREATE TABLE IF NOT EXISTS item_commits (
  id             SERIAL PRIMARY KEY,
  item_id        INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  repo_full_name TEXT    NOT NULL,
  sha            TEXT    NOT NULL,
  message        TEXT    NOT NULL DEFAULT '',
  author_login   TEXT,
  author_name    TEXT    NOT NULL DEFAULT '',
  url            TEXT    NOT NULL DEFAULT '',
  branch         TEXT    NOT NULL DEFAULT '',
  committed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (item_id, repo_full_name, sha)
);

CREATE INDEX IF NOT EXISTS item_commits_item_idx ON item_commits (item_id, committed_at DESC);

CREATE TABLE IF NOT EXISTS comments (
  id                SERIAL PRIMARY KEY,
  item_id           INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  author_login      TEXT    NOT NULL,
  author_avatar_url TEXT,
  body              TEXT    NOT NULL CHECK (length(btrim(body)) > 0),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS comments_item_idx ON comments (item_id, created_at);

CREATE TABLE IF NOT EXISTS activity (
  id           SERIAL PRIMARY KEY,
  item_id      INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  actor_login  TEXT    NOT NULL,
  -- 'user' (UI), 'api' (token), 'github' (webhook/poll). Makes automatic
  -- transitions attributable so a human can always see why an item moved.
  source       TEXT    NOT NULL DEFAULT 'user'
                 CHECK (source IN ('user','api','github','system')),
  field        TEXT    NOT NULL,
  old_value    TEXT,
  new_value    TEXT,
  note         TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS activity_item_idx ON activity (item_id, created_at DESC);

-- Board-issued machine credentials. Only a hash is ever stored.
CREATE TABLE IF NOT EXISTS api_tokens (
  id           SERIAL PRIMARY KEY,
  instance_key TEXT        NOT NULL,
  name         TEXT        NOT NULL CHECK (length(btrim(name)) > 0),
  -- SHA-256 of the presented token; the token itself is shown once and never stored.
  token_hash   TEXT        NOT NULL UNIQUE,
  -- Short non-secret prefix so a user can tell their tokens apart.
  token_prefix TEXT        NOT NULL,
  owner_login  TEXT        NOT NULL,
  -- The issuer's GitHub OAuth token, AES-GCM encrypted, so this token's
  -- membership can be re-verified and the token retired when they leave.
  gh_token     TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at TIMESTAMPTZ,
  expires_at   TIMESTAMPTZ,
  revoked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS api_tokens_owner_idx ON api_tokens (instance_key, owner_login);

-- Makes a retried create safe: the first response is replayed verbatim.
CREATE TABLE IF NOT EXISTS idempotency_keys (
  id            SERIAL PRIMARY KEY,
  instance_key  TEXT        NOT NULL,
  idem_key      TEXT        NOT NULL,
  owner_login   TEXT        NOT NULL,
  request_hash  TEXT        NOT NULL,
  response_body TEXT        NOT NULL,
  status_code   INTEGER     NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (instance_key, owner_login, idem_key)
);

CREATE INDEX IF NOT EXISTS idempotency_created_idx ON idempotency_keys (created_at);

-- File attachments live in object storage (MinIO/S3); only metadata is here.
CREATE TABLE IF NOT EXISTS attachments (
  id           SERIAL PRIMARY KEY,
  item_id      INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  object_key   TEXT    NOT NULL,
  filename     TEXT    NOT NULL,
  content_type TEXT    NOT NULL DEFAULT 'application/octet-stream',
  size_bytes   BIGINT  NOT NULL DEFAULT 0,
  uploaded_by  TEXT    NOT NULL DEFAULT '',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS attachments_item_idx ON attachments (item_id);

-- Webhook delivery ids, so a redelivered event is processed at most once.
CREATE TABLE IF NOT EXISTS webhook_deliveries (
  delivery_id TEXT PRIMARY KEY,
  event       TEXT        NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS webhook_deliveries_received_idx ON webhook_deliveries (received_at);

-- Conditional-request state for the polling fallback, so a deployment without
-- webhooks still converges without burning GitHub rate limit.
CREATE TABLE IF NOT EXISTS poll_state (
  instance_key   TEXT        NOT NULL,
  resource       TEXT        NOT NULL,
  etag           TEXT,
  last_polled_at TIMESTAMPTZ,
  PRIMARY KEY (instance_key, resource)
);
