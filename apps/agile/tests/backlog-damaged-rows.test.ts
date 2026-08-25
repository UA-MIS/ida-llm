import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_backlog_rows_test';
installTestEnv(SCHEMA);
const d = hasDb ? describe : describe.skip;

/**
 * AB#30 — the backlog page must render the rows a real board actually holds.
 *
 * Two independent reasons the live page died where a clean seed did not:
 *
 *  1. Items carry LINKED PULL REQUESTS. `pullRequests.map()` over an empty array
 *     renders nothing, so seeded items with no PR never exercised `PrChip` — the
 *     component whose `onClick` crashed the Server Component render.
 *  2. Items carry NULLS in every optional column. Some are how an item was
 *     created (no wave, no points); some were left by the AB#28 replace-semantics
 *     bug, which blanked `wave` and `repoFullName` on real rows.
 *
 * A student's board will always be partially filled, so "renders with any
 * nullable field null" is a standing requirement, not a one-off repair.
 */

/** The shape of live item #1 after the AB#28 damage: wave and repo blanked. */
const DAMAGED = {
  title: 'Port the walking skeleton',
  description: '# Heading\n\nBody text that still has to render.',
  itemType: 'Story' as const,
  state: 'New' as const,
  assigneeLogin: null,
  assigneeAvatarUrl: null,
  storyPoints: null,
  priority: 2,
  sprintId: null,
  tags: [],
  repoFullName: null,
  wave: null,
};

describe('backlog render helpers tolerate every nullable field (AB#30)', () => {
  it('renders the chips the backlog row uses with everything null', async () => {
    const React = await import('react');
    const { renderToStaticMarkup } = await import('react-dom/server');
    const { Assignee, PriorityChip, StateBadge, TypeChip } = await import('@/components/chips');

    const html = renderToStaticMarkup(
      React.createElement(
        'div',
        null,
        React.createElement(TypeChip as never, { type: 'Story' } as never),
        React.createElement(StateBadge as never, { state: 'New' } as never),
        // Both null — the shape every unassigned row has.
        React.createElement(Assignee as never, { login: null, avatarUrl: null } as never),
        React.createElement(PriorityChip as never, { priority: 2 } as never),
      ),
    );

    expect(html).toContain('Unassigned');
    expect(html).not.toContain('null');
    expect(html).not.toContain('undefined');
  });

  it('renders a PR chip, the component that crashed the page', async () => {
    const React = await import('react');
    const { renderToStaticMarkup } = await import('react-dom/server');
    const { PrChip } = await import('@/components/chips');

    // checksState and behindBy null — the common shape for a merged PR.
    const html = renderToStaticMarkup(
      React.createElement(PrChip as never, {
        pr: {
          id: 1,
          itemId: 1,
          repoFullName: 'UA-MIS/ida-llm',
          prNumber: 12,
          url: 'https://github.com/UA-MIS/ida-llm/pull/12',
          title: 'LLM judge',
          prState: 'closed',
          merged: true,
          draft: false,
          checksState: null,
          headRef: 'story/5',
          baseRef: 'main',
          behindBy: null,
          linkedBy: 'ccsmith33',
          lastSyncedAt: null,
        },
      } as never),
    );

    expect(html).toContain('href="https://github.com/UA-MIS/ida-llm/pull/12"');
    expect(html).toContain('#12');
    expect(html).not.toContain('undefined');
  });

  it('summarises a description to plain text without choking on an empty one', async () => {
    const { toPlainText } = await import('@/lib/markdown');
    expect(toPlainText(DAMAGED.description, 110)).toContain('Body text');
    expect(toPlainText('', 110)).toBe('');
    // The page calls this on every row; a blank description is normal.
    expect(() => toPlainText('', 110)).not.toThrow();
  });
});

d('backlog data for damaged rows (real Postgres, AB#30)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();
    q = await import('@/lib/domain/queries');
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  it('returns a damaged row with its linked PR — the exact live combination', async () => {
    const item = await q.createWorkItem(DAMAGED, 'tester');
    // `createWorkItem` back-fills repo_full_name from config
    // (`input.repoFullName ?? defaultRepoForItem()`), so a null cannot be
    // created through the normal path — it can only be LEFT there, which is
    // precisely what the AB#28 replace-semantics bug did to live item #1.
    // Reproduce that post-damage state directly.
    await db.query('UPDATE work_items SET repo_full_name = NULL WHERE id = $1', [item.id]);

    await q.linkPullRequest(
      item.id,
      {
        repoFullName: 'UA-MIS/ida-llm',
        prNumber: 12,
        url: 'https://github.com/UA-MIS/ida-llm/pull/12',
        title: 'LLM judge',
        prState: 'closed',
        merged: true,
        draft: false,
        headRef: 'story/5',
        baseRef: 'main',
        checksState: null,
        behindBy: null,
      },
      'ccsmith33',
    );

    const rows = await q.listWorkItems();
    const row = rows.find((r) => r.id === item.id)!;

    // The nulls survive the round trip...
    expect(row.wave).toBeNull();
    expect(row.repoFullName).toBeNull();
    expect(row.storyPoints).toBeNull();
    expect(row.assigneeLogin).toBeNull();
    expect(row.assigneeAvatarUrl).toBeNull();
    // ...and the PR is attached, so the page will render a PrChip for it.
    expect(row.pullRequests).toHaveLength(1);
    expect(row.pullRequests[0]!.prNumber).toBe(12);
  });

  it('always gives the page an array to map over, never a null', async () => {
    // `pullRequests.map(...)` runs unconditionally on every backlog row.
    const bare = await q.createWorkItem({ ...DAMAGED, title: 'No PRs at all' }, 'tester');
    const rows = await q.listWorkItems();
    const found = rows.find((r) => r.id === bare.id)!;
    expect(Array.isArray(found.pullRequests)).toBe(true);
    expect(found.pullRequests).toEqual([]);
    expect(Array.isArray(found.tags)).toBe(true);
  });

  it('totals points across rows where storyPoints is null', async () => {
    const rows = await q.listWorkItems();
    // The page's own reduce. A null must contribute 0, not NaN.
    const total = rows.reduce((sum, i) => sum + (i.storyPoints ?? 0), 0);
    expect(Number.isNaN(total)).toBe(false);
    expect(total).toBe(0);
  });
});
