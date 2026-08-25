-- The living README: a human-written narrative page with full edit history.
--
-- Keyed by slug so further pages (a charter, an onboarding note) cost nothing
-- later; today only 'home' is used.

CREATE TABLE IF NOT EXISTS board_pages (
  instance_key TEXT        NOT NULL,
  slug         TEXT        NOT NULL,
  body         TEXT        NOT NULL DEFAULT '',
  updated_by   TEXT        NOT NULL DEFAULT '',
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (instance_key, slug)
);

-- Every save keeps the PREVIOUS text, so "when did our goal change?" is
-- answerable a semester later.
CREATE TABLE IF NOT EXISTS board_page_revisions (
  id           SERIAL PRIMARY KEY,
  instance_key TEXT        NOT NULL,
  slug         TEXT        NOT NULL,
  body         TEXT        NOT NULL,
  edited_by    TEXT        NOT NULL DEFAULT '',
  edited_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS page_revisions_idx
  ON board_page_revisions (instance_key, slug, edited_at DESC);
