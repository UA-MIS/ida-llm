import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_prs_endpoint_test';
installTestEnv(SCHEMA);

const d = hasDb ? describe : describe.skip;

/**
 * REGRESSION — board bug AB#29.
 *
 * `GET /api/v1/prs` answered `{"prs":[]}` on a board with nine merged PRs
 * attached to items, while `/summary` counted all nine from the same database.
 * The two disagreed because they read different things: `/summary` reads the
 * board's `pull_request_links`, and `/prs` asked GitHub for `state=open` PRs
 * across the configured repos -- a query that can never return a merged PR and
 * never knows whether a PR is attached to anything at all.
 *
 * These tests seed items with linked PRs and assert the endpoint lists them, so
 * the endpoint and the summary are pinned to the SAME source. There is
 * deliberately no GitHub credential in the test environment: the fix must not
 * need one, and if `/prs` ever reaches for GitHub again these go red.
 */
d('GET /api/v1/prs — attached pull requests (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');
  let tokens: typeof import('@/lib/auth/tokens');
  let route: typeof import('@/app/api/v1/prs/route');
  let summary: typeof import('@/lib/domain/summary');
  let bearer: string;

  const seeded = { merged: 0, open: 0, shared: 0 };

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();

    q = await import('@/lib/domain/queries');
    tokens = await import('@/lib/auth/tokens');
    route = await import('@/app/api/v1/prs/route');
    summary = await import('@/lib/domain/summary');

    bearer = (await tokens.createApiToken({ name: 'prs-test', ownerLogin: 'alice' })).token;

    const merged = await q.createWorkItem({ title: 'Harness core' }, 'alice');
    const open = await q.createWorkItem({ title: 'Ingest transcripts' }, 'alice');
    const shared = await q.createWorkItem({ title: 'Shared work' }, 'alice');
    seeded.merged = merged.id;
    seeded.open = open.id;
    seeded.shared = shared.id;

    await q.linkPullRequest(
      merged.id,
      {
        repoFullName: 'UA-MIS/ida-llm',
        prNumber: 101,
        url: 'https://github.com/UA-MIS/ida-llm/pull/101',
        title: `Land the harness AB#${merged.id}`,
        prState: 'merged',
        merged: true,
        draft: false,
        checksState: 'success',
        headRef: 'story/harness',
        baseRef: 'main',
      },
      'alice',
    );

    await q.linkPullRequest(
      open.id,
      {
        repoFullName: 'UA-MIS/ida-llm',
        prNumber: 102,
        url: 'https://github.com/UA-MIS/ida-llm/pull/102',
        title: 'Ingest transcripts',
        prState: 'open',
        merged: false,
        draft: false,
        checksState: 'pending',
        headRef: 'story/ingest',
        baseRef: 'main',
      },
      'alice',
    );

    // The same PR attached to two items -- the board allows it, so the endpoint
    // has to have an answer for it.
    for (const id of [open.id, shared.id]) {
      await q.linkPullRequest(
        id,
        {
          repoFullName: 'UA-MIS/ida-llm',
          prNumber: 103,
          url: 'https://github.com/UA-MIS/ida-llm/pull/103',
          title: 'Cross-cutting change',
          prState: 'merged',
          merged: true,
          draft: false,
          checksState: null,
        },
        'alice',
      );
    }
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  async function get(): Promise<{ status: number; body: { prs: Array<Record<string, unknown>>; note?: string } }> {
    const res = await route.GET(
      new Request('http://localhost:3000/api/v1/prs', {
        headers: { authorization: `Bearer ${bearer}` },
      }),
    );
    return { status: res.status, body: await res.json() };
  }

  it('LISTS the pull requests attached to items — the bug was an empty array here', async () => {
    const { status, body } = await get();
    expect(status).toBe(200);
    expect(body.prs.length).toBeGreaterThan(0);
    expect(body.prs.map((p) => p.prNumber).sort()).toEqual([101, 102, 103]);
  });

  it('includes MERGED pull requests, which the old open-only GitHub query excluded', async () => {
    const { body } = await get();
    const pr = body.prs.find((p) => p.prNumber === 101)!;
    expect(pr).toMatchObject({
      repoFullName: 'UA-MIS/ida-llm',
      merged: true,
      prState: 'merged',
      url: 'https://github.com/UA-MIS/ida-llm/pull/101',
      checksState: 'success',
    });
  });

  it('includes OPEN pull requests too, so the endpoint is not merged-only either', async () => {
    const { body } = await get();
    expect(body.prs.find((p) => p.prNumber === 102)).toMatchObject({ merged: false, prState: 'open' });
  });

  it('names the item each PR is attached to', async () => {
    const { body } = await get();
    expect(body.prs.find((p) => p.prNumber === 101)!.items).toEqual([
      { id: seeded.merged, title: 'Harness core' },
    ]);
  });

  it('reports a PR attached to two items ONCE, listing both items', async () => {
    const { body } = await get();
    const shared = body.prs.filter((p) => p.prNumber === 103);
    expect(shared).toHaveLength(1);
    expect((shared[0]!.items as Array<{ id: number }>).map((i) => i.id).sort((a, b) => a - b)).toEqual(
      [seeded.open, seeded.shared].sort((a, b) => a - b),
    );
  });

  it('AGREES with /summary about the merged pull requests — the two now read one source', async () => {
    const { body } = await get();
    const s = await summary.boardSummary('2026-08-25');
    const mergedFromPrs = body.prs.filter((p) => p.merged);
    // /summary counts link rows; /prs reports distinct PRs. Both must see the
    // same PRs, which is the disagreement AB#29 reported.
    expect(new Set(s.recentMergedPrs.map((p) => `${p.repoFullName}#${p.prNumber}`))).toEqual(
      new Set(mergedFromPrs.map((p) => `${p.repoFullName}#${p.prNumber}`)),
    );
    expect(s.mergedPrCount).toBeGreaterThan(0);
  });

  it('needs NO GitHub credential — no note, no outbound call, on a board with none configured', async () => {
    const { body } = await get();
    expect(body.note).toBeUndefined();
    expect(body.prs.length).toBe(3);
  });

  it('still annotates AB#<id> references found in the PR title', async () => {
    const { body } = await get();
    expect(body.prs.find((p) => p.prNumber === 101)!.suggestedItemIds).toEqual([seeded.merged]);
  });

  it('does not leak another board instance’s pull requests', async () => {
    await db.query(`UPDATE work_items SET instance_key = 'other-board' WHERE id = $1`, [seeded.merged]);
    try {
      const { body } = await get();
      expect(body.prs.map((p) => p.prNumber).sort()).toEqual([102, 103]);
    } finally {
      await db.query(`UPDATE work_items SET instance_key = 'test-instance' WHERE id = $1`, [seeded.merged]);
    }
  });

  it('still requires authentication — a bad token is refused, not answered with data', async () => {
    // A bearer is used rather than the anonymous path because `cookies()` needs
    // a Next request scope that a unit test does not have; the point being
    // pinned is that the rewritten route is still behind `withApi`.
    const res = await route.GET(
      new Request('http://localhost:3000/api/v1/prs', {
        headers: { authorization: 'Bearer iag_definitely-not-a-real-token' },
      }),
    );
    expect(res.status).toBe(401);
    expect(await res.json()).toMatchObject({ error: { code: 'bad_token' } });
  });
});
