import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_home_test';
installTestEnv(SCHEMA);
const d = hasDb ? describe : describe.skip;

/**
 * The living README and the auto-generated state strip.
 */
d('homepage (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let pages: typeof import('@/lib/domain/pages');
  let summary: typeof import('@/lib/domain/summary');
  let q: typeof import('@/lib/domain/queries');
  let deps: typeof import('@/lib/domain/deps-queries');
  let markdown: typeof import('@/lib/markdown');

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    const applied = await (await import('@/lib/db/migrate')).runMigrations();
    expect(applied).toContain('003_pages.sql');
    pages = await import('@/lib/domain/pages');
    summary = await import('@/lib/domain/summary');
    q = await import('@/lib/domain/queries');
    deps = await import('@/lib/domain/deps-queries');
    markdown = await import('@/lib/markdown');
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  beforeEach(() => {
    delete process.env.HOME_TEMPLATE;
  });

  // ------------------------------------------------------------- narrative

  it('a fresh instance shows starter content, never a blank page', async () => {
    const page = await pages.getPage();
    expect(page.isTemplate).toBe(true);
    expect(page.body.length).toBeGreaterThan(100);
    // The suggested sections are present so a new team has a shape to fill in.
    for (const heading of ['What this project is', 'Goals', 'Current focus', 'How we work', 'Links']) {
      expect(page.body).toContain(heading);
    }
  });

  it('the starter template is overridable per instance', async () => {
    process.env.HOME_TEMPLATE = '# Another class\n\nOur own starter text.';
    const page = await pages.getPage();
    expect(page.body).toContain('Another class');
    expect(page.isTemplate).toBe(true);
  });

  it('renders through the same sanitising markdown pipeline as work items', async () => {
    const html = markdown.renderMarkdown(
      '# Hello\n\nSome **bold** text.\n\n<script>alert(1)</script>\n',
    );
    expect(html).toContain('<h1>Hello</h1>');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('alert(1)');
  });

  it('an edit persists and is attributed', async () => {
    const saved = await pages.savePage('# Version one\n\nOur real goal.', 'alice');
    expect(saved.isTemplate).toBe(false);
    expect(saved.updatedBy).toBe('alice');

    const read = await pages.getPage();
    expect(read.body).toContain('Version one');
    expect(read.isTemplate).toBe(false);
    expect(read.updatedBy).toBe('alice');
  });

  it('records the PREVIOUS text in history on each change', async () => {
    await pages.savePage('# Version two\n\nGoal changed.', 'bob');

    const revisions = await pages.listPageRevisions();
    expect(revisions.length).toBeGreaterThan(0);
    // The newest revision holds what was replaced, and who wrote it.
    expect(revisions[0]!.body).toContain('Version one');
    expect(revisions[0]!.editedBy).toBe('alice');

    // ...and the live page holds the new text.
    expect((await pages.getPage()).body).toContain('Version two');
  });

  it('answers "when did our goal change?" — history is ordered newest first', async () => {
    await pages.savePage('# Version three', 'carol');
    const revisions = await pages.listPageRevisions();
    expect(revisions.length).toBeGreaterThanOrEqual(2);
    const times = revisions.map((r) => Date.parse(r.editedAt));
    expect([...times].sort((a, b) => b - a)).toEqual(times);
    expect(revisions[0]!.body).toContain('Version two');
  });

  it('does NOT record a revision when the text is unchanged', async () => {
    const before = (await pages.listPageRevisions()).length;
    await pages.savePage('# Version three', 'dave');
    expect((await pages.listPageRevisions()).length).toBe(before);
  });

  it('accepts an empty page without losing the history', async () => {
    const before = (await pages.listPageRevisions()).length;
    await pages.savePage('', 'erin');
    expect((await pages.getPage()).body).toBe('');
    expect((await pages.listPageRevisions()).length).toBe(before + 1);
    await pages.savePage('# Restored', 'erin');
  });

  // ----------------------------------------------------------- state strip

  it('summary reflects ACTUAL board data, not hand-maintained prose', async () => {
    const sprint = await q.createSprint({
      name: 'Home Sprint',
      goal: 'Ship the thing',
      startsOn: '2026-08-20',
      endsOn: '2026-09-02',
    });
    await deps.setCurrentSprint(sprint.id, 'alice');

    const a = await q.createWorkItem({ title: 'Home A', storyPoints: 5, sprintId: sprint.id }, 'alice');
    const b = await q.createWorkItem({ title: 'Home B', storyPoints: 3, sprintId: sprint.id }, 'alice');
    const blocked = await q.createWorkItem({ title: 'Home blocked', storyPoints: 2 }, 'alice');
    await deps.addDependency(blocked.id, a.id, 'alice');

    await q.updateWorkItem(b.id, { state: 'Active' }, 'alice');

    const s = await summary.boardSummary('2026-08-25');

    expect(s.currentSprint.sprint?.name).toBe('Home Sprint');
    expect(s.currentSprint.setBy).toBe('alice');
    // 2026-08-25 -> 2026-09-02
    expect(s.currentSprint.daysRemaining).toBe(8);

    expect(s.states.Active).toBeGreaterThanOrEqual(1);
    expect(s.points.total).toBeGreaterThanOrEqual(10);
    expect(s.points.remaining).toBe(s.points.total - s.points.done);

    // The blocked item is counted as blocked, not ready.
    expect(s.blockedCount).toBeGreaterThanOrEqual(1);
    expect(s.readyCount).toBeGreaterThanOrEqual(1);
    expect(s.totals.items).toBeGreaterThanOrEqual(3);
  });

  it('moving an item to a finished state moves points from remaining to done', async () => {
    const before = await summary.boardSummary('2026-08-25');
    const item = await q.createWorkItem({ title: 'Points mover', storyPoints: 8 }, 'alice');
    await q.updateWorkItem(item.id, { state: 'Active' }, 'alice');
    await q.updateWorkItem(item.id, { state: 'Resolved' }, 'alice');

    const after = await summary.boardSummary('2026-08-25');
    expect(after.points.done).toBe(before.points.done + 8);
    expect(after.recentlyResolved.map((r) => r.id)).toContain(item.id);
  });

  it('counts MERGED pull requests as progress — commits never count', async () => {
    const item = await q.createWorkItem({ title: 'PR progress' }, 'alice');
    const before = (await summary.boardSummary('2026-08-25')).mergedPrCount;

    // Commits alone must not change the merged-PR count.
    await q.recordCommits(item.id, 'UA-MIS/ida-llm', 'story/x', [
      { sha: 'f'.repeat(40), message: 'wip', authorLogin: 'alice', authorName: 'Alice', url: 'u',
        committedAt: new Date().toISOString() },
    ]);
    expect((await summary.boardSummary('2026-08-25')).mergedPrCount).toBe(before);

    // A merged PR does.
    await q.linkPullRequest(
      item.id,
      { repoFullName: 'UA-MIS/ida-llm', prNumber: 900, url: 'https://example.test/pr/900',
        title: 'Merged work', prState: 'merged', merged: true, draft: false, checksState: 'success' },
      'alice',
    );
    const after = await summary.boardSummary('2026-08-25');
    expect(after.mergedPrCount).toBe(before + 1);
    expect(after.recentMergedPrs.map((p) => p.prNumber)).toContain(900);
  });

  it('reports no current sprint cleanly rather than crashing', async () => {
    await deps.setCurrentSprint(null, 'alice');
    const s = await summary.boardSummary('2026-08-25');
    expect(s.currentSprint.sprint).toBeNull();
    expect(s.currentSprint.daysRemaining).toBeNull();
    expect(typeof s.states.New).toBe('number');
  });
});
