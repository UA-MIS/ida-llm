import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_sync_test';
installTestEnv(SCHEMA);
process.env.GITHUB_REPOS = 'UA-MIS/ida-llm';

const REPO = 'UA-MIS/ida-llm';
const d = hasDb ? describe : describe.skip;

/**
 * End-to-end behaviour of the git -> board loop, against a real database.
 * These cover the rules the team will actually feel: commits attaching to the
 * right item, PRs moving state, and every automatic move being attributed.
 */
d('sync engine (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');
  let engine: typeof import('@/lib/sync/engine');

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

  beforeEach(() => {
    delete process.env.AUTO_PROGRESS;
  });

  async function newItem(title: string, state: 'New' | 'Active' = 'New') {
    return q.createWorkItem(
      {
        title,
        description: '',
        itemType: 'Story',
        state,
        assigneeLogin: null,
        assigneeAvatarUrl: null,
        storyPoints: null,
        priority: 2,
        sprintId: null,
        tags: [],
      },
      'alice',
    );
  }

  const commit = (sha: string, message: string) => ({
    sha,
    message,
    authorLogin: 'alice',
    authorName: 'Alice',
    url: `https://github.com/${REPO}/commit/${sha}`,
    committedAt: new Date().toISOString(),
  });

  it('attaches commits pushed to an item branch, and activates a New item', async () => {
    const item = await newItem('Branch push');
    await q.setItemBranch(
      item.id,
      { repoFullName: REPO, name: `story/${item.id}-branch-push`, url: 'u' },
      'alice',
    );

    const outcome = await engine.handlePush({
      repoFullName: REPO,
      branch: `story/${item.id}-branch-push`,
      commits: [commit('a'.repeat(40), 'first work')],
    });

    expect(outcome.itemsTouched).toContain(item.id);
    expect(outcome.transitions).toEqual([
      expect.objectContaining({ itemId: item.id, from: 'New', to: 'Active' }),
    ]);

    const after = await q.getWorkItem(item.id);
    expect(after?.state).toBe('Active');
    expect(after?.commitCount).toBe(1);
  });

  it('records the automatic move in history as coming from GitHub', async () => {
    const item = await newItem('Attributed move');
    await q.setItemBranch(item.id, { repoFullName: REPO, name: `story/${item.id}-attr`, url: 'u' }, 'alice');

    await engine.handlePush({
      repoFullName: REPO,
      branch: `story/${item.id}-attr`,
      commits: [commit('b'.repeat(40), 'work')],
    });

    const log = await q.listActivity(item.id);
    const move = log.find((e) => e.field === 'state');
    expect(move).toBeDefined();
    expect(move?.source).toBe('github');
    expect(move?.note).toContain('moved by GitHub');
    expect(move?.note).toContain('commit');
  });

  it('is idempotent: replaying the same push adds no duplicate commits', async () => {
    const item = await newItem('Replay safety');
    const branch = `story/${item.id}-replay`;
    await q.setItemBranch(item.id, { repoFullName: REPO, name: branch, url: 'u' }, 'alice');

    const payload = {
      repoFullName: REPO,
      branch,
      commits: [commit('c'.repeat(40), 'once')],
    };
    await engine.handlePush(payload);
    await engine.handlePush(payload);

    expect((await q.getWorkItem(item.id))?.commitCount).toBe(1);
  });

  it('attaches a commit on ANY branch that names the item with AB#<id>', async () => {
    const item = await newItem('Referenced by message');

    await engine.handlePush({
      repoFullName: REPO,
      branch: 'someone-elses-branch',
      commits: [commit('d'.repeat(40), `fix the thing AB#${item.id}`)],
    });

    const after = await q.getWorkItem(item.id);
    expect(after?.commitCount).toBe(1);
  });

  it('ignores pushes to repos this board is not configured for', async () => {
    const item = await newItem('Other repo');
    await q.setItemBranch(item.id, { repoFullName: REPO, name: `story/${item.id}-x`, url: 'u' }, 'alice');

    const outcome = await engine.handlePush({
      repoFullName: 'someone/unrelated',
      branch: `story/${item.id}-x`,
      commits: [commit('e'.repeat(40), 'nope')],
    });

    expect(outcome.itemsTouched).toEqual([]);
    expect((await q.getWorkItem(item.id))?.commitCount).toBe(0);
  });

  it('links and activates on PR open, via the branch name', async () => {
    const item = await newItem('PR opened');
    const branch = `story/${item.id}-pr-opened`;
    await q.setItemBranch(item.id, { repoFullName: REPO, name: branch, url: 'u' }, 'alice');

    const outcome = await engine.handlePullRequest({
      repoFullName: REPO,
      number: 101,
      url: `https://github.com/${REPO}/pull/101`,
      title: 'Implement it',
      body: '',
      state: 'open',
      merged: false,
      draft: false,
      headRef: branch,
      baseRef: 'main',
      action: 'opened',
    });

    expect(outcome.transitions).toContainEqual(
      expect.objectContaining({ itemId: item.id, to: 'Active' }),
    );
    const after = await q.getWorkItem(item.id);
    expect(after?.state).toBe('Active');
    expect(after?.pullRequests.map((p) => p.prNumber)).toContain(101);
  });

  it('moves an Active item to Resolved when its PR merges — never straight to Closed', async () => {
    const item = await newItem('PR merged', 'Active');
    const branch = `story/${item.id}-merge`;
    await q.setItemBranch(item.id, { repoFullName: REPO, name: branch, url: 'u' }, 'alice');

    await engine.handlePullRequest({
      repoFullName: REPO,
      number: 102,
      url: 'u',
      title: 'Done',
      body: '',
      state: 'closed',
      merged: true,
      draft: false,
      headRef: branch,
      baseRef: 'main',
      action: 'closed',
    });

    const after = await q.getWorkItem(item.id);
    expect(after?.state).toBe('Resolved');

    const move = (await q.listActivity(item.id)).find(
      (e) => e.field === 'state' && e.newValue === 'Resolved',
    );
    expect(move?.source).toBe('github');
    expect(move?.note).toContain('PR #102 merged');
  });

  it('walks New -> Active -> Resolved when a merge arrives on a New item', async () => {
    const item = await newItem('Straight to merged');
    const branch = `story/${item.id}-jump`;
    await q.setItemBranch(item.id, { repoFullName: REPO, name: branch, url: 'u' }, 'alice');

    await engine.handlePullRequest({
      repoFullName: REPO, number: 103, url: 'u', title: 'Jump', body: '',
      state: 'closed', merged: true, draft: false, headRef: branch, baseRef: 'main', action: 'closed',
    });

    // The illegal New -> Resolved hop is never taken directly.
    const states = (await q.listActivity(item.id))
      .filter((e) => e.field === 'state')
      .map((e) => `${e.oldValue}->${e.newValue}`);
    expect(states).not.toContain('New->Resolved');
    expect((await q.getWorkItem(item.id))?.state).toBe('Resolved');
  });

  it('does NOT change state when a PR is closed without merging, but warns', async () => {
    const item = await newItem('Abandoned PR', 'Active');
    const branch = `story/${item.id}-abandoned`;
    await q.setItemBranch(item.id, { repoFullName: REPO, name: branch, url: 'u' }, 'alice');

    const outcome = await engine.handlePullRequest({
      repoFullName: REPO, number: 104, url: 'u', title: 'Nope', body: '',
      state: 'closed', merged: false, draft: false, headRef: branch, baseRef: 'main', action: 'closed',
    });

    expect(outcome.transitions).toEqual([]);
    expect(outcome.warnings.join(' ')).toContain('closed without merging');
    expect((await q.getWorkItem(item.id))?.state).toBe('Active');
  });

  it('auto-links a PR that mentions AB#<id> even with no matching branch', async () => {
    const item = await newItem('Mentioned in PR body');

    await engine.handlePullRequest({
      repoFullName: REPO, number: 105, url: 'u', title: 'Unrelated branch name',
      body: `This closes AB#${item.id}`, state: 'open', merged: false, draft: false,
      headRef: 'random/thing', baseRef: 'main', action: 'opened',
    });

    const after = await q.getWorkItem(item.id);
    expect(after?.pullRequests.map((p) => p.prNumber)).toContain(105);
  });

  it('respects AUTO_PROGRESS=false — links the PR but leaves state alone', async () => {
    process.env.AUTO_PROGRESS = 'false';
    const item = await newItem('Passive board');
    const branch = `story/${item.id}-passive`;
    await q.setItemBranch(item.id, { repoFullName: REPO, name: branch, url: 'u' }, 'alice');

    const outcome = await engine.handlePullRequest({
      repoFullName: REPO, number: 106, url: 'u', title: 'Passive', body: '',
      state: 'open', merged: false, draft: false, headRef: branch, baseRef: 'main', action: 'opened',
    });

    expect(outcome.transitions).toEqual([]);
    const after = await q.getWorkItem(item.id);
    expect(after?.state).toBe('New');
    expect(after?.pullRequests.map((p) => p.prNumber)).toContain(106);
  });

  it('refreshes stored check state for a linked PR', async () => {
    const item = await newItem('Checks', 'Active');
    const branch = `story/${item.id}-checks`;
    await q.setItemBranch(item.id, { repoFullName: REPO, name: branch, url: 'u' }, 'alice');
    await engine.handlePullRequest({
      repoFullName: REPO, number: 107, url: 'u', title: 'Checks', body: '',
      state: 'open', merged: false, draft: false, headRef: branch, baseRef: 'main', action: 'opened',
    });

    await engine.handleCheckState(REPO, [107], 'failure');
    const after = await q.getWorkItem(item.id);
    expect(after?.pullRequests.find((p) => p.prNumber === 107)?.checksState).toBe('failure');
  });
});
