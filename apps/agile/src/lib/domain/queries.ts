import { query, queryOne, withTransaction } from '@/lib/db/pool';
import { config } from '@/lib/env';
import {
  assertTransition,
  createWorkItemSchema,
  toActor,
  type Actor,
  type ActorLike,
  type Attachment,
  type CreateWorkItemInput,
  type UpdateWorkItemInput,
  sprintSchema,
  type SprintInput,
  type WorkItem,
  type WorkItemState,
  type Sprint,
  type Comment,
  type ActivityEntry,
  type PullRequestLink,
} from './workitem';
import {
  mapActivity,
  mapAttachment,
  mapComment,
  mapPullRequest,
  mapSprint,
  mapWorkItem,
  type ActivityRow,
  type AttachmentRow,
  type CommentRow,
  type PullRequestLinkRow,
  type SprintRow,
  type WorkItemRow,
} from './mappers';
import type { LinkedPullRequest } from './board-prs';

const instance = () => config.instanceKey;

/**
 * Single projection for every work-item read, so tags, linked PRs, recent
 * commits and derived counts are always present and identical everywhere.
 */
const ITEM_SELECT = `
  SELECT wi.*,
         COALESCE(t.tags, ARRAY[]::text[])  AS tags,
         COALESCE(p.prs, '[]'::json)        AS pull_requests,
         COALESCE(c.commits, '[]'::json)    AS commits,
         COALESCE(c.commit_count, 0)        AS commit_count,
         COALESCE(p.merged_pr_count, 0)     AS merged_pr_count,
         GREATEST(
           wi.updated_at,
           COALESCE(c.last_commit_at, wi.updated_at),
           COALESCE(p.last_pr_at,     wi.updated_at)
         )                                  AS last_activity_at
    FROM work_items wi
    LEFT JOIN LATERAL (
      SELECT array_agg(tag ORDER BY tag) AS tags
        FROM work_item_tags WHERE item_id = wi.id
    ) t ON true
    LEFT JOIN LATERAL (
      SELECT json_agg(row_to_json(pl) ORDER BY pl.pr_number) AS prs,
             max(pl.created_at) AS last_pr_at,
             -- Merged PRs are the trunk-based progress signal; commits are
             -- activity and are deliberately NOT counted as progress.
             count(*) FILTER (WHERE pl.merged) AS merged_pr_count
        FROM pull_request_links pl WHERE pl.item_id = wi.id
    ) p ON true
    LEFT JOIN LATERAL (
      SELECT json_agg(row_to_json(x) ORDER BY x.committed_at DESC) AS commits,
             count(*) AS commit_count,
             max(x.committed_at) AS last_commit_at
        FROM (
          SELECT * FROM item_commits ic
           WHERE ic.item_id = wi.id
           ORDER BY ic.committed_at DESC
           LIMIT 20
        ) x
    ) c ON true
`;

export interface WorkItemFilters {
  state?: WorkItemState;
  sprintId?: number | null;
  assignee?: string;
  itemType?: string;
  search?: string;
  tag?: string;
  wave?: string;
  repoFullName?: string;
  includeRemoved?: boolean;
  limit?: number;
  offset?: number;
}

export async function listWorkItems(filters: WorkItemFilters = {}): Promise<WorkItem[]> {
  const params: unknown[] = [instance()];
  const where: string[] = ['wi.instance_key = $1'];

  if (!filters.includeRemoved) where.push(`wi.state <> 'Removed'`);

  if (filters.state) {
    params.push(filters.state);
    where.push(`wi.state = $${params.length}`);
  }
  if (filters.itemType) {
    params.push(filters.itemType);
    where.push(`wi.item_type = $${params.length}`);
  }
  if (filters.assignee) {
    params.push(filters.assignee);
    where.push(`wi.assignee_login = $${params.length}`);
  }
  if (filters.sprintId === null) {
    where.push('wi.sprint_id IS NULL');
  } else if (typeof filters.sprintId === 'number') {
    params.push(filters.sprintId);
    where.push(`wi.sprint_id = $${params.length}`);
  }
  if (filters.wave) {
    params.push(filters.wave);
    where.push(`wi.wave = $${params.length}`);
  }
  if (filters.repoFullName) {
    params.push(filters.repoFullName);
    where.push(`wi.repo_full_name = $${params.length}`);
  }
  if (filters.tag) {
    params.push(filters.tag);
    where.push(
      `EXISTS (SELECT 1 FROM work_item_tags wt WHERE wt.item_id = wi.id AND wt.tag = $${params.length})`,
    );
  }
  if (filters.search && filters.search.trim()) {
    params.push(`%${filters.search.trim().replace(/[%_]/g, (m) => `\\${m}`)}%`);
    where.push(`(wi.title ILIKE $${params.length} OR wi.description ILIKE $${params.length})`);
  }

  let sql = `${ITEM_SELECT} WHERE ${where.join(' AND ')} ORDER BY wi.board_rank ASC, wi.id ASC`;
  if (filters.limit !== undefined) {
    params.push(Math.min(Math.max(filters.limit, 1), 500));
    sql += ` LIMIT $${params.length}`;
  }
  if (filters.offset) {
    params.push(Math.max(filters.offset, 0));
    sql += ` OFFSET $${params.length}`;
  }

  return (await query<WorkItemRow>(sql, params)).map(mapWorkItem);
}

export async function countWorkItems(filters: WorkItemFilters = {}): Promise<number> {
  const rows = await listWorkItems({ ...filters, limit: undefined, offset: undefined });
  return rows.length;
}

export async function getWorkItem(id: number): Promise<WorkItem | null> {
  const row = await queryOne<WorkItemRow>(
    `${ITEM_SELECT} WHERE wi.id = $1 AND wi.instance_key = $2`,
    [id, instance()],
  );
  return row ? mapWorkItem(row) : null;
}

/** Finds the item a branch belongs to (webhook/poll join key). */
export async function findItemByBranch(
  repoFullName: string,
  branch: string,
): Promise<WorkItem | null> {
  const row = await queryOne<WorkItemRow>(
    `${ITEM_SELECT}
      WHERE wi.instance_key = $1 AND wi.branch_repo = $2 AND wi.branch_name = $3
      LIMIT 1`,
    [instance(), repoFullName, branch],
  );
  return row ? mapWorkItem(row) : null;
}

export async function findItemsByPullRequest(
  repoFullName: string,
  prNumber: number,
): Promise<WorkItem[]> {
  const rows = await query<WorkItemRow>(
    `${ITEM_SELECT}
      WHERE wi.instance_key = $1
        AND EXISTS (
          SELECT 1 FROM pull_request_links pl
           WHERE pl.item_id = wi.id AND pl.repo_full_name = $2 AND pl.pr_number = $3
        )`,
    [instance(), repoFullName, prNumber],
  );
  return rows.map(mapWorkItem);
}

async function logActivity(
  client: { query: (sql: string, params?: unknown[]) => Promise<unknown> },
  itemId: number,
  actor: Actor,
  field: string,
  oldValue: string | null,
  newValue: string | null,
): Promise<void> {
  await client.query(
    `INSERT INTO activity (item_id, actor_login, source, field, old_value, new_value, note)
     VALUES ($1,$2,$3,$4,$5,$6,$7)`,
    [itemId, actor.login, actor.source, field, oldValue, newValue, actor.note ?? null],
  );
}

export async function createWorkItem(
  raw: CreateWorkItemInput,
  actorLike: ActorLike,
): Promise<WorkItem> {
  const actor = toActor(actorLike);
  // Parse here so defaults are applied exactly once, wherever the call
  // originated (UI, API, bulk seed, tests).
  const input = createWorkItemSchema.parse(raw);
  return withTransaction(async (client) => {
    const { rows: rankRows } = await client.query<{ min: number | null }>(
      'SELECT MIN(board_rank) AS min FROM work_items WHERE instance_key = $1 AND state = $2',
      [instance(), input.state],
    );
    const rank = (rankRows[0]?.min ?? 0) - 1;

    const { rows } = await client.query<{ id: number }>(
      `INSERT INTO work_items
         (instance_key, title, description, item_type, state, assignee_login,
          assignee_avatar_url, story_points, priority, sprint_id, board_rank,
          created_by, repo_full_name, wave, closed_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
               CASE WHEN $5 = 'Closed' THEN now() ELSE NULL END)
       RETURNING id`,
      [
        instance(),
        input.title,
        input.description,
        input.itemType,
        input.state,
        input.assigneeLogin,
        input.assigneeAvatarUrl,
        input.storyPoints,
        input.priority,
        input.sprintId,
        rank,
        actor.login,
        input.repoFullName ?? defaultRepoForItem(),
        input.wave,
      ],
    );
    const id = rows[0]!.id;

    await replaceTags(client, id, input.tags);
    await logActivity(client, id, actor, 'created', null, input.title);

    const { rows: created } = await client.query<WorkItemRow>(
      `${ITEM_SELECT} WHERE wi.id = $1`,
      [id],
    );
    return mapWorkItem(created[0]!);
  });
}

/**
 * A single-repo board leaves the item's repo implicit rather than nagging the
 * user with a picker they do not need; a multi-repo board requires it.
 */
function defaultRepoForItem(): string | null {
  return config.githubRepos.length === 1 ? config.githubRepos[0]! : null;
}

const UPDATABLE: Record<string, string> = {
  title: 'title',
  description: 'description',
  itemType: 'item_type',
  state: 'state',
  assigneeLogin: 'assignee_login',
  assigneeAvatarUrl: 'assignee_avatar_url',
  storyPoints: 'story_points',
  priority: 'priority',
  sprintId: 'sprint_id',
  repoFullName: 'repo_full_name',
  wave: 'wave',
};

export async function updateWorkItem(
  id: number,
  input: UpdateWorkItemInput,
  actorLike: ActorLike,
): Promise<WorkItem | null> {
  const actor = toActor(actorLike);
  return withTransaction(async (client) => {
    const { rows: existingRows } = await client.query<WorkItemRow>(
      'SELECT * FROM work_items WHERE id = $1 AND instance_key = $2 FOR UPDATE',
      [id, instance()],
    );
    const existing = existingRows[0];
    if (!existing) return null;

    if (input.state !== undefined) {
      assertTransition(existing.state as WorkItemState, input.state);
    }

    const sets: string[] = [];
    const params: unknown[] = [];
    const changes: Array<[string, string | null, string | null]> = [];

    for (const [key, column] of Object.entries(UPDATABLE)) {
      const value = (input as Record<string, unknown>)[key];
      if (value === undefined) continue;
      params.push(value);
      sets.push(`${column} = $${params.length}`);
      const before = (existing as unknown as Record<string, unknown>)[column];
      if (String(before ?? '') !== String(value ?? '')) {
        changes.push([
          key,
          before === null || before === undefined ? null : String(before),
          value === null ? null : String(value),
        ]);
      }
    }

    if (input.state !== undefined) {
      sets.push(input.state === 'Closed' ? 'closed_at = now()' : 'closed_at = NULL');
    }

    if (sets.length) {
      sets.push('updated_at = now()');
      params.push(id);
      await client.query(
        `UPDATE work_items SET ${sets.join(', ')} WHERE id = $${params.length}`,
        params,
      );
    }

    if (input.tags !== undefined) await replaceTags(client, id, input.tags);

    for (const [field, oldValue, newValue] of changes) {
      await logActivity(client, id, actor, field, oldValue, newValue);
    }

    const { rows } = await client.query<WorkItemRow>(`${ITEM_SELECT} WHERE wi.id = $1`, [id]);
    return rows[0] ? mapWorkItem(rows[0]) : null;
  });
}

export async function deleteWorkItem(id: number): Promise<boolean> {
  const rows = await query<{ id: number }>(
    'DELETE FROM work_items WHERE id = $1 AND instance_key = $2 RETURNING id',
    [id, instance()],
  );
  return rows.length > 0;
}

export async function moveWorkItem(
  id: number,
  toState: WorkItemState,
  orderedIds: number[],
  actorLike: ActorLike,
): Promise<WorkItem | null> {
  const actor = toActor(actorLike);
  return withTransaction(async (client) => {
    const { rows } = await client.query<{ state: string }>(
      'SELECT state FROM work_items WHERE id = $1 AND instance_key = $2 FOR UPDATE',
      [id, instance()],
    );
    const current = rows[0];
    if (!current) return null;

    const from = current.state as WorkItemState;
    assertTransition(from, toState);

    if (from !== toState) {
      await client.query(
        `UPDATE work_items
            SET state = $1, updated_at = now(),
                closed_at = CASE WHEN $1 = 'Closed' THEN now() ELSE NULL END
          WHERE id = $2`,
        [toState, id],
      );
      await logActivity(client, id, actor, 'state', from, toState);
    }

    const ids = orderedIds.filter((n) => Number.isInteger(n));
    if (ids.length) {
      await client.query(
        `UPDATE work_items AS w
            SET board_rank = v.rank
           FROM (SELECT * FROM unnest($1::int[], $2::float8[]) AS t(id, rank)) AS v
          WHERE w.id = v.id AND w.state = $3 AND w.instance_key = $4`,
        [ids, ids.map((_, i) => i), toState, instance()],
      );
    }

    const { rows: out } = await client.query<WorkItemRow>(`${ITEM_SELECT} WHERE wi.id = $1`, [id]);
    return out[0] ? mapWorkItem(out[0]) : null;
  });
}

async function replaceTags(
  client: { query: (sql: string, params?: unknown[]) => Promise<unknown> },
  itemId: number,
  tags: string[],
): Promise<void> {
  await client.query('DELETE FROM work_item_tags WHERE item_id = $1', [itemId]);
  const unique = [...new Set(tags.map((t) => t.trim()).filter(Boolean))];
  if (!unique.length) return;
  await client.query(
    `INSERT INTO work_item_tags (item_id, tag)
     SELECT $1, unnest($2::text[]) ON CONFLICT DO NOTHING`,
    [itemId, unique],
  );
}

// ---------------------------------------------------------------- branches

export async function setItemBranch(
  itemId: number,
  branch: { repoFullName: string; name: string; url: string },
  actorLike: ActorLike,
): Promise<WorkItem | null> {
  const actor = toActor(actorLike);
  return withTransaction(async (client) => {
    const { rows } = await client.query<{ branch_name: string | null }>(
      'SELECT branch_name FROM work_items WHERE id = $1 AND instance_key = $2 FOR UPDATE',
      [itemId, instance()],
    );
    if (!rows[0]) return null;

    await client.query(
      `UPDATE work_items
          SET branch_repo = $1, branch_name = $2, branch_url = $3,
              branch_created_at = COALESCE(branch_created_at, now()), updated_at = now()
        WHERE id = $4`,
      [branch.repoFullName, branch.name, branch.url, itemId],
    );

    if (rows[0].branch_name !== branch.name) {
      await logActivity(client, itemId, actor, 'branch', rows[0].branch_name, branch.name);
    }

    const { rows: out } = await client.query<WorkItemRow>(`${ITEM_SELECT} WHERE wi.id = $1`, [itemId]);
    return out[0] ? mapWorkItem(out[0]) : null;
  });
}

// ----------------------------------------------------------------- commits

export async function recordCommits(
  itemId: number,
  repoFullName: string,
  branch: string,
  commits: Array<{
    sha: string;
    message: string;
    authorLogin: string | null;
    authorName: string;
    url: string;
    committedAt: string;
  }>,
): Promise<number> {
  if (!commits.length) return 0;
  let inserted = 0;
  for (const c of commits) {
    const rows = await query<{ id: number }>(
      `INSERT INTO item_commits
         (item_id, repo_full_name, sha, message, author_login, author_name, url, branch, committed_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
       ON CONFLICT (item_id, repo_full_name, sha) DO NOTHING
       RETURNING id`,
      [itemId, repoFullName, c.sha, c.message, c.authorLogin, c.authorName, c.url, branch, c.committedAt],
    );
    if (rows.length) inserted++;
  }
  if (inserted) {
    await query('UPDATE work_items SET updated_at = now() WHERE id = $1', [itemId]);
  }
  return inserted;
}

export async function countItemCommits(itemId: number): Promise<number> {
  const row = await queryOne<{ n: string }>(
    'SELECT COUNT(*) AS n FROM item_commits WHERE item_id = $1',
    [itemId],
  );
  return Number(row?.n ?? 0);
}

// ------------------------------------------------------------------ sprints

export async function listSprints(): Promise<Sprint[]> {
  const rows = await query<SprintRow>(
    `SELECT s.*,
            (SELECT COUNT(*) FROM work_items wi
              WHERE wi.sprint_id = s.id AND wi.state <> 'Removed') AS item_count
       FROM sprints s
      WHERE s.instance_key = $1
      ORDER BY s.position ASC, s.starts_on ASC, s.id ASC`,
    [instance()],
  );
  return rows.map(mapSprint);
}

export async function getSprint(id: number): Promise<Sprint | null> {
  const row = await queryOne<SprintRow>(
    'SELECT * FROM sprints WHERE id = $1 AND instance_key = $2',
    [id, instance()],
  );
  return row ? mapSprint(row) : null;
}

export async function createSprint(raw: SprintInput): Promise<Sprint> {
  const input = sprintSchema.parse(raw);
  const row = await queryOne<SprintRow>(
    `INSERT INTO sprints (instance_key, name, goal, starts_on, ends_on, position)
     VALUES ($1,$2,$3,$4,$5,
             COALESCE(NULLIF($6, 0),
                      (SELECT COALESCE(MAX(position), 0) + 1 FROM sprints WHERE instance_key = $1)))
     RETURNING *`,
    [instance(), input.name, input.goal, input.startsOn, input.endsOn, input.position],
  );
  return mapSprint(row!);
}

export async function updateSprint(id: number, raw: SprintInput): Promise<Sprint | null> {
  const input = sprintSchema.parse(raw);
  const row = await queryOne<SprintRow>(
    `UPDATE sprints SET name=$1, goal=$2, starts_on=$3, ends_on=$4,
                        position=COALESCE(NULLIF($5, 0), position), updated_at=now()
      WHERE id=$6 AND instance_key=$7 RETURNING *`,
    [input.name, input.goal, input.startsOn, input.endsOn, input.position, id, instance()],
  );
  return row ? mapSprint(row) : null;
}

export async function deleteSprint(id: number): Promise<boolean> {
  const rows = await query<{ id: number }>(
    'DELETE FROM sprints WHERE id = $1 AND instance_key = $2 RETURNING id',
    [id, instance()],
  );
  return rows.length > 0;
}

export interface SprintStats {
  sprintId: number;
  total: number;
  done: number;
  points: number;
  donePoints: number;
}

export async function sprintStats(sprintId: number): Promise<SprintStats> {
  const row = await queryOne<{
    total: string;
    done: string;
    points: string | null;
    done_points: string | null;
  }>(
    `SELECT COUNT(*)                                      AS total,
            COUNT(*) FILTER (WHERE state = 'Closed')      AS done,
            COALESCE(SUM(story_points), 0)                AS points,
            COALESCE(SUM(story_points) FILTER (WHERE state = 'Closed'), 0) AS done_points
       FROM work_items
      WHERE sprint_id = $1 AND instance_key = $2 AND state <> 'Removed'`,
    [sprintId, instance()],
  );
  return {
    sprintId,
    total: Number(row?.total ?? 0),
    done: Number(row?.done ?? 0),
    points: Number(row?.points ?? 0),
    donePoints: Number(row?.done_points ?? 0),
  };
}

// ------------------------------------------------------------ PR links

export interface PrLinkInput {
  repoFullName: string;
  prNumber: number;
  url: string;
  title: string;
  prState: string;
  merged: boolean;
  draft: boolean;
  checksState: string | null;
  headRef?: string;
  baseRef?: string;
  behindBy?: number | null;
}

export async function linkPullRequest(
  itemId: number,
  pr: PrLinkInput,
  actorLike: ActorLike,
): Promise<PullRequestLink> {
  const actor = toActor(actorLike);
  const row = await queryOne<PullRequestLinkRow>(
    `INSERT INTO pull_request_links
       (item_id, repo_full_name, pr_number, url, title, pr_state, merged, draft,
        head_ref, base_ref, checks_state, behind_by, linked_by, last_synced_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13, now())
     ON CONFLICT (item_id, repo_full_name, pr_number) DO UPDATE
       SET title = EXCLUDED.title, pr_state = EXCLUDED.pr_state,
           merged = EXCLUDED.merged, draft = EXCLUDED.draft,
           head_ref = EXCLUDED.head_ref, base_ref = EXCLUDED.base_ref,
           checks_state = EXCLUDED.checks_state, behind_by = EXCLUDED.behind_by,
           last_synced_at = now()
     RETURNING *`,
    [
      itemId, pr.repoFullName, pr.prNumber, pr.url, pr.title, pr.prState, pr.merged, pr.draft,
      pr.headRef ?? '', pr.baseRef ?? '', pr.checksState, pr.behindBy ?? null, actor.login,
    ],
  );
  return mapPullRequest(row!);
}

/**
 * Every pull request attached to an item on this board, open and merged alike.
 *
 * This is the SAME source `boardSummary` counts (`pull_request_links`), which
 * is the point: board bug AB#29 was `/api/v1/prs` reading GitHub's open-PR list
 * instead, so the endpoint and the summary could not agree by construction.
 *
 * Scoped by `instance_key` through the item, exactly like the summary's merged
 * count -- including items in `Removed`, because the summary counts those too
 * and one endpoint quietly filtering differently is how the two drift again.
 */
export async function listLinkedPullRequests(): Promise<LinkedPullRequest[]> {
  const rows = await query<PullRequestLinkRow & { item_title: string }>(
    `SELECT pl.*, wi.title AS item_title
       FROM pull_request_links pl
       JOIN work_items wi ON wi.id = pl.item_id
      WHERE wi.instance_key = $1
      ORDER BY pl.last_synced_at DESC NULLS LAST, pl.repo_full_name ASC, pl.pr_number DESC`,
    [instance()],
  );
  return rows.map((row) => ({ ...mapPullRequest(row), itemTitle: row.item_title }));
}

export async function recordPrLinkActivity(
  itemId: number,
  actorLike: ActorLike,
  prNumber: number,
  repoFullName: string,
): Promise<void> {
  const actor = toActor(actorLike);
  await query(
    `INSERT INTO activity (item_id, actor_login, source, field, old_value, new_value, note)
     VALUES ($1,$2,$3,'pull_request',NULL,$4,$5)`,
    [itemId, actor.login, actor.source, `${repoFullName}#${prNumber}`, actor.note ?? null],
  );
}

export async function unlinkPullRequest(itemId: number, linkId: number): Promise<boolean> {
  const rows = await query<{ id: number }>(
    'DELETE FROM pull_request_links WHERE id = $1 AND item_id = $2 RETURNING id',
    [linkId, itemId],
  );
  return rows.length > 0;
}

export async function setBacklinkCommentId(
  itemId: number,
  repoFullName: string,
  prNumber: number,
  commentId: number,
): Promise<void> {
  await query(
    `UPDATE pull_request_links SET backlink_comment_id = $1
      WHERE item_id = $2 AND repo_full_name = $3 AND pr_number = $4`,
    [commentId, itemId, repoFullName, prNumber],
  );
}

// -------------------------------------------------------- comments/activity

export async function listComments(itemId: number): Promise<Comment[]> {
  const rows = await query<CommentRow>(
    'SELECT * FROM comments WHERE item_id = $1 ORDER BY created_at ASC, id ASC',
    [itemId],
  );
  return rows.map(mapComment);
}

export async function addComment(
  itemId: number,
  author: { login: string; avatarUrl: string | null },
  body: string,
): Promise<Comment> {
  const row = await queryOne<CommentRow>(
    `INSERT INTO comments (item_id, author_login, author_avatar_url, body)
     VALUES ($1,$2,$3,$4) RETURNING *`,
    [itemId, author.login, author.avatarUrl, body],
  );
  return mapComment(row!);
}

export async function listActivity(itemId: number, limit = 100): Promise<ActivityEntry[]> {
  const rows = await query<ActivityRow>(
    'SELECT * FROM activity WHERE item_id = $1 ORDER BY created_at DESC, id DESC LIMIT $2',
    [itemId, limit],
  );
  return rows.map(mapActivity);
}

// --------------------------------------------------------------- attachments

export async function listAttachments(itemId: number): Promise<Attachment[]> {
  const rows = await query<AttachmentRow>(
    'SELECT * FROM attachments WHERE item_id = $1 ORDER BY created_at ASC, id ASC',
    [itemId],
  );
  return rows.map(mapAttachment);
}

export async function recordAttachment(
  itemId: number,
  meta: {
    objectKey: string;
    filename: string;
    contentType: string;
    sizeBytes: number;
    uploadedBy: string;
  },
): Promise<Attachment> {
  const row = await queryOne<AttachmentRow>(
    `INSERT INTO attachments (item_id, object_key, filename, content_type, size_bytes, uploaded_by)
     VALUES ($1,$2,$3,$4,$5,$6) RETURNING *`,
    [itemId, meta.objectKey, meta.filename, meta.contentType, meta.sizeBytes, meta.uploadedBy],
  );
  return mapAttachment(row!);
}

export async function getAttachment(
  itemId: number,
  attachmentId: number,
): Promise<{ id: number; objectKey: string; filename: string; contentType: string } | null> {
  const row = await queryOne<{
    id: number;
    object_key: string;
    filename: string;
    content_type: string;
  }>('SELECT id, object_key, filename, content_type FROM attachments WHERE id = $1 AND item_id = $2', [
    attachmentId,
    itemId,
  ]);
  return row
    ? { id: row.id, objectKey: row.object_key, filename: row.filename, contentType: row.content_type }
    : null;
}

export async function deleteAttachment(itemId: number, attachmentId: number): Promise<string | null> {
  const rows = await query<{ object_key: string }>(
    'DELETE FROM attachments WHERE id = $1 AND item_id = $2 RETURNING object_key',
    [attachmentId, itemId],
  );
  return rows[0]?.object_key ?? null;
}
