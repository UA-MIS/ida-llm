-- One-time cleanup: branch metadata that outlived its branch.
--
-- The board stores a branch's name, url and created-at on the work item. Until
-- now nothing could ever clear those columns: they are not writable through
-- PATCH, and no code path reacted to a branch being deleted. So every branch
-- that was merged-and-deleted, or cut and then abandoned, left a card pointing
-- at a ref that 404s.
--
-- The code fixes stop this recurring (the `delete` webhook clears the item, and
-- non-code item types no longer get a branch at all). This migration reconciles
-- the rows that were already written. It is deliberately written as a general
-- predicate rather than a list of ids, so a second board with the same history
-- is repaired by the same statement.
--
-- SQL cannot ask GitHub whether a ref still exists, so "stale" is approximated
-- by two populations that are both safe to clear and both observable here:

-- ---------------------------------------------------------------------------
-- A. Non-code items that were given a branch by the old Start-work flow.
--
-- Spike and Task no longer branch (see BRANCHING_ITEM_TYPES). An existing
-- Spike/Task branch is therefore a ref created by a rule that no longer holds,
-- and the guard `NOT EXISTS (... pull_request_links ...)` keeps the one case
-- that would be real work — a spike that did produce a PR — untouched.
--
-- Their recorded commits go too, and ONLY theirs: those rows were the base
-- branch's history, ingested because the old commit walk listed a branch's
-- whole ancestry rather than the commits ahead of the base. That is why item
-- 25 read "20 commits" on a branch nobody had ever pushed to. The delete is
-- narrowed to `ic.branch = wi.branch_name` so a commit attributed to the item
-- by an `AB#<id>` reference in its MESSAGE, on some other branch, survives.
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE stale_noncode_branches ON COMMIT DROP AS
SELECT wi.id, wi.branch_name
  FROM work_items wi
 WHERE wi.branch_name IS NOT NULL
   AND wi.item_type IN ('Spike', 'Task')
   AND NOT EXISTS (SELECT 1 FROM pull_request_links pl WHERE pl.item_id = wi.id);

DELETE FROM item_commits ic
 USING stale_noncode_branches s
 WHERE ic.item_id = s.id
   AND ic.branch = s.branch_name;

INSERT INTO activity (item_id, actor_login, source, field, old_value, new_value, note)
SELECT s.id, 'migration', 'system', 'branch', s.branch_name, NULL,
       'branch metadata cleared: this item type no longer uses a branch, and its recorded commits were the base branch''s history'
  FROM stale_noncode_branches s;

UPDATE work_items wi
   SET branch_repo = NULL, branch_name = NULL, branch_url = NULL,
       branch_created_at = NULL, updated_at = now()
  FROM stale_noncode_branches s
 WHERE wi.id = s.id;

-- ---------------------------------------------------------------------------
-- B. Finished work whose branch was merged away.
--
-- An item that is Closed or Removed, and every one of whose linked pull
-- requests is merged, is work that landed on trunk. Delivery here is
-- trunk-based, so that branch is deleted on merge as a matter of course, and
-- the item's own pointer at it is the thing left behind.
--
-- `head_ref` is not compared with `branch_name` on purpose: a developer who
-- opened the PR from a differently-named branch (item 9 did) is the same
-- situation, and matching on the name would miss exactly those.
--
-- Nothing is deleted here — the commits and the PR links ARE the record of
-- what this item shipped, and stay. Only the dead link goes.
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE stale_merged_branches ON COMMIT DROP AS
SELECT wi.id, wi.branch_name
  FROM work_items wi
 WHERE wi.branch_name IS NOT NULL
   AND wi.state IN ('Closed', 'Removed')
   AND EXISTS     (SELECT 1 FROM pull_request_links pl WHERE pl.item_id = wi.id)
   AND NOT EXISTS (SELECT 1 FROM pull_request_links pl
                    WHERE pl.item_id = wi.id AND pl.merged IS NOT TRUE);

INSERT INTO activity (item_id, actor_login, source, field, old_value, new_value, note)
SELECT s.id, 'migration', 'system', 'branch', s.branch_name, NULL,
       'branch metadata cleared: the item is closed and all of its pull requests were merged'
  FROM stale_merged_branches s;

UPDATE work_items wi
   SET branch_repo = NULL, branch_name = NULL, branch_url = NULL,
       branch_created_at = NULL, updated_at = now()
  FROM stale_merged_branches s
 WHERE wi.id = s.id;
