import { describe, it, expect } from 'vitest';
import { groupLinkedPullRequests, type LinkedPullRequest } from '@/lib/domain/board-prs';

/**
 * BUG AB#29 — `GET /api/v1/prs` returned `{"prs":[]}` while nine merged PRs were
 * attached to board items and counted by `/summary`.
 *
 * Root cause was the data SOURCE, not this grouping: the route asked GitHub for
 * `state=open` PRs instead of reading the board's own `pull_request_links`. The
 * shaping half lives here so it is covered by the no-database CI job; the query
 * and the route are pinned in `prs-endpoint.test.ts` against real Postgres.
 */

let seq = 0;
function link(over: Partial<LinkedPullRequest> = {}): LinkedPullRequest {
  return {
    id: ++seq,
    itemId: 1,
    itemTitle: 'An item',
    repoFullName: 'UA-MIS/ida-llm',
    prNumber: 42,
    url: 'https://github.com/UA-MIS/ida-llm/pull/42',
    title: 'Do the thing',
    prState: 'open',
    merged: false,
    draft: false,
    checksState: null,
    headRef: 'story/1',
    baseRef: 'main',
    behindBy: null,
    linkedBy: 'alice',
    lastSyncedAt: '2026-08-20T00:00:00.000Z',
    ...over,
  };
}

describe('groupLinkedPullRequests', () => {
  it('returns MERGED pull requests — the state the old open-only query could never show', () => {
    const out = groupLinkedPullRequests([
      link({ prNumber: 7, merged: true, prState: 'merged', title: 'Ship it AB#7' }),
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ prNumber: 7, merged: true, prState: 'merged' });
  });

  it('returns open and merged together, since both are attached to the board', () => {
    const out = groupLinkedPullRequests([
      link({ prNumber: 1, merged: false, prState: 'open' }),
      link({ prNumber: 2, merged: true, prState: 'merged' }),
    ]);
    expect(out.map((p) => p.prNumber).sort()).toEqual([1, 2]);
  });

  it('collapses one PR attached to several items into ONE entry listing every item', () => {
    const out = groupLinkedPullRequests([
      link({ id: 100, itemId: 29, itemTitle: 'Board bug', prNumber: 5 }),
      link({ id: 101, itemId: 12, itemTitle: 'Older story', prNumber: 5 }),
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]!.items).toEqual([
      { id: 12, title: 'Older story' },
      { id: 29, title: 'Board bug' },
    ]);
  });

  it('treats repo names case-insensitively when deciding two rows are the same PR', () => {
    const out = groupLinkedPullRequests([
      link({ itemId: 1, repoFullName: 'UA-MIS/ida-llm', prNumber: 9 }),
      link({ itemId: 2, repoFullName: 'ua-mis/IDA-LLM', prNumber: 9 }),
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]!.items.map((i) => i.id)).toEqual([1, 2]);
  });

  it('keeps the same number in different repos apart', () => {
    const out = groupLinkedPullRequests([
      link({ repoFullName: 'UA-MIS/ida-llm', prNumber: 3 }),
      link({ repoFullName: 'UA-MIS/platform-infra', prNumber: 3 }),
    ]);
    expect(out).toHaveLength(2);
  });

  it('takes PR facts from the most recently synced row, not whichever arrived first', () => {
    const out = groupLinkedPullRequests([
      link({ itemId: 1, prNumber: 4, merged: false, prState: 'open', lastSyncedAt: '2026-08-01T00:00:00.000Z' }),
      link({ itemId: 2, prNumber: 4, merged: true, prState: 'merged', lastSyncedAt: '2026-08-25T00:00:00.000Z' }),
    ]);
    expect(out[0]).toMatchObject({ merged: true, prState: 'merged' });
  });

  it('orders newest-synced first, and puts never-synced rows last', () => {
    const out = groupLinkedPullRequests([
      link({ prNumber: 1, lastSyncedAt: null }),
      link({ prNumber: 2, lastSyncedAt: '2026-08-10T00:00:00.000Z' }),
      link({ prNumber: 3, lastSyncedAt: '2026-08-24T00:00:00.000Z' }),
    ]);
    expect(out.map((p) => p.prNumber)).toEqual([3, 2, 1]);
  });

  it('is deterministic when nothing has ever been synced', () => {
    const shape = () =>
      groupLinkedPullRequests([
        link({ prNumber: 2, repoFullName: 'UA-MIS/b', lastSyncedAt: null }),
        link({ prNumber: 8, repoFullName: 'UA-MIS/a', lastSyncedAt: null }),
        link({ prNumber: 3, repoFullName: 'UA-MIS/a', lastSyncedAt: null }),
      ]).map((p) => `${p.repoFullName}#${p.prNumber}`);
    expect(shape()).toEqual(['UA-MIS/a#8', 'UA-MIS/a#3', 'UA-MIS/b#2']);
    expect(shape()).toEqual(shape());
  });

  it('still annotates AB#<id> references found in the PR title', () => {
    const out = groupLinkedPullRequests([link({ title: 'Fix board AB#29 and AB#3' })]);
    expect(out[0]!.suggestedItemIds).toEqual([3, 29]);
  });

  it('reports no suggestions rather than null when the title mentions nothing', () => {
    expect(groupLinkedPullRequests([link({ title: 'chore: bump deps' })])[0]!.suggestedItemIds).toEqual([]);
  });

  it('returns an empty list for no links, never null', () => {
    expect(groupLinkedPullRequests([])).toEqual([]);
  });

  it('carries the fields a reviewer needs to triage without a second call', () => {
    const [pr] = groupLinkedPullRequests([
      link({ prNumber: 11, url: 'https://github.com/UA-MIS/ida-llm/pull/11', checksState: 'success', behindBy: 2, draft: true }),
    ]);
    expect(pr).toMatchObject({
      repoFullName: 'UA-MIS/ida-llm',
      prNumber: 11,
      url: 'https://github.com/UA-MIS/ida-llm/pull/11',
      checksState: 'success',
      behindBy: 2,
      draft: true,
      headRef: 'story/1',
      baseRef: 'main',
    });
  });
});
