import { describe, it, expect } from 'vitest';
import { installTestEnv } from './helpers/db';
import {
  BRANCHING_ITEM_TYPES,
  WORK_ITEM_TYPES,
  shouldCreateBranch,
  startWorkSchema,
  typeCreatesBranch,
  updateWorkItemSchema,
} from '@/lib/domain/workitem';
import { validationError } from '@/lib/api/respond';
import { listCommitsAheadOfBase } from '@/lib/github/client';

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
    const { fetchImpl } = stub({ ahead_by: 8, commits: many });
    const commits = await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl, 3);
    expect(commits.map((c) => c.sha)).toEqual(['c5', 'c6', 'c7']);
  });

  it('fails soft — a commit count must never break reconciliation', async () => {
    const { fetchImpl } = stub({ message: 'Not Found' }, 404);
    expect(await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', fetchImpl)).toEqual([]);

    const { fetchImpl: weird } = stub({ ahead_by: 2 }); // no commits array at all
    expect(await listCommitsAheadOfBase(REPO, 'story/42-judge', 'tok', weird)).toEqual([]);
  });
});
