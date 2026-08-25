import { query, queryOne } from '@/lib/db/pool';
import { config } from '@/lib/env';
import { getCurrentSprint, readinessMap } from './deps-queries';
import { listSprints } from './queries';
import type { Sprint, WorkItemState } from './workitem';

/**
 * The auto-generated half of the homepage.
 *
 * Everything here is derived from board data, so it is never hand-maintained
 * and cannot drift the way a prose status paragraph does.
 *
 * Trunk-based note: progress is measured by **merged pull requests** and by
 * items reaching a finished state. Commit counts and branch age are shown
 * elsewhere as *activity* and are deliberately excluded from these numbers.
 */
export interface BoardSummary {
  currentSprint: {
    sprint: Sprint | null;
    setBy: string | null;
    daysRemaining: number | null;
    daysTotal: number | null;
  };
  states: Record<WorkItemState, number>;
  points: { total: number; done: number; remaining: number };
  readyCount: number;
  blockedCount: number;
  unassignedCount: number;
  mergedPrCount: number;
  recentlyResolved: Array<{ id: number; title: string; state: string; at: string }>;
  recentMergedPrs: Array<{
    itemId: number;
    itemTitle: string;
    repoFullName: string;
    prNumber: number;
    title: string;
    url: string;
  }>;
  totals: { items: number; sprints: number };
}

function daysBetween(fromIso: string, toIso: string): number {
  const a = Date.parse(`${fromIso}T00:00:00Z`);
  const b = Date.parse(`${toIso}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return 0;
  return Math.round((b - a) / 86_400_000);
}

/**
 * @param today YYYY-MM-DD, supplied by the caller so the clock is read on the
 *              server and never during a React render.
 */
export async function boardSummary(today: string): Promise<BoardSummary> {
  const instance = config.instanceKey;

  const [stateRows, pointRows, sprints, current, readiness, resolvedRows, prRows, totalRow] =
    await Promise.all([
      query<{ state: string; n: string }>(
        `SELECT state, COUNT(*) AS n FROM work_items
          WHERE instance_key = $1 GROUP BY state`,
        [instance],
      ),
      queryOne<{ total: string; done: string }>(
        `SELECT COALESCE(SUM(story_points), 0) AS total,
                COALESCE(SUM(story_points) FILTER (WHERE state IN ('Resolved','Closed')), 0) AS done
           FROM work_items WHERE instance_key = $1 AND state <> 'Removed'`,
        [instance],
      ),
      listSprints(),
      getCurrentSprint(),
      readinessMap(),
      query<{ id: number; title: string; state: string; updated_at: Date }>(
        `SELECT id, title, state, updated_at FROM work_items
          WHERE instance_key = $1 AND state IN ('Resolved','Closed')
          ORDER BY updated_at DESC LIMIT 5`,
        [instance],
      ),
      query<{
        item_id: number;
        item_title: string;
        repo_full_name: string;
        pr_number: number;
        title: string;
        url: string;
      }>(
        `SELECT pl.item_id, wi.title AS item_title, pl.repo_full_name, pl.pr_number,
                pl.title, pl.url
           FROM pull_request_links pl
           JOIN work_items wi ON wi.id = pl.item_id
          WHERE wi.instance_key = $1 AND pl.merged
          ORDER BY pl.last_synced_at DESC NULLS LAST, pl.id DESC
          LIMIT 5`,
        [instance],
      ),
      queryOne<{ n: string }>(
        `SELECT COUNT(*) AS n FROM work_items WHERE instance_key = $1 AND state <> 'Removed'`,
        [instance],
      ),
    ]);

  const states: Record<WorkItemState, number> = {
    New: 0, Active: 0, Resolved: 0, Closed: 0, Removed: 0,
  };
  for (const r of stateRows) states[r.state as WorkItemState] = Number(r.n);

  const sprint = sprints.find((s) => s.id === current.sprintId) ?? null;
  const daysRemaining = sprint ? Math.max(0, daysBetween(today, sprint.endsOn)) : null;
  const daysTotal = sprint ? daysBetween(sprint.startsOn, sprint.endsOn) + 1 : null;

  // Ready / blocked are computed over unassigned, not-yet-started work — the
  // same definition the Ready view uses, so the two never disagree.
  const openUnassigned = await query<{ id: number }>(
    `SELECT id FROM work_items
      WHERE instance_key = $1 AND state = 'New' AND assignee_login IS NULL`,
    [instance],
  );
  let readyCount = 0;
  let blockedCount = 0;
  for (const row of openUnassigned) {
    if (readiness.get(row.id)?.ready === false) blockedCount++;
    else readyCount++;
  }

  const mergedTotal = await queryOne<{ n: string }>(
    `SELECT COUNT(*) AS n FROM pull_request_links pl
       JOIN work_items wi ON wi.id = pl.item_id
      WHERE wi.instance_key = $1 AND pl.merged`,
    [instance],
  );

  const total = Number(pointRows?.total ?? 0);
  const done = Number(pointRows?.done ?? 0);

  return {
    currentSprint: { sprint, setBy: current.setBy, daysRemaining, daysTotal },
    states,
    points: { total, done, remaining: Math.max(0, total - done) },
    readyCount,
    blockedCount,
    unassignedCount: openUnassigned.length,
    mergedPrCount: Number(mergedTotal?.n ?? 0),
    recentlyResolved: resolvedRows.map((r) => ({
      id: r.id,
      title: r.title,
      state: r.state,
      at: r.updated_at.toISOString(),
    })),
    recentMergedPrs: prRows.map((r) => ({
      itemId: r.item_id,
      itemTitle: r.item_title,
      repoFullName: r.repo_full_name,
      prNumber: r.pr_number,
      title: r.title,
      url: r.url,
    })),
    totals: { items: Number(totalRow?.n ?? 0), sprints: sprints.length },
  };
}
