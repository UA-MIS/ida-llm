-- Dependencies, shared sprint state, waves, and repo-awareness.
--
-- Repo-awareness is deliberately introduced now rather than later: a board for
-- platform maintainers will follow MANY repos, and retrofitting that would
-- touch every git-integration path. A single-repo tenant simply leaves
-- repo_full_name NULL and never sees a repo picker.

ALTER TABLE work_items ADD COLUMN IF NOT EXISTS repo_full_name TEXT;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS wave TEXT;

-- An explicit, logged escape hatch from dependency gating. A hard block with no
-- way through gets worked around outside the tool; a logged override keeps the
-- truth inside it.
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS dep_override_by     TEXT;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS dep_override_reason TEXT;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS dep_override_at     TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS work_items_repo_idx ON work_items (instance_key, repo_full_name);
CREATE INDEX IF NOT EXISTS work_items_wave_idx ON work_items (instance_key, wave);

-- Many-to-many "this item is blocked by that item".
CREATE TABLE IF NOT EXISTS work_item_dependencies (
  item_id       INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  depends_on_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
  created_by    TEXT    NOT NULL DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (item_id, depends_on_id),
  -- A self-dependency is the degenerate cycle; reject it in the schema.
  CONSTRAINT no_self_dependency CHECK (item_id <> depends_on_id)
);

CREATE INDEX IF NOT EXISTS deps_item_idx    ON work_item_dependencies (item_id);
CREATE INDEX IF NOT EXISTS deps_blocker_idx ON work_item_dependencies (depends_on_id);

-- Board-wide settings. The CURRENT sprint is shared server-side state: when one
-- person sets it, every visitor lands on that sprint. It is deliberately not a
-- per-user preference.
CREATE TABLE IF NOT EXISTS board_settings (
  instance_key          TEXT PRIMARY KEY,
  current_sprint_id     INTEGER REFERENCES sprints(id) ON DELETE SET NULL,
  current_sprint_set_by TEXT,
  current_sprint_set_at TIMESTAMPTZ
);

-- Sprint ordering for the selector: explicit position, falling back to dates.
ALTER TABLE sprints ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0;
