import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { sealSession, unsealSession } from '@/lib/auth/session';
import { sessionStillValid, clearRevalidationCache } from '@/lib/auth/revalidate';
import { githubActionCredential, githubReadToken } from '@/lib/github/credential';
import { startWork } from '@/lib/github/branches';
import type { WorkItem } from '@/lib/domain/workitem';

/**
 * Regression cover for the Dex migration's seam.
 *
 * The original design put the user's GitHub token in the session, and several
 * paths quietly depended on it. A Dex session carries identity and groups but
 * NO GitHub credential — so every one of those paths needs explicit cover with
 * `githubToken: null`, which is exactly the shape the earlier tests lacked.
 */
const SECRET = 'd'.repeat(48);

/** What a Dex-authenticated session actually looks like. */
const dexSession = {
  login: 'clayton',
  name: 'Clayton',
  avatarUrl: '',
  token: '', // ← the whole point: no GitHub credential
  groups: ['UA-MIS:ida-llm'],
  provider: 'oidc' as const,
};

beforeEach(() => {
  clearRevalidationCache();
  process.env.SESSION_SECRET = SECRET;
  process.env.GITHUB_ORG = 'UA-MIS';
  process.env.GITHUB_TEAM = 'ida-llm';
  process.env.GITHUB_REPOS = 'UA-MIS/ida-llm';
  process.env.APP_URL = 'https://ida-agile.capstone.uamishub.com';
  process.env.AUTH_PROVIDER = 'oidc';
  process.env.OIDC_ISSUER = 'https://id.capstone.uamishub.com';
  process.env.OIDC_CLIENT_ID = 'ida-agile';
  delete process.env.GITHUB_POLL_TOKEN;
  delete process.env.REQUIRED_GROUP;
});

afterEach(() => {
  delete process.env.AUTH_PROVIDER;
  delete process.env.GITHUB_POLL_TOKEN;
});

describe('a Dex session round-trips without a GitHub token', () => {
  it('preserves identity, groups and provider', () => {
    const out = unsealSession(sealSession(dexSession, SECRET), SECRET);
    expect(out).toMatchObject({ login: 'clayton', provider: 'oidc', token: '' });
    expect(out?.groups).toEqual(['UA-MIS:ida-llm']);
  });
});

describe('session revalidation for a Dex user', () => {
  it('stays valid — a Dex user is never stuck in an unresolvable state', async () => {
    expect(await sessionStillValid(dexSession)).toBe(true);
  });

  it('FAILS CLOSED when the qualifying group is gone from the session', async () => {
    expect(await sessionStillValid({ ...dexSession, groups: ['UA-MIS:other-team'] })).toBe(false);
    expect(await sessionStillValid({ ...dexSession, groups: [] })).toBe(false);
  });

  it('FAILS CLOSED when REQUIRED_GROUP is changed to something the user lacks', async () => {
    process.env.REQUIRED_GROUP = 'UA-MIS:staff-only';
    expect(await sessionStillValid(dexSession)).toBe(false);
  });

  it('revalidates by the provider that ISSUED the session, not the current default', async () => {
    // Deployment has since switched to github, but this session came from Dex
    // and must still be judged by its groups claim rather than a GitHub call.
    process.env.AUTH_PROVIDER = 'github';
    expect(await sessionStillValid(dexSession)).toBe(true);
    expect(await sessionStillValid({ ...dexSession, groups: [] })).toBe(false);
  });

  it('a GitHub-provider session with no token is kept, not revoked', async () => {
    // "Cannot tell" must never revoke on its own.
    const ghSession = { ...dexSession, provider: 'github' as const, token: '', groups: [] };
    expect(await sessionStillValid(ghSession)).toBe(true);
  });
});

describe('credential selection for a Dex principal', () => {
  const dexPrincipal = { githubToken: null };

  it('has no read credential until the app token is configured', () => {
    expect(githubReadToken(dexPrincipal)).toBeNull();
    process.env.GITHUB_POLL_TOKEN = 'gho_app';
    expect(githubReadToken(dexPrincipal)).toBe('gho_app');
  });

  it('uses the app credential for actions, and says so', () => {
    process.env.GITHUB_POLL_TOKEN = 'gho_app';
    expect(githubActionCredential(dexPrincipal)).toEqual({ token: 'gho_app', source: 'app' });
  });

  it('reports "none" — never a silent no-op — when nothing is configured', () => {
    expect(githubActionCredential(dexPrincipal)).toEqual({ token: null, source: 'none' });
  });
});

describe('"Start work" for a Dex user', () => {
  const item = {
    id: 42,
    title: 'Judge calibration refresh',
    itemType: 'Story',
    branchName: null,
    branchRepo: null,
    assigneeLogin: null,
  } as unknown as WorkItem;

  const actor = { login: 'clayton', source: 'user' as const };

  it('FAILS LOUDLY with an actionable message when no credential exists at all', async () => {
    const outcome = await startWork(item, actor, { token: null, source: 'none' });

    expect(outcome.status).toBe('failed');
    if (outcome.status !== 'failed') throw new Error('expected failure');
    // Never a silent no-op: it names what failed and what an owner must set.
    expect(outcome.message).toContain('Creating a branch');
    expect(outcome.message).toContain('GITHUB_POLL_TOKEN');
  });

  it('is disabled cleanly when AUTO_BRANCH is off', async () => {
    process.env.AUTO_BRANCH = 'false';
    try {
      const outcome = await startWork(item, actor, { token: 'gho_app', source: 'app' });
      expect(outcome.status).toBe('disabled');
    } finally {
      delete process.env.AUTO_BRANCH;
    }
  });

  it('refuses a repo the board is not configured for', async () => {
    const outcome = await startWork(item, actor, { token: 'gho_app', source: 'app' }, 'someone/else');
    expect(outcome.status).toBe('failed');
    if (outcome.status !== 'failed') throw new Error('expected failure');
    expect(outcome.message).toContain('not configured');
  });
});

describe('PR backlink for a Dex user', () => {
  const item = { id: 7, title: 'Linked item', state: 'Active' } as unknown as WorkItem;

  it('explains itself instead of silently skipping when no credential exists', async () => {
    const { syncBacklinkComment } = await import('@/lib/sync/backlink');
    const result = await syncBacklinkComment(item, 'UA-MIS/ida-llm', 5, {
      token: null,
      source: 'none',
    });

    expect(result.ok).toBe(false);
    expect(result.reason).toContain('GITHUB_POLL_TOKEN');
  });

  it('reports the disabled flag distinctly from a missing credential', async () => {
    process.env.PR_BACKLINK_COMMENTS = 'false';
    try {
      const { syncBacklinkComment } = await import('@/lib/sync/backlink');
      const result = await syncBacklinkComment(item, 'UA-MIS/ida-llm', 5, {
        token: 'gho_app',
        source: 'app',
      });
      expect(result.ok).toBe(false);
      expect(result.reason).toContain('disabled');
    } finally {
      delete process.env.PR_BACKLINK_COMMENTS;
    }
  });
});
