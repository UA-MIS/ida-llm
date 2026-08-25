import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_branch_metadata_test';
installTestEnv(SCHEMA);
const d = hasDb ? describe : describe.skip;

const REPO = 'UA-MIS/ida-llm';

/**
 * Branch metadata (name, url, created-at) could be written but never cleared.
 * It is not a writable PATCH field, and nothing reacted to a branch going away,
 * so item 25 — an OPEN research card the team looks at daily — kept advertising
 * a `spike/25-...` branch that had already been deleted and 404s.
 */
d('branch metadata can be cleared (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');
  let engine: typeof import('@/lib/sync/engine');

  const STORY = {
    title: 'Port the skeleton',
    description: '',
    itemType: 'Story' as const,
    state: 'New' as const,
    assigneeLogin: null,
    assigneeAvatarUrl: null,
    storyPoints: 5,
    priority: 1,
    sprintId: null,
    tags: [],
    repoFullName: REPO,
    wave: null,
  };

  /** An item that has been through "Start work" and has a branch. */
  async function itemWithBranch(name: string, overrides: Partial<typeof STORY> = {}) {
    const item = await q.createWorkItem({ ...STORY, ...overrides }, 'tester');
    const withBranch = await q.setItemBranch(
      item.id,
      { repoFullName: REPO, name, url: `https://github.com/${REPO}/tree/${name}` },
      'tester',
    );
    expect(withBranch?.branchName).toBe(name);
    return withBranch!;
  }

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();
    q = await import('@/lib/domain/queries');
    engine = await import('@/lib/sync/engine');
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  it('clearItemBranch nulls every branch column', async () => {
    const item = await itemWithBranch('story/100-port-the-skeleton');

    const cleared = await q.clearItemBranch(item.id, 'tester');

    expect(cleared?.branchName).toBeNull();
    expect(cleared?.branchRepo).toBeNull();
    expect(cleared?.branchUrl).toBeNull();
    expect(cleared?.branchCreatedAt).toBeNull();
  });

  it('records the clear in the item history, so it is never a silent change', async () => {
    const item = await itemWithBranch('story/101-history');
    await q.clearItemBranch(item.id, { login: 'github', source: 'github', note: 'branch deleted' });

    const entry = (await q.listActivity(item.id)).find(
      (a) => a.field === 'branch' && a.newValue === null,
    );
    expect(entry, 'a branch-cleared entry must exist').toBeTruthy();
    expect(entry?.oldValue).toBe('story/101-history');
    expect(entry?.note).toBe('branch deleted');
  });

  it('is idempotent — clearing an item with no branch changes and logs nothing', async () => {
    const item = await q.createWorkItem(STORY, 'tester');
    const before = (await q.listActivity(item.id)).length;

    const cleared = await q.clearItemBranch(item.id, 'tester');

    expect(cleared?.id).toBe(item.id);
    expect(cleared?.branchName).toBeNull();
    expect((await q.listActivity(item.id)).length).toBe(before);
  });

  it('returns null for an item that does not exist', async () => {
    expect(await q.clearItemBranch(999_999, 'tester')).toBeNull();
  });

  // ---------------------------------------------------------------- webhook

  it('the branch-delete webhook clears the item that owned the branch', async () => {
    const item = await itemWithBranch('story/102-deleted-on-merge');

    const outcome = await engine.handleBranchDeleted(REPO, 'story/102-deleted-on-merge');

    expect(outcome.itemsTouched).toContain(item.id);
    const after = await q.getWorkItem(item.id);
    expect(after?.branchName).toBeNull();
    expect(after?.branchUrl).toBeNull();
    expect(after?.branchCreatedAt).toBeNull();
  });

  it('keeps the commits and PR links — only the dead pointer goes', async () => {
    const item = await itemWithBranch('story/103-real-work');
    await q.recordCommits(item.id, REPO, 'story/103-real-work', [
      {
        sha: 'deadbeef',
        message: 'real work',
        authorLogin: 'ccsmith33',
        authorName: 'Clayton',
        url: `https://github.com/${REPO}/commit/deadbeef`,
        committedAt: '2026-08-25T12:00:00Z',
      },
    ]);

    await engine.handleBranchDeleted(REPO, 'story/103-real-work');

    const after = await q.getWorkItem(item.id);
    expect(after?.branchName).toBeNull();
    // The record of what happened survives the ref that carried it.
    expect(after?.commitCount).toBe(1);
  });

  it('ignores a branch no item owns, and a repo the board does not follow', async () => {
    expect((await engine.handleBranchDeleted(REPO, 'nobody/owns-this')).itemsTouched).toEqual([]);
    const item = await itemWithBranch('story/104-other-repo');
    expect(
      (await engine.handleBranchDeleted('someone/else', 'story/104-other-repo')).itemsTouched,
    ).toEqual([]);
    expect((await q.getWorkItem(item.id))?.branchName).toBe('story/104-other-repo');
  });

  // ------------------------------------------------------- back to New

  it('releases an UNUSED branch when the item is sent back to New', async () => {
    const item = await itemWithBranch('story/105-abandoned');
    await q.updateWorkItem(item.id, { state: 'Active' }, 'tester');

    const back = await q.updateWorkItem(item.id, { state: 'New' }, 'tester');

    expect(back?.state).toBe('New');
    expect(back?.branchName).toBeNull();
  });

  it('releases it on a board DRAG back to New too, not just a PATCH', async () => {
    const item = await itemWithBranch('story/106-dragged-back');
    await q.moveWorkItem(item.id, 'Active', [], 'tester');

    const back = await q.moveWorkItem(item.id, 'New', [], 'tester');

    expect(back?.state).toBe('New');
    expect(back?.branchName).toBeNull();
  });

  it('KEEPS a branch that has real commits on it — rework still owns its work', async () => {
    const item = await itemWithBranch('story/107-has-commits');
    await q.updateWorkItem(item.id, { state: 'Active' }, 'tester');
    await q.recordCommits(item.id, REPO, 'story/107-has-commits', [
      {
        sha: 'c0ffee',
        message: 'half the feature',
        authorLogin: 'ccsmith33',
        authorName: 'Clayton',
        url: `https://github.com/${REPO}/commit/c0ffee`,
        committedAt: '2026-08-25T12:00:00Z',
      },
    ]);

    const back = await q.updateWorkItem(item.id, { state: 'New' }, 'tester');

    // Losing the pointer to work in progress would be worse than a stale link.
    expect(back?.branchName).toBe('story/107-has-commits');
  });

  it('KEEPS a branch that has a pull request on it', async () => {
    const item = await itemWithBranch('story/108-has-pr');
    await q.updateWorkItem(item.id, { state: 'Active' }, 'tester');
    await q.linkPullRequest(
      item.id,
      {
        repoFullName: REPO,
        prNumber: 4242,
        url: `https://github.com/${REPO}/pull/4242`,
        title: 'WIP',
        prState: 'open',
        merged: false,
        draft: true,
        checksState: null,
        headRef: 'story/108-has-pr',
        baseRef: 'main',
      },
      'tester',
    );

    const back = await q.updateWorkItem(item.id, { state: 'New' }, 'tester');

    expect(back?.branchName).toBe('story/108-has-pr');
  });

  it('does not touch the branch on any other transition', async () => {
    const item = await itemWithBranch('story/109-forward');
    await q.updateWorkItem(item.id, { state: 'Active' }, 'tester');
    const resolved = await q.updateWorkItem(item.id, { state: 'Resolved' }, 'tester');
    expect(resolved?.branchName).toBe('story/109-forward');

    // ...including a no-op New -> New, which must not clear anything either.
    const fresh = await itemWithBranch('story/110-still-new');
    const same = await q.updateWorkItem(fresh.id, { state: 'New' }, 'tester');
    expect(same?.branchName).toBe('story/110-still-new');
  });
});

/**
 * The delete webhook for item 25's branch already fired, before anything
 * listened for it. The rows it should have cleared are still on the live
 * board, so the code fix alone leaves the visible bug in place.
 */
d('migration 004 — cleans branch metadata already written (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');
  let migrationSql: string;

  const BASE = {
    description: '',
    state: 'New' as const,
    assigneeLogin: null,
    assigneeAvatarUrl: null,
    storyPoints: null,
    priority: 2,
    sprintId: null,
    tags: [],
    repoFullName: REPO,
    wave: null,
  };

  async function seed(
    title: string,
    itemType: 'Story' | 'Task' | 'Bug' | 'Spike',
    branch: string,
  ) {
    const item = await q.createWorkItem({ ...BASE, title, itemType }, 'tester');
    await q.setItemBranch(
      item.id,
      { repoFullName: REPO, name: branch, url: `https://github.com/${REPO}/tree/${branch}` },
      'tester',
    );
    return item.id;
  }

  /** Runs the migration's SQL by hand — it was already applied at setup. */
  async function runCleanup() {
    await db.withTransaction(async (client) => {
      await client.query(`SET LOCAL search_path TO ${SCHEMA}, public`);
      await client.query(migrationSql);
    });
  }

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();
    q = await import('@/lib/domain/queries');
    migrationSql = await readFile(
      path.join(process.cwd(), 'src/lib/db/migrations/004_clear_stale_branch_metadata.sql'),
      'utf8',
    );
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  it('clears the branch a research spike should never have had (the AB#25 shape)', async () => {
    const id = await seed('Surface catalog: UA licenses + FERPA', 'Spike', 'spike/25-surface-catalog');
    // The base branch's history, ingested and attributed to the spike.
    await q.recordCommits(
      id,
      REPO,
      'spike/25-surface-catalog',
      Array.from({ length: 20 }, (_, i) => ({
        sha: `main${i}`,
        message: `a commit on main ${i}`,
        authorLogin: 'someone',
        authorName: 'Someone',
        url: `https://github.com/${REPO}/commit/main${i}`,
        committedAt: '2026-08-20T12:00:00Z',
      })),
    );
    expect((await q.getWorkItem(id))?.commitCount).toBe(20);

    await runCleanup();

    const after = await q.getWorkItem(id);
    expect(after?.branchName).toBeNull();
    expect(after?.branchUrl).toBeNull();
    expect(after?.branchRepo).toBeNull();
    expect(after?.branchCreatedAt).toBeNull();
    // ...and the 20 commits it never made.
    expect(after?.commitCount).toBe(0);
    // The item itself is untouched: it is OPEN research, not resolved work.
    expect(after?.state).toBe('New');
    expect(after?.itemType).toBe('Spike');
  });

  it('clears a Task that was given a branch by the old flow', async () => {
    const id = await seed('Book the demo room', 'Task', 'task/50-book-the-demo-room');
    await runCleanup();
    expect((await q.getWorkItem(id))?.branchName).toBeNull();
  });

  it('clears merged-and-gone branches on closed work (the AB#1 / AB#9 shape)', async () => {
    const id = await seed('Port walking skeleton', 'Story', 'story/1-port-walking-skeleton');
    await q.linkPullRequest(
      id,
      {
        repoFullName: REPO,
        prNumber: 5,
        url: `https://github.com/${REPO}/pull/5`,
        title: 'Port the skeleton',
        prState: 'merged',
        merged: true,
        draft: false,
        checksState: 'success',
        // Item 9's PR came off a DIFFERENTLY NAMED branch; matching head_ref
        // against branch_name would have missed exactly that case.
        headRef: 'story/1-different-name',
        baseRef: 'main',
      },
      'tester',
    );
    await q.recordCommits(id, REPO, 'story/1-port-walking-skeleton', [
      {
        sha: 'realwork',
        message: 'the actual skeleton',
        authorLogin: 'ccsmith33',
        authorName: 'Clayton',
        url: `https://github.com/${REPO}/commit/realwork`,
        committedAt: '2026-08-25T12:00:00Z',
      },
    ]);
    await q.updateWorkItem(id, { state: 'Active' }, 'tester');
    await q.updateWorkItem(id, { state: 'Resolved' }, 'tester');
    await q.updateWorkItem(id, { state: 'Closed' }, 'tester');

    await runCleanup();

    const after = await q.getWorkItem(id);
    expect(after?.branchName).toBeNull();
    // What the item shipped is the durable record and stays.
    expect(after?.commitCount).toBe(1);
    expect(after?.pullRequests).toHaveLength(1);
  });

  it('leaves live work alone — an Active story keeps its branch', async () => {
    const id = await seed('Judge calibration refresh', 'Story', 'story/42-judge-calibration');
    await q.updateWorkItem(id, { state: 'Active' }, 'tester');

    await runCleanup();

    expect((await q.getWorkItem(id))?.branchName).toBe('story/42-judge-calibration');
  });

  it('leaves a CLOSED story with an unmerged PR alone — that branch may still matter', async () => {
    const id = await seed('Abandoned experiment', 'Story', 'story/60-abandoned');
    await q.linkPullRequest(
      id,
      {
        repoFullName: REPO,
        prNumber: 60,
        url: `https://github.com/${REPO}/pull/60`,
        title: 'Experiment',
        prState: 'closed',
        merged: false,
        draft: false,
        checksState: null,
        headRef: 'story/60-abandoned',
        baseRef: 'main',
      },
      'tester',
    );
    await q.updateWorkItem(id, { state: 'Active' }, 'tester');
    await q.updateWorkItem(id, { state: 'Resolved' }, 'tester');
    await q.updateWorkItem(id, { state: 'Closed' }, 'tester');

    await runCleanup();

    expect((await q.getWorkItem(id))?.branchName).toBe('story/60-abandoned');
  });

  it('leaves a spike that produced a real PR alone', async () => {
    const id = await seed('Prototype the retriever', 'Spike', 'spike/70-prototype');
    await q.linkPullRequest(
      id,
      {
        repoFullName: REPO,
        prNumber: 70,
        url: `https://github.com/${REPO}/pull/70`,
        title: 'Prototype',
        prState: 'open',
        merged: false,
        draft: true,
        checksState: null,
        headRef: 'spike/70-prototype',
        baseRef: 'main',
      },
      'tester',
    );

    await runCleanup();

    expect((await q.getWorkItem(id))?.branchName).toBe('spike/70-prototype');
  });

  it('does not delete commits attributed to a spike by an AB# reference elsewhere', async () => {
    const id = await seed('Read the FERPA guidance', 'Spike', 'spike/80-ferpa');
    // A commit on SOMEONE ELSE'S branch that named this item in its message.
    await q.recordCommits(id, REPO, 'story/81-elsewhere', [
      {
        sha: 'elsewhere',
        message: 'note the FERPA finding (AB#80)',
        authorLogin: 'ccsmith33',
        authorName: 'Clayton',
        url: `https://github.com/${REPO}/commit/elsewhere`,
        committedAt: '2026-08-25T12:00:00Z',
      },
    ]);

    await runCleanup();

    const after = await q.getWorkItem(id);
    expect(after?.branchName).toBeNull();
    // Narrowed to `ic.branch = wi.branch_name`, so this one survives.
    expect(after?.commitCount).toBe(1);
  });

  it('is safe to run twice', async () => {
    const id = await seed('Idempotence check', 'Spike', 'spike/90-idempotence');
    await runCleanup();
    await runCleanup();
    expect((await q.getWorkItem(id))?.branchName).toBeNull();
  });
});
