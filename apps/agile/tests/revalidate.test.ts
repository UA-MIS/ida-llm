import { describe, it, expect, beforeEach } from 'vitest';
import { isStillOnTeam, clearRevalidationCache, REVALIDATE_TTL_MS } from '@/lib/auth/revalidate';
import type { Fetcher } from '@/lib/auth/github-oauth';

function stub(status: number, body: unknown, onCall?: () => void): Fetcher {
  return ((): Promise<Response> => {
    onCall?.();
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      }),
    );
  }) as unknown as Fetcher;
}

describe('session revalidation', () => {
  beforeEach(clearRevalidationCache);

  it('keeps a session while the user is still an active member', async () => {
    const ok = await isStillOnTeam('alice', 'tok', {
      fetchImpl: stub(200, { state: 'active', role: 'member' }),
    });
    expect(ok).toBe(true);
  });

  it('REVOKES a session once the user is removed from the team', async () => {
    const ok = await isStillOnTeam('exiled', 'tok', { fetchImpl: stub(404, {}) });
    expect(ok).toBe(false);
  });

  it('REVOKES when membership degrades to pending', async () => {
    const ok = await isStillOnTeam('pending-user', 'tok', {
      fetchImpl: stub(200, { state: 'pending' }),
    });
    expect(ok).toBe(false);
  });

  it('KEEPS the session when GitHub is unreachable, and does not cache that', async () => {
    let calls = 0;
    const flaky = stub(500, { message: 'boom' }, () => calls++);

    expect(await isStillOnTeam('alice', 'tok', { fetchImpl: flaky })).toBe(true);
    expect(await isStillOnTeam('alice', 'tok', { fetchImpl: flaky })).toBe(true);
    // An inconclusive result must not be cached, so GitHub is retried.
    expect(calls).toBe(2);
  });

  it('caches a positive result for the TTL, then re-checks', async () => {
    let calls = 0;
    const member = stub(200, { state: 'active', role: 'member' }, () => calls++);
    const t0 = 1_000_000;

    await isStillOnTeam('alice', 'tok', { now: t0, fetchImpl: member });
    await isStillOnTeam('alice', 'tok', { now: t0 + 1000, fetchImpl: member });
    expect(calls).toBe(1);

    await isStillOnTeam('alice', 'tok', { now: t0 + REVALIDATE_TTL_MS + 1, fetchImpl: member });
    expect(calls).toBe(2);
  });

  it('picks up a revocation on the next check after the TTL expires', async () => {
    const t0 = 1_000_000;
    await isStillOnTeam('bob', 'tok', {
      now: t0,
      fetchImpl: stub(200, { state: 'active', role: 'member' }),
    });
    expect(await isStillOnTeam('bob', 'tok', { now: t0 + 1000, fetchImpl: stub(404, {}) })).toBe(true);

    const after = await isStillOnTeam('bob', 'tok', {
      now: t0 + REVALIDATE_TTL_MS + 1,
      fetchImpl: stub(404, {}),
    });
    expect(after).toBe(false);
  });

  it('tracks users independently', async () => {
    const t0 = 1_000_000;
    await isStillOnTeam('alice', 'tok', { now: t0, fetchImpl: stub(200, { state: 'active' }) });
    const mallory = await isStillOnTeam('mallory', 'tok', { now: t0, fetchImpl: stub(404, {}) });
    expect(mallory).toBe(false);
    expect(await isStillOnTeam('alice', 'tok', { now: t0, fetchImpl: stub(404, {}) })).toBe(true);
  });
});
