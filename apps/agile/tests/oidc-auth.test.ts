import { describe, it, expect, beforeEach } from 'vitest';
import {
  createPkcePair,
  extractGroups,
  hasRequiredGroup,
  resetDiscoveryCache,
} from '@/lib/auth/providers/oidc';
import {
  authenticateGitHubToken,
  clearPassthroughCache,
  looksLikeGitHubToken,
  PASSTHROUGH_TTL_MS,
} from '@/lib/auth/github-passthrough';
import type { Fetcher } from '@/lib/auth/github-oauth';

beforeEach(() => {
  resetDiscoveryCache();
  clearPassthroughCache();
  process.env.GITHUB_ORG = 'UA-MIS';
  process.env.GITHUB_TEAM = 'ida-llm';
  process.env.SESSION_SECRET = 'x'.repeat(48);
  process.env.APP_URL = 'https://ida-agile.capstone.uamishub.com';
  delete process.env.REQUIRED_GROUP;
});

describe('PKCE', () => {
  it('produces a high-entropy verifier and an S256 challenge', () => {
    const { verifier, challenge } = createPkcePair();
    expect(verifier.length).toBeGreaterThanOrEqual(43);
    expect(challenge).not.toBe(verifier);
    // base64url alphabet only — no padding, no +/ characters.
    expect(verifier).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(challenge).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it('is different on every call', () => {
    expect(createPkcePair().verifier).not.toBe(createPkcePair().verifier);
  });
});

describe('groups claim — verified against the live Dex shape', () => {
  it('reads a string array', () => {
    expect(extractGroups({ groups: ['UA-MIS:ida-llm', 'UA-MIS:labmx'] })).toEqual([
      'UA-MIS:ida-llm',
      'UA-MIS:labmx',
    ]);
  });

  it('tolerates a missing or malformed claim rather than throwing', () => {
    expect(extractGroups({})).toEqual([]);
    expect(extractGroups({ groups: 'nope' as unknown as string[] })).toEqual([]);
    expect(extractGroups({ groups: [1, 'ok'] as unknown as string[] })).toEqual(['ok']);
  });

  it('ADMITS a member of the required org:team group', () => {
    expect(hasRequiredGroup(['UA-MIS:ida-llm'], 'UA-MIS:ida-llm')).toBe(true);
  });

  it('REJECTS a member of a different team in the same org', () => {
    expect(hasRequiredGroup(['UA-MIS:labmx', 'UA-MIS:sample'], 'UA-MIS:ida-llm')).toBe(false);
  });

  it('REJECTS an empty groups claim', () => {
    expect(hasRequiredGroup([], 'UA-MIS:ida-llm')).toBe(false);
  });

  it('REJECTS a bare org group — Dex never emits one, so it must not grant access', () => {
    expect(hasRequiredGroup(['UA-MIS'], 'UA-MIS:ida-llm')).toBe(false);
  });

  it('REJECTS a prefix or suffix near-match', () => {
    expect(hasRequiredGroup(['UA-MIS:ida-llm-admins'], 'UA-MIS:ida-llm')).toBe(false);
    expect(hasRequiredGroup(['OTHER:ida-llm'], 'UA-MIS:ida-llm')).toBe(false);
  });

  it('is case-insensitive, since org casing varies by how it is configured', () => {
    expect(hasRequiredGroup(['ua-mis:IDA-LLM'], 'UA-MIS:ida-llm')).toBe(true);
  });

  it('tolerates incidental whitespace', () => {
    expect(hasRequiredGroup([' UA-MIS:ida-llm '], 'UA-MIS:ida-llm')).toBe(true);
  });
});

// ---------------------------------------------------------------------------

function ghStub(handler: (url: string) => Response): Fetcher {
  return ((input: RequestInfo | URL) => Promise.resolve(handler(String(input)))) as unknown as Fetcher;
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('GitHub token passthrough', () => {
  it.each(['ghp_abc', 'gho_abc', 'ghu_abc', 'ghs_abc', 'ghr_abc', 'github_pat_abc'])(
    'recognises %s as a GitHub token',
    (t) => expect(looksLikeGitHubToken(t)).toBe(true),
  );

  it('does NOT mistake a board token for a GitHub token', () => {
    expect(looksLikeGitHubToken('iag_abcdef')).toBe(false);
    expect(looksLikeGitHubToken('random')).toBe(false);
  });

  it('ADMITS an active team member', async () => {
    const verdict = await authenticateGitHubToken(
      'ghp_valid',
      ghStub((url) =>
        url.endsWith('/user')
          ? json(200, { login: 'octocat' })
          : json(200, { state: 'active', role: 'member' }),
      ),
    );
    expect(verdict).toEqual({ ok: true, login: 'octocat' });
  });

  it('REJECTS a token GitHub does not recognise', async () => {
    const verdict = await authenticateGitHubToken('ghp_bad', ghStub(() => json(401, {})));
    expect(verdict.ok).toBe(false);
    if (!verdict.ok) expect(verdict.reason).toBe('invalid-token');
  });

  it('REJECTS a valid token belonging to a non-member', async () => {
    const verdict = await authenticateGitHubToken(
      'ghp_outsider',
      ghStub((url) => (url.endsWith('/user') ? json(200, { login: 'mallory' }) : json(404, {}))),
    );
    expect(verdict.ok).toBe(false);
    if (!verdict.ok) {
      expect(verdict.reason).toBe('not-on-team');
      expect(verdict.message).toContain('mallory');
    }
  });

  it('explains the read:org requirement when the membership check cannot be made', async () => {
    const verdict = await authenticateGitHubToken(
      'ghp_noscope',
      ghStub((url) => (url.endsWith('/user') ? json(200, { login: 'alice' }) : json(403, {}))),
    );
    expect(verdict.ok).toBe(false);
    if (!verdict.ok) {
      expect(verdict.reason).toBe('lookup-failed');
      expect(verdict.message).toContain('read:org');
    }
  });

  it('caches a positive verdict so a burst of API calls is one GitHub round trip', async () => {
    let calls = 0;
    const stub = ghStub((url) => {
      calls++;
      return url.endsWith('/user') ? json(200, { login: 'octocat' }) : json(200, { state: 'active' });
    });

    await authenticateGitHubToken('ghp_cached', stub);
    const before = calls;
    await authenticateGitHubToken('ghp_cached', stub);
    expect(calls).toBe(before);
  });

  it('re-checks after the cache TTL expires', async () => {
    let calls = 0;
    const stub = ghStub((url) => {
      calls++;
      return url.endsWith('/user') ? json(200, { login: 'octocat' }) : json(200, { state: 'active' });
    });

    await authenticateGitHubToken('ghp_ttl', stub, Date.now());
    const before = calls;
    await authenticateGitHubToken('ghp_ttl', stub, Date.now() + PASSTHROUGH_TTL_MS + 1);
    expect(calls).toBeGreaterThan(before);
  });

  it('does NOT cache an inconclusive lookup', async () => {
    let calls = 0;
    const stub = ghStub((url) => {
      calls++;
      return url.endsWith('/user') ? json(200, { login: 'alice' }) : json(500, {});
    });

    await authenticateGitHubToken('ghp_flaky', stub);
    const before = calls;
    await authenticateGitHubToken('ghp_flaky', stub);
    expect(calls).toBeGreaterThan(before);
  });

  it('keys the cache per token, so one user\'s verdict cannot admit another', async () => {
    const stub = ghStub((url) =>
      url.endsWith('/user') ? json(200, { login: 'octocat' }) : json(200, { state: 'active' }),
    );
    await authenticateGitHubToken('ghp_a', stub);

    const other = await authenticateGitHubToken(
      'ghp_b',
      ghStub((url) => (url.endsWith('/user') ? json(200, { login: 'mallory' }) : json(404, {}))),
    );
    expect(other.ok).toBe(false);
  });
});

// ---------------------------------------------------------------------------

describe('GitHub credential selection', () => {
  beforeEach(() => {
    delete process.env.GITHUB_POLL_TOKEN;
    delete process.env.AUTH_PROVIDER;
  });

  it('prefers the acting user’s own token for reads', async () => {
    const { githubReadToken } = await import('@/lib/github/credential');
    process.env.GITHUB_POLL_TOKEN = 'gho_shared';
    expect(githubReadToken({ githubToken: 'gho_mine' })).toBe('gho_mine');
  });

  it('falls back to the shared token for READS when the session has none (OIDC)', async () => {
    const { githubReadToken } = await import('@/lib/github/credential');
    process.env.GITHUB_POLL_TOKEN = 'gho_shared';
    expect(githubReadToken({ githubToken: null })).toBe('gho_shared');
  });

  it('returns null for reads when nothing is configured', async () => {
    const { githubReadToken } = await import('@/lib/github/credential');
    expect(githubReadToken({ githubToken: null })).toBeNull();
    expect(githubReadToken(null)).toBeNull();
  });

  it('NEVER falls back to the shared token for writes — that would misattribute', async () => {
    const { githubWriteToken } = await import('@/lib/github/credential');
    process.env.GITHUB_POLL_TOKEN = 'gho_shared';
    expect(githubWriteToken({ githubToken: null })).toBeNull();
    expect(githubWriteToken({ githubToken: 'gho_mine' })).toBe('gho_mine');
  });

  it('explains the missing credential differently per provider', async () => {
    const { writeCredentialHint } = await import('@/lib/github/credential');
    process.env.AUTH_PROVIDER = 'oidc';
    process.env.OIDC_ISSUER = 'https://id.example.test';
    expect(writeCredentialHint()).toContain('Dex');

    process.env.AUTH_PROVIDER = 'github';
    expect(writeCredentialHint()).toContain('signed-in session');
  });
});

describe('GitHub client with no credential', () => {
  it('returns empty rather than calling GitHub unauthenticated', async () => {
    const { listTeamMembers, listOpenPullRequests, clearGitHubCaches } = await import(
      '@/lib/github/client'
    );
    clearGitHubCaches();
    let called = 0;
    const spy = (() => {
      called++;
      return Promise.resolve(new Response('[]', { status: 200 }));
    }) as unknown as Fetcher;

    expect(await listTeamMembers('', spy)).toEqual([]);
    expect(await listOpenPullRequests('', spy)).toEqual([]);
    expect(called).toBe(0);
  });
});
