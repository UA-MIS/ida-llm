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

  /**
   * Runs the migration's SQL by hand — it was already applied at setup.
   * Supplies `ida_agile.instance_key` exactly as `migrate.ts` does, so this
   * exercises the real contract rather than a relaxed one.
   */
  async function runCleanup(instanceKey = 'test-instance') {
    await db.withTransaction(async (client) => {
      await client.query(`SET LOCAL search_path TO ${SCHEMA}, public`);
      await client.query('SELECT set_config($1, $2, true)', [
        'ida_agile.instance_key',
        instanceKey,
      ]);
      await client.query(migrationSql);
    });
  }

  /** Records commits against an item's own branch at a given time. */
  async function commitsOnBranch(
    id: number,
    branch: string,
    when: string,
    shas: string[],
  ) {
    await q.recordCommits(
      id,
      REPO,
      branch,
      shas.map((sha) => ({
        sha,
        message: `real work ${sha}`,
        authorLogin: 'ccsmith33',
        authorName: 'Clayton',
        url: `https://github.com/${REPO}/commit/${sha}`,
        committedAt: when,
      })),
    );
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

  // -------------------------------------------------------------------------
  // Regression: the shapes an earlier version of this migration DESTROYED.
  //
  // Arm A deletes commit rows, and its first draft guarded only on "has no PR".
  // That is the ordinary mid-flight state of any started Task — before this PR
  // every type branched — so real, pushed, unrecoverable work was swept. The
  // deleted SHAs live nowhere else and the poller cannot re-ingest them once
  // the branch pointer it reads from has been nulled.
  //
  // Ancestry commits predate the branch cut; real work follows it. That is the
  // discriminator, and these two tests are the ones that would have caught it.
  // -------------------------------------------------------------------------

  it('PRESERVES an Active Task with real commits pushed after the cut and no PR yet', async () => {
    const id = await seed('Deploy the staging overlay', 'Task', 'task/200-deploy');
    const cutAt = (await q.getWorkItem(id))!.branchCreatedAt!;
    // Two commits pushed AFTER the branch was cut. No PR open yet.
    await commitsOnBranch(id, 'task/200-deploy', new Date(Date.parse(cutAt) + 60_000).toISOString(), [
      'realwork1',
      'realwork2',
    ]);
    await q.updateWorkItem(id, { state: 'Active' }, 'tester');

    await runCleanup();

    const after = await q.getWorkItem(id);
    // Both must survive: these SHAs are recorded nowhere else in the system.
    expect(after?.commitCount).toBe(2);
    // And the pointer stays, or the poller can never reach the branch again.
    expect(after?.branchName).toBe('task/200-deploy');
    expect(after?.branchUrl).not.toBeNull();
  });

  it('PRESERVES a Spike using the {branch:true} escape hatch this PR adds', async () => {
    // The migration must not destroy the exact case its own PR introduced.
    const id = await seed('Prototype pgvector recall', 'Spike', 'spike/201-pgvector');
    const cutAt = (await q.getWorkItem(id))!.branchCreatedAt!;
    await commitsOnBranch(id, 'spike/201-pgvector', new Date(Date.parse(cutAt) + 60_000).toISOString(), [
      'spikework1',
    ]);
    await q.updateWorkItem(id, { state: 'Active' }, 'tester');

    await runCleanup();

    const after = await q.getWorkItem(id);
    expect(after?.commitCount).toBe(1);
    expect(after?.branchName).toBe('spike/201-pgvector');
  });

  it('still clears a Spike whose ONLY commits predate the branch cut (the #25 discriminator)', async () => {
    // This is what makes the guard a discriminator and not just "any commit
    // protects": #25's 20 rows are main's history, and they must still go.
    const id = await seed('Read the policy corpus', 'Spike', 'spike/202-policy');
    const cutAt = (await q.getWorkItem(id))!.branchCreatedAt!;
    await commitsOnBranch(id, 'spike/202-policy', new Date(Date.parse(cutAt) - 86_400_000).toISOString(), [
      'ancestry1',
      'ancestry2',
    ]);

    await runCleanup();

    const after = await q.getWorkItem(id);
    expect(after?.branchName).toBeNull();
    expect(after?.commitCount).toBe(0);
  });

  it('treats an unknown branch-cut time as "cannot prove stale" and leaves the item alone', async () => {
    const id = await seed('Unknown provenance', 'Task', 'task/203-unknown');
    await commitsOnBranch(id, 'task/203-unknown', '2026-08-25T12:00:00Z', ['mystery']);
    // A row from before branch_created_at was populated.
    await db.query(
      `UPDATE ${SCHEMA}.work_items SET branch_created_at = NULL WHERE id = $1`,
      [id],
    );

    await runCleanup();

    const after = await q.getWorkItem(id);
    expect(after?.branchName).toBe('task/203-unknown');
    expect(after?.commitCount).toBe(1);
  });

  it('is scoped to this board — another instance_key is never touched', async () => {
    const id = await seed('Someone else\'s spike', 'Spike', 'spike/300-other-board');
    await db.query(
      `UPDATE ${SCHEMA}.work_items SET instance_key = 'OTHER-BOARD' WHERE id = $1`,
      [id],
    );

    await runCleanup('test-instance');

    const rows = await db.query<{ branch_name: string | null }>(
      `SELECT branch_name FROM ${SCHEMA}.work_items WHERE id = $1`,
      [id],
    );
    expect(rows[0]?.branch_name).toBe('spike/300-other-board');
  });

  it('refuses to run at all when the runner does not say which board it is', async () => {
    // Fail loudly rather than fall back to editing every board's rows.
    await expect(
      db.withTransaction(async (client) => {
        await client.query(`SET LOCAL search_path TO ${SCHEMA}, public`);
        await client.query(migrationSql);
      }),
    ).rejects.toThrow(/ida_agile\.instance_key/);
  });

  it('is safe to run twice', async () => {
    const id = await seed('Idempotence check', 'Spike', 'spike/90-idempotence');
    await runCleanup();
    await runCleanup();
    expect((await q.getWorkItem(id))?.branchName).toBeNull();
  });
});
