import { describe, it, expect, beforeAll, afterAll, beforeEach, vi } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_start_work_route_test';
installTestEnv(SCHEMA);
const d = hasDb ? describe : describe.skip;

const REPO = 'UA-MIS/ida-llm';

/**
 * Authenticate as a signed-in member holding a GitHub token, so the route runs
 * its real branch path and every GitHub call is visible on the stubbed fetch.
 */
vi.mock('@/lib/auth/principal', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/auth/principal')>();
  return {
    ...actual,
    authenticate: async () => ({
      ok: true as const,
      principal: {
        login: 'ccsmith33',
        source: 'user' as const,
        credential: 'session' as const,
        githubToken: 'gho_test',
        avatarUrl: '',
        name: 'Clayton',
      },
    }),
  };
});

/**
 * The end of the AB#25 story, at the endpoint a user actually presses.
 *
 * Starting a research spike created `spike/25-surface-catalog-...` — a ref a
 * literature review can never push to, deleted unused a day later, leaving an
 * open card pointing at a 404.
 */
d('POST /items/{id}/start-work (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');
  let POST: typeof import('@/app/api/v1/items/[id]/start-work/route').POST;

  /** Every GitHub URL the route touched during one call. */
  let githubCalls: string[] = [];

  const BASE = {
    description: '',
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

  function stubGitHub() {
    githubCalls = [];
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      githubCalls.push(`${init?.method ?? 'GET'} ${url}`);
      // The ref does not exist yet...
      if (url.includes('/git/ref/heads/') && !url.includes('heads/main')) {
        return new Response(JSON.stringify({ message: 'Not Found' }), { status: 404 });
      }
      if (url.includes('/git/ref/heads/main')) {
        return new Response(JSON.stringify({ object: { sha: 'basesha' } }), { status: 200 });
      }
      if (url === `https://api.github.com/repos/${REPO}`) {
        return new Response(JSON.stringify({ default_branch: 'main' }), { status: 200 });
      }
      // ...so creating it succeeds.
      if (url.endsWith('/git/refs')) {
        return new Response(JSON.stringify({ object: { sha: 'newsha' } }), { status: 201 });
      }
      return new Response('{}', { status: 200 });
    });
  }

  /** Did anything actually create a ref on GitHub? */
  const branchWasCreated = () => githubCalls.some((c) => c.startsWith('POST') && c.endsWith('/git/refs'));

  async function startWork(id: number, body?: unknown) {
    const res = await POST(
      new Request(`http://localhost/api/v1/items/${id}/start-work`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body ?? {}),
      }),
      { params: Promise.resolve({ id: String(id) }) },
    );
    return { res, body: (await res.json()) as Record<string, never> };
  }

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();
    q = await import('@/lib/domain/queries');
    POST = (await import('@/app/api/v1/items/[id]/start-work/route')).POST;
  });

  afterAll(async () => {
    vi.unstubAllGlobals();
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  beforeEach(stubGitHub);

  it('starts a SPIKE with no branch at all — Active, assigned, nothing in git', async () => {
    const spike = await q.createWorkItem(
      { ...BASE, title: 'Surface catalog: UA licenses + campus AI policy + FERPA', itemType: 'Spike' },
      'tester',
    );

    const { res, body } = await startWork(spike.id);

    expect(res.status).toBe(200);
    const item = body.item as unknown as import('@/lib/domain/workitem').WorkItem;
    expect(item.state).toBe('Active');
    expect(item.assigneeLogin).toBe('ccsmith33');

    // The whole point: no branch, no branch metadata, and NO GitHub write.
    expect(item.branchName).toBeNull();
    expect(item.branchUrl).toBeNull();
    expect(item.branchRepo).toBeNull();
    expect((body.branch as unknown as { status: string }).status).toBe('skipped');
    expect(branchWasCreated()).toBe(false);
    expect(githubCalls).toEqual([]);

    // Skipping a branch is the designed outcome, not a degradation.
    expect(body.warnings).toEqual([]);
  });

  it('starts a TASK with no branch either', async () => {
    const task = await q.createWorkItem({ ...BASE, title: 'Book the demo room', itemType: 'Task' }, 'tester');

    const { body } = await startWork(task.id);

    expect((body.item as unknown as { state: string }).state).toBe('Active');
    expect((body.item as unknown as { branchName: string | null }).branchName).toBeNull();
    expect(branchWasCreated()).toBe(false);
  });

  it('starts a STORY exactly as before — the branch is created', async () => {
    const story = await q.createWorkItem({ ...BASE, title: 'Judge calibration refresh', itemType: 'Story' }, 'tester');

    const { res, body } = await startWork(story.id);

    expect(res.status).toBe(200);
    const item = body.item as unknown as import('@/lib/domain/workitem').WorkItem;
    expect(item.state).toBe('Active');
    expect(item.branchName).toBe(`story/${story.id}-judge-calibration-refresh`);
    expect(branchWasCreated()).toBe(true);

    const branch = body.branch as unknown as { status: string; name: string; checkout: string };
    expect(branch.status).toBe('created');
    // The existing branch-prefix behaviour is preserved verbatim.
    expect(branch.name.startsWith('story/')).toBe(true);
    expect(branch.checkout).toBe(`git fetch origin && git switch ${branch.name}`);
  });

  it('starts a BUG with a branch too', async () => {
    const bug = await q.createWorkItem({ ...BASE, title: 'Logout ignores CSRF', itemType: 'Bug' }, 'tester');

    const { body } = await startWork(bug.id);

    expect((body.item as unknown as { branchName: string }).branchName).toBe(
      `bug/${bug.id}-logout-ignores-csrf`,
    );
    expect(branchWasCreated()).toBe(true);
  });

  it('lets a spike opt IN to a branch when it genuinely wants one', async () => {
    const spike = await q.createWorkItem({ ...BASE, title: 'Prototype the retriever', itemType: 'Spike' }, 'tester');

    const { body } = await startWork(spike.id, { branch: true });

    expect((body.branch as unknown as { status: string }).status).toBe('created');
    expect((body.item as unknown as { branchName: string }).branchName).toBe(
      `spike/${spike.id}-prototype-the-retriever`,
    );
  });

  it('lets a story opt OUT of one', async () => {
    const story = await q.createWorkItem({ ...BASE, title: 'Thinking first', itemType: 'Story' }, 'tester');

    const { body } = await startWork(story.id, { branch: false });

    expect((body.branch as unknown as { status: string }).status).toBe('skipped');
    expect((body.item as unknown as { state: string }).state).toBe('Active');
    expect(branchWasCreated()).toBe(false);
  });

  it('rejects a misspelled option instead of silently using the default', async () => {
    const spike = await q.createWorkItem({ ...BASE, title: 'Typo guard', itemType: 'Spike' }, 'tester');

    const { res, body } = await startWork(spike.id, { branches: true });

    expect(res.status).toBe(422);
    expect((body.error as unknown as { code: string }).code).toBe('validation_failed');
    expect((await q.getWorkItem(spike.id))?.state).toBe('New');
  });

  it('lets a lead start a card without silently claiming it', async () => {
    const story = await q.createWorkItem({ ...BASE, title: 'For someone else', itemType: 'Story' }, 'tester');

    const { body } = await startWork(story.id, { assign: false });

    expect((body.item as unknown as { state: string }).state).toBe('Active');
    expect((body.item as unknown as { assigneeLogin: string | null }).assigneeLogin).toBeNull();
  });

  it('does not steal an item that already has an owner', async () => {
    const story = await q.createWorkItem(
      { ...BASE, title: 'Already claimed', itemType: 'Story', assigneeLogin: 'someone-else' },
      'tester',
    );

    const { body } = await startWork(story.id);

    expect((body.item as unknown as { assigneeLogin: string }).assigneeLogin).toBe('someone-else');
  });
});

/**
 * The endpoint answered 200 to `PATCH {"branchName": null}` and changed
 * nothing — the caller's only signal said the dead branch link was cleared.
 */
d('PATCH /items/{id} — unknown fields are refused, not ignored (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let q: typeof import('@/lib/domain/queries');
  let PATCH: typeof import('@/app/api/v1/items/[id]/route').PATCH;

  const SCHEMA2 = SCHEMA;

  async function patch(id: number, body: unknown) {
    const res = await PATCH(
      new Request(`http://localhost/api/v1/items/${id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      }),
      { params: Promise.resolve({ id: String(id) }) },
    );
    return { res, body: (await res.json()) as Record<string, never> };
  }

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA2} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();
    q = await import('@/lib/domain/queries');
    PATCH = (await import('@/app/api/v1/items/[id]/route')).PATCH;
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA2} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  async function seeded() {
    const item = await q.createWorkItem(
      {
        title: 'Surface catalog',
        description: 'research',
        itemType: 'Spike',
        state: 'New',
        assigneeLogin: null,
        assigneeAvatarUrl: null,
        storyPoints: null,
        priority: 2,
        sprintId: null,
        tags: ['policy'],
        repoFullName: REPO,
        wave: 'Wave 1',
      },
      'tester',
    );
    await q.setItemBranch(
      item.id,
      { repoFullName: REPO, name: 'spike/25-surface-catalog', url: `https://github.com/${REPO}/tree/x` },
      'tester',
    );
    return item.id;
  }

  it('answers 422 to the body that used to answer 200 and do nothing', async () => {
    const id = await seeded();

    const { res, body } = await patch(id, { branchName: null });

    expect(res.status).toBe(422);
    const error = body.error as unknown as { code: string; fields: Record<string, string[]> };
    expect(error.code).toBe('validation_failed');
    expect(error.fields.branchName?.[0]).toContain('branchName');

    // Still set — a 422 must not half-apply anything either.
    expect((await q.getWorkItem(id))?.branchName).toBe('spike/25-surface-catalog');
  });

  it('refuses the whole body when one key is unknown, and writes nothing', async () => {
    const id = await seeded();

    const { res } = await patch(id, { title: 'Renamed', branchName: null });

    expect(res.status).toBe(422);
    expect((await q.getWorkItem(id))?.title).toBe('Surface catalog');
  });

  it('still applies a legitimate partial patch, untouched by the strictness (AB#28)', async () => {
    const id = await seeded();

    const { res, body } = await patch(id, { assigneeLogin: 'ccsmith33' });

    expect(res.status).toBe(200);
    const item = body.item as unknown as import('@/lib/domain/workitem').WorkItem;
    expect(item.assigneeLogin).toBe('ccsmith33');
    // The fields a partial patch must never touch.
    expect(item.wave).toBe('Wave 1');
    expect(item.description).toBe('research');
    expect(item.repoFullName).toBe(REPO);
    expect(item.tags).toEqual(['policy']);
  });

  it('still honours an explicit null as a deliberate clear', async () => {
    const id = await seeded();
    const sprint = await q.createSprint({
      name: 'Sprint 9',
      goal: '',
      startsOn: '2026-08-01',
      endsOn: '2026-08-14',
      position: 0,
    });
    await patch(id, { sprintId: sprint.id });

    const { res, body } = await patch(id, { sprintId: null });

    expect(res.status).toBe(200);
    expect((body.item as unknown as { sprintId: number | null }).sprintId).toBeNull();
  });
});
