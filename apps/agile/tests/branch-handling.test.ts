import { describe, it, expect } from 'vitest';
import { installTestEnv } from './helpers/db';
import {
  BRANCHING_ITEM_TYPES,
  WORK_ITEM_TYPES,
  createWorkItemRequestSchema,
  createWorkItemSchema,
  shouldCreateBranch,
  startWorkSchema,
  typeCreatesBranch,
  updateWorkItemSchema,
} from '@/lib/domain/workitem';
import { seedSchema } from '@/lib/api/seed';
import { buildOpenApiDocument } from '@/lib/api/openapi';
import { validationError } from '@/lib/api/respond';
import { clearGitHubCaches, listCommitsAheadOfBase } from '@/lib/github/client';

installTestEnv('agile_branch_handling_test');

/**
 * The board cut a branch for EVERY item type. Item 25 is a research spike —
 * "what does UA license / what does campus AI policy say / FERPA" — and
 * "Start work" handed it `spike/25-surface-catalog-...`, a ref that research
 * can never push to and that was deleted unused, leaving the card advertising
 * a 404. Branching belongs to the types whose work ends in a diff.
 *
 * No database: this is the layer the bug lived at, and CI runs `npm test`
 * without a DATABASE_URL, so this is the layer that has to gate.
 */
describe('which item types get a branch', () => {
  it('branches Story and Bug — the types that end in a diff', () => {
    expect(typeCreatesBranch('Story')).toBe(true);
    expect(typeCreatesBranch('Bug')).toBe(true);
  });

  it('does NOT branch Spike or Task — research and coordination (AB#25)', () => {
    expect(typeCreatesBranch('Spike')).toBe(false);
    expect(typeCreatesBranch('Task')).toBe(false);
  });

  it('classifies every known type, so a new type cannot silently default to branching', () => {
    for (const type of WORK_ITEM_TYPES) {
      expect(typeof typeCreatesBranch(type), `${type} must be classified`).toBe('boolean');
    }
    expect([...BRANCHING_ITEM_TYPES].sort()).toEqual(['Bug', 'Story']);
  });

  it('uses the type default when the caller says nothing', () => {
    for (const type of WORK_ITEM_TYPES) {
      expect(shouldCreateBranch(type), type).toBe(typeCreatesBranch(type));
      expect(shouldCreateBranch(type, undefined), `${type} (explicit undefined)`).toBe(
        typeCreatesBranch(type),
      );
    }
  });

  it('lets a caller override in either direction', () => {
    // A spike that genuinely wants a scratch branch may ask for one...
    expect(shouldCreateBranch('Spike', true)).toBe(true);
    // ...and a story may decline one.
    expect(shouldCreateBranch('Story', false)).toBe(false);
  });
});

describe('start-work body validation', () => {
  it('accepts the empty body every UI caller sends', () => {
    expect(startWorkSchema.parse({})).toEqual({});
  });

  it('accepts the documented options', () => {
    expect(startWorkSchema.parse({ branch: false })).toEqual({ branch: false });
    expect(startWorkSchema.parse({ activate: false })).toEqual({ activate: false });
    expect(startWorkSchema.parse({ assign: false })).toEqual({ assign: false });
    expect(startWorkSchema.parse({ repo: 'UA-MIS/ida-llm' })).toEqual({ repo: 'UA-MIS/ida-llm' });
  });

  it('rejects a misspelled option rather than reading it as the default', () => {
    // {"branches": false} must not quietly mean "use the type default".
    expect(startWorkSchema.safeParse({ branches: false }).success).toBe(false);
    expect(startWorkSchema.safeParse({ branch: 'no' }).success).toBe(false);
    expect(startWorkSchema.safeParse({ repo: 'not-a-repo' }).success).toBe(false);
  });
});

/**
 * `PATCH {"branchName": null}` — the obvious way to clear a dead branch link —
 * returned 200 and changed nothing, because branchName is not a writable field
 * and unknown keys were dropped. "The API said 200 and you believed it" is the
 * same family as AB#28's silent field-clearing.
 */
describe('PATCH /items/{id} rejects unknown fields (422, not a silent 200)', () => {
  it('rejects the exact body that used to 200 and no-op', () => {
    const parsed = updateWorkItemSchema.safeParse({ branchName: null });
    expect(parsed.success).toBe(false);
  });

  it('rejects every branch-metadata field, not just branchName', () => {
    for (const field of ['branchName', 'branchRepo', 'branchUrl', 'branchCreatedAt']) {
      expect(updateWorkItemSchema.safeParse({ [field]: null }).success, field).toBe(false);
    }
  });

  it('rejects a derived/read-only field a client might reasonably guess at', () => {
    for (const field of ['commitCount', 'id', 'createdAt', 'mergedPrCount', 'boardRank']) {
      expect(updateWorkItemSchema.safeParse({ [field]: 1 }).success, field).toBe(false);
    }
  });

  it('rejects an unknown key even alongside perfectly valid ones', () => {
    // The dangerous shape: the caller sees their title change and assumes the
    // rest of the body applied too.
    expect(updateWorkItemSchema.safeParse({ title: 'Fine', branchName: null }).success).toBe(false);
  });

  it('answers 422 validation_failed and NAMES the offending key', async () => {
    const parsed = updateWorkItemSchema.safeParse({ branchName: null });
    if (parsed.success) throw new Error('expected a validation failure');

    const res = validationError(parsed.error);
    expect(res.status).toBe(422);

    const body = (await res.json()) as {
      error: { code: string; fields?: Record<string, string[]> };
    };
    expect(body.error.code).toBe('validation_failed');
    // Filed under the key itself — Zod reports unrecognized keys with an EMPTY
    // path, so without unpacking they all landed under "_" and the client was
    // told "invalid" without being told what.
    expect(Object.keys(body.error.fields ?? {})).toContain('branchName');
    expect(body.error.fields?.branchName?.[0]).toContain('branchName');
  });

  it('still accepts every legitimate partial patch — merge-patch is unchanged (AB#28)', () => {
    expect(updateWorkItemSchema.parse({ assigneeLogin: 'ccsmith33' })).toEqual({
      assigneeLogin: 'ccsmith33',
    });
    expect(updateWorkItemSchema.parse({})).toEqual({});
    expect(updateWorkItemSchema.parse({ title: 'Renamed' })).toEqual({ title: 'Renamed' });
    // An explicit null is a deliberate clear and must keep working.
    const cleared = updateWorkItemSchema.parse({ sprintId: null });
    expect('sprintId' in cleared).toBe(true);
    expect(cleared.sprintId).toBeNull();
  });

  it('accepts a body containing every writable field at once', () => {
    const full = {
      title: 'Everything',
      description: 'body',
      itemType: 'Story' as const,
      state: 'Active' as const,
      assigneeLogin: 'octocat',
      assigneeAvatarUrl: 'https://example.com/a.png',
      storyPoints: 3,
      priority: 1,
      sprintId: 2,
      tags: ['eval'],
      repoFullName: 'UA-MIS/ida-llm',
      wave: 'Wave 1',
    };
    expect(updateWorkItemSchema.parse(full)).toEqual(full);
  });

  it('the exact payload the edit dialog sends is still accepted', () => {
    // WorkItemDialog serialises this draft verbatim; strictness must not break it.
    const draft = {
      title: 'Port the skeleton',
      description: '# Heading',
      itemType: 'Story' as const,
      state: 'New' as const,
      assigneeLogin: null,
      assigneeAvatarUrl: null,
      storyPoints: 5,
      priority: 1,
      sprintId: null,
      tags: ['groundwork'],
    };
    expect(updateWorkItemSchema.safeParse(draft).success).toBe(true);
  });
});

/**
 * The same silent-drop defect as fix 4, on the create path: `POST {"branchName":
 * null}` used to 201 and quietly discard the key. Strictness lives at the HTTP
 * boundary rather than on the shared schema, because `createWorkItem()`
 * re-parses through that schema and `/seed` legitimately hands it a wider
 * object.
 */
describe('POST /items rejects unknown fields, without breaking /seed', () => {
  it('refuses an unknown key at the request boundary', () => {
    expect(createWorkItemRequestSchema.safeParse({ title: 'x', branchName: null }).success).toBe(false);
    expect(createWorkItemRequestSchema.safeParse({ title: 'x', commitCount: 3 }).success).toBe(false);
  });

  it('still applies every create default', () => {
    expect(createWorkItemRequestSchema.parse({ title: 'Fresh' })).toEqual({
      title: 'Fresh',
      description: '',
      itemType: 'Story',
      state: 'New',
      assigneeLogin: null,
      assigneeAvatarUrl: null,
      storyPoints: null,
      priority: 2,
      sprintId: null,
      tags: [],
      repoFullName: null,
      wave: null,
    });
  });

  it('leaves the INTERNAL schema lenient, so the seed path keeps working', () => {
    // `/seed` calls createWorkItem({...item, sprintId}) with `key`, `sprintKey`
    // and `dependsOn` still attached, and createWorkItem re-parses through
    // createWorkItemSchema. Making that schema strict would 500 the seed
    // endpoint on its own payload.
    expect(
      createWorkItemSchema.safeParse({
        title: 'Seeded',
        key: 'story-a',
        sprintKey: 'sprint-1',
        dependsOn: ['story-b'],
      }).success,
    ).toBe(true);
  });

  it('accepts a realistic seed payload end to end', () => {
    const parsed = seedSchema.safeParse({
      sprints: [{ key: 's1', name: 'Sprint 1', startsOn: '2026-08-01', endsOn: '2026-08-14' }],
      items: [
        { key: 'a', title: 'First', itemType: 'Story', sprintKey: 's1' },
        { key: 'b', title: 'Second', dependsOn: ['a'] },
      ],
    });
    expect(parsed.success).toBe(true);
  });

  it('but a mistyped seed key fails loudly instead of vanishing', () => {
    // A silently-dropped `dependsOnn` in a 500-item seed leaves the dependency
    // graph quietly wrong, which is the worst possible outcome for a seed.
    const parsed = seedSchema.safeParse({
      items: [{ title: 'First', dependsOnn: ['a'] }],
    });
    expect(parsed.success).toBe(false);
  });
});

/**
 * The machine-readable contract has to change when the behaviour does.
 * `docs/api.md` documented strict PATCH while the OpenAPI document still
 * pointed PATCH at the CREATE schema and advertised no 422 — so a generated
 * client would send `title` as required and believe unknown fields were fine.
 */
describe('OpenAPI reflects the endpoints this PR changed', () => {
  const doc = buildOpenApiDocument() as {
    paths: Record<string, Record<string, { requestBody?: unknown; responses: Record<string, unknown> }>>;
    components: { schemas: Record<string, { additionalProperties?: unknown; required?: string[]; properties: Record<string, unknown> }> };
  };

  it('points PATCH at an update schema, not the create schema', () => {
    const patch = doc.paths['/api/v1/items/{id}']!.patch!;
    const ref = JSON.stringify(patch.requestBody);
    expect(ref).toContain('UpdateWorkItem');
    expect(ref).not.toContain('CreateWorkItem');
  });

  it('documents 422 on PATCH — the headline client-visible change', () => {
    expect(Object.keys(doc.paths['/api/v1/items/{id}']!.patch!.responses)).toContain('422');
  });

  it('declares both write schemas closed, matching the server', () => {
    expect(doc.components.schemas.UpdateWorkItem!.additionalProperties).toBe(false);
    expect(doc.components.schemas.CreateWorkItem!.additionalProperties).toBe(false);
  });

  it('makes no field required on update, and only title on create', () => {
    expect(doc.components.schemas.UpdateWorkItem!.required).toBeUndefined();
    expect(doc.components.schemas.CreateWorkItem!.required).toEqual(['title']);
  });

  it('publishes exactly the writable field set the server accepts', () => {
    const published = Object.keys(doc.components.schemas.UpdateWorkItem!.properties).sort();
    // Derived from the schema itself, so the contract cannot drift from it.
    const actual = Object.keys(updateWorkItemSchema.shape).sort();
    expect(published).toEqual(actual);
  });

  it('documents the start-work branch and assign overrides', () => {
    const body = JSON.stringify(doc.paths['/api/v1/items/{id}/start-work']!.post!.requestBody);
    expect(body).toContain('branch');
    expect(body).toContain('additionalProperties');
  });
});

// ---------------------------------------------------------------------------

const REPO = 'UA-MIS/ida-llm';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function commit(sha: string) {
  return {
    sha,
    html_url: `https://github.com/${REPO}/commit/${sha}`,
    author: { login: 'ccsmith33' },
    commit: { message: `work ${sha}`, author: { name: 'Clayton', date: '2026-08-25T12:00:00Z' } },
  };
}

/**
 * Item 25 displayed `commitCount: 20` on a branch nobody had ever pushed to.
 * They were main's commits: the poller listed the branch with
 * `GET /commits?sha={branch}`, which returns the branch's whole ANCESTRY, and
 * a freshly-cut branch's ancestry IS the base branch's history.
 */
describe('listCommitsAheadOfBase — the base branch is not the item\'s work', () => {
  /** Serves the repo's default branch, then whatever compare result is given. */
  function stub(compare: unknown, status = 200) {
    clearGitHubCaches();
    const calls: string[] = [];
    const fetchImpl = (async (url: string | URL | Request) => {
      const href = String(url);
      calls.push(href);
      if (href === `https://api.github.com/repos/${REPO}`) {
        return jsonResponse({ default_branch: 'main' });
      }
      return jsonResponse(compare, status);
    }) as unknown as typeof fetch;
    return { fetchImpl, calls };
  }

  /**
   * A stub that PAGINATES the way GitHub really does: `commits` is oldest-first
   * and truncated to one page, while `total_commits` reports the whole
   * ahead-count. A stub that hands back the entire array in one response — as
   * the first version of this suite did — cannot see the bug in MED-3, because
   * pagination never happens.
   */
  function paginatingStub(total: number, pageSize = 100) {
    clearGitHubCaches();
    const all = Array.from({ length: total }, (_, i) => commit(`c${i}`));
    const calls: string[] = [];
    const fetchImpl = (async (url: string | URL | Request) => {
      const href = String(url);
      calls.push(href);
      if (href === `https://api.github.com/repos/${REPO}`) {
        return jsonResponse({ default_branch: 'main' });
      }
      const page = Number(new URL(href).searchParams.get('page') ?? '1');
      const slice = all.slice((page - 1) * pageSize, page * pageSize);
      return jsonResponse({ total_commits: total, ahead_by: total, commits: slice });
    }) as unknown as typeof fetch;
    return { fetchImpl, calls, all };
  }

  it('reports ZERO for a branch sitting at the base branch tip', async () => {
    // What GitHub returns the moment "Start work" cuts the ref: nothing ahead.
    const { fetchImpl } = stub({ ahead_by: 0, behind_by: 0, commits: [] });
    const commits = await listCommitsAheadOfBase(REPO, 'spike/25-surface-catalog', 'tok', fetchImpl);
    expect(commits).toHaveLength(0);
  });

  it('reports only the N commits actually pushed to the branch', async () => {
    const { fetchImpl } = stub({
      ahead_by: 3,
      behind_by: 0,
      commits: [commit('aaa'), commit('bbb'), commit('ccc')],
    });
    const commits = await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl);
    expect(commits).toHaveLength(3);
    expect(commits.map((c) => c.sha)).toEqual(['aaa', 'bbb', 'ccc']);
    expect(commits[0]!.message).toBe('work aaa');
    expect(commits[0]!.authorLogin).toBe('ccsmith33');
  });

  it('asks GitHub to COMPARE against the base, never to list the branch', async () => {
    const { fetchImpl, calls } = stub({ ahead_by: 0, commits: [] });
    await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl);

    const compared = calls.find((c) => c.includes('/compare/'));
    expect(compared, 'must use the compare endpoint').toBeTruthy();
    expect(compared).toContain('main...story%2F42-judge');
    // The ancestry-walking call is the bug; it must not happen at all.
    expect(calls.some((c) => c.includes('/commits?sha='))).toBe(false);
  });

  it('never attributes the base branch to an item, even asked for it directly', async () => {
    const { fetchImpl, calls } = stub({ ahead_by: 0, commits: [] });
    expect(await listCommitsAheadOfBase(REPO, 'main', 'tok', fetchImpl)).toEqual([]);
    // Short-circuited: comparing main with itself is not even worth the call.
    expect(calls.some((c) => c.includes('/compare/'))).toBe(false);
  });

  it('keeps the most RECENT commits when a branch is longer than the limit', async () => {
    // compare returns oldest-first, so a naive slice(0, n) would keep the oldest.
    const many = Array.from({ length: 8 }, (_, i) => commit(`c${i}`));
    const { fetchImpl } = stub({ total_commits: 8, ahead_by: 8, commits: many });
    const commits = await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl, 3);
    expect(commits.map((c) => c.sha)).toEqual(['c5', 'c6', 'c7']);
  });

  it('keeps the NEWEST commits on a branch further ahead than one page', async () => {
    // The bug this guards: GitHub returns the FIRST page of an oldest-first
    // list, so a single request on a 300-ahead branch holds commits 0..99 and
    // slicing its tail yields the MIDDLE of the branch, never the newest.
    const { fetchImpl } = paginatingStub(300);

    const commits = await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl, 50);

    expect(commits).toHaveLength(50);
    expect(commits[0]!.sha).toBe('c250');
    expect(commits.at(-1)!.sha).toBe('c299');
    // Not the tail of page one, which is what the naive slice returned.
    expect(commits.map((c) => c.sha)).not.toContain('c99');
  });

  it('still fills the limit when the final page holds only a handful', async () => {
    // 101 ahead => the last page has exactly ONE commit. Reading only that page
    // would return 1 instead of the 50 most recent.
    const { fetchImpl } = paginatingStub(101);

    const commits = await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl, 50);

    expect(commits).toHaveLength(50);
    expect(commits.at(-1)!.sha).toBe('c100');
    expect(commits[0]!.sha).toBe('c51');
  });

  it('makes exactly one compare request when the branch fits in a page', async () => {
    const { fetchImpl, calls } = paginatingStub(12);

    await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl, 50);

    expect(calls.filter((c) => c.includes('/compare/'))).toHaveLength(1);
  });

  it('fails soft on the COMPARE call — a commit count must never break reconciliation', async () => {
    const { fetchImpl } = stub({ message: 'Not Found' }, 404);
    expect(await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl)).toEqual([]);

    const { fetchImpl: weird } = stub({ ahead_by: 2 }); // no commits array at all
    expect(await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', weird)).toEqual([]);
  });

  it('does NOT fail soft when the base branch itself cannot be read', async () => {
    // A rate-limited GitHub must not be indistinguishable from "0 ahead" —
    // that is the wrong-but-plausible answer AB#25 was. The poller turns this
    // throw into a visible warning.
    clearGitHubCaches();
    const rateLimited = (async () =>
      jsonResponse({ message: 'API rate limit exceeded' }, 403)) as unknown as typeof fetch;

    await expect(
      listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', rateLimited),
    ).rejects.toThrow(/Could not read repository/);
  });

  it('asks for the repo default branch ONCE, then serves it from cache', async () => {
    // Uncached this cost a GET /repos/{repo} per item per poll cycle, all
    // returning the same immutable string against a shared org rate budget.
    const { fetchImpl, calls } = paginatingStub(3);

    await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl);
    await listCommitsAheadOfBase(REPO, 'story/43-other', 'tok', fetchImpl);
    await listCommitsAheadOfBase(REPO, 'story/44-third', 'tok', fetchImpl);

    expect(calls.filter((c) => c === `https://api.github.com/repos/${REPO}`)).toHaveLength(1);
    expect(calls.filter((c) => c.includes('/compare/'))).toHaveLength(3);
  });

  it('does not cache a FAILED default-branch lookup', async () => {
    clearGitHubCaches();
    let attempt = 0;
    const flaky = (async (url: string | URL | Request) => {
      const href = String(url);
      if (href === `https://api.github.com/repos/${REPO}`) {
        attempt += 1;
        return attempt === 1
          ? jsonResponse({ message: 'rate limited' }, 403)
          : jsonResponse({ default_branch: 'main' });
      }
      return jsonResponse({ total_commits: 0, commits: [] });
    }) as unknown as typeof fetch;

    await expect(listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', flaky)).rejects.toThrow();
    // A 403 must not pin an absence for half an hour; the retry re-asks.
    await expect(listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', flaky)).resolves.toEqual([]);
    expect(attempt).toBe(2);
  });
});
