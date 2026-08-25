import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

// Env must be installed before any module reads it.
const SCHEMA = 'agile_test';
installTestEnv(SCHEMA);

const d = hasDb ? describe : describe.skip;

d('data layer (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    const migrate = await import('@/lib/db/migrate');
    // Start from a clean schema every run so tests are order-independent.
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    const applied = await migrate.runMigrations();
    expect(applied).toContain('001_init.sql');
    q = await import('@/lib/domain/queries');
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  it('runs migrations idempotently — a second run applies nothing', async () => {
    const migrate = await import('@/lib/db/migrate');
    const second = await migrate.runMigrations();
    expect(second).toEqual([]);
  });

  it('creates its objects inside the dedicated schema, not public', async () => {
    const rows = await db.query<{ table_name: string }>(
      `SELECT table_name FROM information_schema.tables WHERE table_schema = $1 ORDER BY table_name`,
      [SCHEMA],
    );
    const names = rows.map((r) => r.table_name);
    expect(names).toEqual(
      expect.arrayContaining([
        'activity',
        'api_tokens',
        'attachments',
        'comments',
        'idempotency_keys',
        'item_commits',
        'poll_state',
        'pull_request_links',
        'schema_migrations',
        'sprints',
        'webhook_deliveries',
        'work_item_tags',
        'work_items',
      ]),
    );

    const leaked = await db.query<{ table_name: string }>(
      `SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name IN ('work_items','sprints','comments')`,
    );
    expect(leaked).toEqual([]);
  });

  it('creates a work item with tags and reads it back', async () => {
    const item = await q.createWorkItem(
      {
        title: 'Ingest transcripts',
        description: '## Goal\nParse the corpus.',
        itemType: 'Story',
        state: 'New',
        assigneeLogin: 'octocat',
        assigneeAvatarUrl: 'https://example.test/a.png',
        storyPoints: 5,
        priority: 1,
        sprintId: null,
        tags: ['backend', 'ingest'],
      },
      'octocat',
    );

    expect(item.id).toBeGreaterThan(0);
    expect(item.title).toBe('Ingest transcripts');
    expect(item.tags).toEqual(['backend', 'ingest']);
    expect(item.state).toBe('New');
    expect(item.pullRequests).toEqual([]);

    const fetched = await q.getWorkItem(item.id);
    expect(fetched).toMatchObject({ id: item.id, storyPoints: 5, priority: 1 });
  });

  it('records an activity entry on create and on field changes', async () => {
    const item = await q.createWorkItem(
      { title: 'Activity check', description: '', itemType: 'Task', state: 'New',
        assigneeLogin: null, assigneeAvatarUrl: null, storyPoints: null, priority: 2,
        sprintId: null, tags: [] },
      'alice',
    );
    await q.updateWorkItem(item.id, { title: 'Renamed', priority: 4 }, 'bob');

    const log = await q.listActivity(item.id);
    const fields = log.map((a) => a.field);
    expect(fields).toContain('created');
    expect(fields).toContain('title');
    expect(fields).toContain('priority');

    const titleChange = log.find((a) => a.field === 'title');
    expect(titleChange).toMatchObject({
      actorLogin: 'bob',
      oldValue: 'Activity check',
      newValue: 'Renamed',
    });
  });

  it('rejects an illegal state transition at the data layer', async () => {
    const item = await q.createWorkItem(
      { title: 'Illegal move', description: '', itemType: 'Bug', state: 'New',
        assigneeLogin: null, assigneeAvatarUrl: null, storyPoints: null, priority: 2,
        sprintId: null, tags: [] },
      'alice',
    );

    await expect(q.updateWorkItem(item.id, { state: 'Closed' }, 'alice')).rejects.toThrow(
      /Cannot move a work item from "New" to "Closed"/,
    );

    // ...and the item is unchanged (the transaction rolled back).
    expect((await q.getWorkItem(item.id))?.state).toBe('New');
  });

  it('stamps closed_at when an item reaches Closed and clears it on reactivate', async () => {
    const item = await q.createWorkItem(
      { title: 'Closing time', description: '', itemType: 'Task', state: 'New',
        assigneeLogin: null, assigneeAvatarUrl: null, storyPoints: null, priority: 2,
        sprintId: null, tags: [] },
      'alice',
    );
    await q.updateWorkItem(item.id, { state: 'Active' }, 'alice');
    await q.updateWorkItem(item.id, { state: 'Resolved' }, 'alice');
    const closed = await q.updateWorkItem(item.id, { state: 'Closed' }, 'alice');
    expect(closed?.closedAt).not.toBeNull();

    const reopened = await q.updateWorkItem(item.id, { state: 'Active' }, 'alice');
    expect(reopened?.state).toBe('Active');
    expect(reopened?.closedAt).toBeNull();
  });

  it('replaces tags wholesale on update and de-duplicates them', async () => {
    const item = await q.createWorkItem(
      { title: 'Tagged', description: '', itemType: 'Story', state: 'New',
        assigneeLogin: null, assigneeAvatarUrl: null, storyPoints: null, priority: 2,
        sprintId: null, tags: ['a', 'b'] },
      'alice',
    );
    const updated = await q.updateWorkItem(item.id, { tags: ['c', 'c', 'a'] }, 'alice');
    expect(updated?.tags).toEqual(['a', 'c']);
  });

  it('moves an item between columns and persists the new order', async () => {
    const mk = (title: string) =>
      q.createWorkItem(
        { title, description: '', itemType: 'Task', state: 'New', assigneeLogin: null,
          assigneeAvatarUrl: null, storyPoints: null, priority: 2, sprintId: null, tags: [] },
        'alice',
      );
    const a = await mk('move-a');
    const b = await mk('move-b');

    await q.moveWorkItem(a.id, 'Active', [a.id], 'alice');
    await q.moveWorkItem(b.id, 'Active', [b.id, a.id], 'alice');

    const active = await q.listWorkItems({ state: 'Active' });
    const order = active.filter((i) => [a.id, b.id].includes(i.id)).map((i) => i.id);
    expect(order).toEqual([b.id, a.id]);

    const log = await q.listActivity(a.id);
    expect(log.some((e) => e.field === 'state' && e.newValue === 'Active')).toBe(true);
  });

  it('refuses an illegal move and leaves state untouched', async () => {
    const item = await q.createWorkItem(
      { title: 'no skipping', description: '', itemType: 'Task', state: 'New',
        assigneeLogin: null, assigneeAvatarUrl: null, storyPoints: null, priority: 2,
        sprintId: null, tags: [] },
      'alice',
    );
    await expect(q.moveWorkItem(item.id, 'Resolved', [item.id], 'alice')).rejects.toThrow();
    expect((await q.getWorkItem(item.id))?.state).toBe('New');
  });

  it('filters the backlog by sprint, assignee and free text', async () => {
    const sprint = await q.createSprint({
      name: `Sprint ${Date.now()}`,
      goal: 'ship it',
      startsOn: '2026-09-01',
      endsOn: '2026-09-14',
    });

    const inSprint = await q.createWorkItem(
      { title: 'Vector search spike', description: 'pgvector', itemType: 'Spike', state: 'New',
        assigneeLogin: 'carol', assigneeAvatarUrl: null, storyPoints: 3, priority: 2,
        sprintId: sprint.id, tags: [] },
      'alice',
    );

    expect((await q.listWorkItems({ sprintId: sprint.id })).map((i) => i.id)).toEqual([inSprint.id]);
    expect((await q.listWorkItems({ assignee: 'carol' })).map((i) => i.id)).toContain(inSprint.id);
    expect((await q.listWorkItems({ search: 'vector search' })).map((i) => i.id)).toContain(inSprint.id);
    expect((await q.listWorkItems({ search: 'pgvector' })).map((i) => i.id)).toContain(inSprint.id);
    expect((await q.listWorkItems({ search: 'nothing-matches-this' }))).toEqual([]);

    const stats = await q.sprintStats(sprint.id);
    expect(stats).toMatchObject({ sprintId: sprint.id, total: 1, done: 0, points: 3, donePoints: 0 });
  });

  it('hides Removed items from the default listing but finds them when asked', async () => {
    const item = await q.createWorkItem(
      { title: 'to be removed', description: '', itemType: 'Task', state: 'New',
        assigneeLogin: null, assigneeAvatarUrl: null, storyPoints: null, priority: 2,
        sprintId: null, tags: [] },
      'alice',
    );
    await q.updateWorkItem(item.id, { state: 'Removed' }, 'alice');

    expect((await q.listWorkItems()).map((i) => i.id)).not.toContain(item.id);
    expect((await q.listWorkItems({ includeRemoved: true })).map((i) => i.id)).toContain(item.id);
  });

  it('links a PR, upserts it on relink, and unlinks it', async () => {
    const item = await q.createWorkItem(
      { title: 'PR linking', description: '', itemType: 'Story', state: 'New',
        assigneeLogin: null, assigneeAvatarUrl: null, storyPoints: null, priority: 2,
        sprintId: null, tags: [] },
      'alice',
    );

    const pr = {
      repoFullName: 'UA-MIS/ida-llm',
      prNumber: 42,
      url: 'https://github.com/UA-MIS/ida-llm/pull/42',
      title: 'Add ingest pipeline',
      prState: 'open',
      merged: false,
      draft: false,
      checksState: 'pending',
    };
    const link = await q.linkPullRequest(item.id, pr, 'alice');
    expect(link).toMatchObject({ prNumber: 42, prState: 'open', merged: false });

    // Re-linking the same PR updates in place rather than duplicating.
    const relinked = await q.linkPullRequest(
      item.id,
      { ...pr, prState: 'closed', merged: true, checksState: 'success' },
      'alice',
    );
    expect(relinked.id).toBe(link.id);
    expect(relinked.merged).toBe(true);

    const withPr = await q.getWorkItem(item.id);
    expect(withPr?.pullRequests).toHaveLength(1);
    expect(withPr?.pullRequests[0]).toMatchObject({ prNumber: 42, merged: true });

    expect(await q.unlinkPullRequest(item.id, link.id)).toBe(true);
    expect((await q.getWorkItem(item.id))?.pullRequests).toEqual([]);
  });

  it('cascades deletes to tags, PR links, comments and activity', async () => {
    const item = await q.createWorkItem(
      { title: 'cascade', description: '', itemType: 'Task', state: 'New',
        assigneeLogin: null, assigneeAvatarUrl: null, storyPoints: null, priority: 2,
        sprintId: null, tags: ['x'] },
      'alice',
    );
    await q.linkPullRequest(
      item.id,
      { repoFullName: 'UA-MIS/ida-llm', prNumber: 7, url: 'u', title: 't', prState: 'open',
        merged: false, draft: false, checksState: null },
      'alice',
    );
    await q.addComment(item.id, { login: 'alice', avatarUrl: null }, 'looks good');

    expect(await q.deleteWorkItem(item.id)).toBe(true);
    expect(await q.getWorkItem(item.id)).toBeNull();

    for (const table of ['work_item_tags', 'pull_request_links', 'comments', 'activity']) {
      const left = await db.query<{ n: string }>(
        `SELECT COUNT(*) AS n FROM ${table} WHERE item_id = $1`,
        [item.id],
      );
      expect(Number(left[0]!.n), `${table} should be empty`).toBe(0);
    }
  });

  it('detaches items from a deleted sprint instead of deleting them', async () => {
    const sprint = await q.createSprint({
      name: `Doomed ${Date.now()}`, goal: '', startsOn: '2026-10-01', endsOn: '2026-10-14',
    });
    const item = await q.createWorkItem(
      { title: 'survivor', description: '', itemType: 'Task', state: 'New', assigneeLogin: null,
        assigneeAvatarUrl: null, storyPoints: null, priority: 2, sprintId: sprint.id, tags: [] },
      'alice',
    );

    expect(await q.deleteSprint(sprint.id)).toBe(true);
    const after = await q.getWorkItem(item.id);
    expect(after).not.toBeNull();
    expect(after?.sprintId).toBeNull();
  });

  it('stores and lists comments chronologically', async () => {
    const item = await q.createWorkItem(
      { title: 'discuss', description: '', itemType: 'Story', state: 'New', assigneeLogin: null,
        assigneeAvatarUrl: null, storyPoints: null, priority: 2, sprintId: null, tags: [] },
      'alice',
    );
    await q.addComment(item.id, { login: 'alice', avatarUrl: null }, 'first');
    await q.addComment(item.id, { login: 'bob', avatarUrl: null }, 'second');

    const comments = await q.listComments(item.id);
    expect(comments.map((c) => c.body)).toEqual(['first', 'second']);
    expect(comments[1]?.authorLogin).toBe('bob');
  });

  it('rejects a sprint whose end date precedes its start date', async () => {
    await expect(
      q.createSprint({ name: `Bad ${Date.now()}`, goal: '', startsOn: '2026-10-10', endsOn: '2026-10-01' }),
    ).rejects.toThrow();
  });

  it('rejects a blank work item title at the database level', async () => {
    await expect(
      q.createWorkItem(
        { title: '   ', description: '', itemType: 'Task', state: 'New', assigneeLogin: null,
          assigneeAvatarUrl: null, storyPoints: null, priority: 2, sprintId: null, tags: [] },
        'alice',
      ),
    ).rejects.toThrow();
  });
});
