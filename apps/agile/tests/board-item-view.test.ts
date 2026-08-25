import { describe, it, expect } from 'vitest';
import { installTestEnv } from './helpers/db';

installTestEnv('agile_board_view_test');

/**
 * AB#31 — a work item's full read view must be reachable from the board.
 *
 * The regression this guards: every prominent affordance on a board card opened
 * the EDIT dialog (double-click, Enter), and the card title was a plain <div>.
 * The only link to /items/{id} was the `#id` chip, styled faint and undecorated,
 * so in practice the read view was unreachable from the board and users went
 * looking for it on the backlog page instead.
 *
 * Rendered rather than grepped: this asserts the markup a browser actually gets.
 */
async function renderBoard(items: Array<Record<string, unknown>>) {
  const React = await import('react');
  const { renderToStaticMarkup } = await import('react-dom/server');
  const { Board } = await import('@/components/Board');
  const { ToastProvider } = await import('@/components/Toast');

  return renderToStaticMarkup(
    React.createElement(
      ToastProvider,
      null,
      React.createElement(Board as never, {
        initialItems: items,
        sprints: [],
        members: [],
        currentUser: 'tester',
        autoBranch: false,
        currentSprint: { sprintId: null, setBy: null, setAt: null },
        now: '2026-01-01T00:00:00Z',
        staleness: { maxAgeDays: 7, maxBehind: 20 },
      } as never),
    ),
  );
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    title: 'Port the skeleton',
    description: 'body',
    itemType: 'Story',
    state: 'New',
    assigneeLogin: null,
    assigneeAvatarUrl: null,
    storyPoints: 3,
    priority: 2,
    sprintId: null,
    boardRank: 0,
    createdBy: 'tester',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    closedAt: null,
    tags: [],
    pullRequests: [],
    commits: [],
    commitCount: 0,
    branchName: null,
    branchRepo: null,
    branchUrl: null,
    branchCreatedAt: null,
    lastActivityAt: '2026-01-01T00:00:00Z',
    repoFullName: null,
    wave: null,
    mergedPrCount: 0,
    depOverrideBy: null,
    depOverrideReason: null,
    readiness: { ready: true, blockers: [], overridden: false },
    ...overrides,
  };
}

describe('board cards link to the full item view (AB#31)', () => {
  it("renders the card title as a link to the item's detail page", async () => {
    const html = await renderBoard([item()]);
    expect(html).toMatch(
      /<div class="card-title"><a[^>]*href="\/items\/7"[^>]*>Port the skeleton<\/a><\/div>/,
    );
  });

  it('gives every card a title link, not just the first', async () => {
    const html = await renderBoard([
      item({ id: 7, title: 'First' }),
      item({ id: 8, title: 'Second', state: 'Active' }),
    ]);
    for (const id of [7, 8]) {
      const links = html.match(new RegExp(`href="/items/${id}"`, 'g')) ?? [];
      // The id chip AND the title, so the read view survives losing either one.
      expect(links.length, `item ${id} needs more than one route to its full view`)
        .toBeGreaterThanOrEqual(2);
    }
  });

  it('keeps the title link out of the drag interaction', async () => {
    // A draggable anchor inside a draggable card hijacks the drag as a link drag.
    const html = await renderBoard([item()]);
    const title = html.match(/<div class="card-title">(.*?)<\/div>/)?.[1] ?? '';
    expect(title).toContain('draggable="false"');
  });

  it('still exposes the id chip as a link, so nothing regressed', async () => {
    const html = await renderBoard([item()]);
    expect(html).toMatch(/<a class="id-chip"[^>]*href="\/items\/7"/);
  });
});
