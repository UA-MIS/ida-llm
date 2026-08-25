import { describe, it, expect } from 'vitest';
import { checkTeamMembership } from '@/lib/auth/team';
import type { Fetcher } from '@/lib/auth/github-oauth';

/**
 * MANDATORY BOUNDARY TEST.
 *
 * This app is deployed on a PUBLIC URL with no platform login in front of it.
 * `checkTeamMembership` is the only gate. These tests pin the behaviour that
 * every non-member outcome is a denial (fail closed).
 */

function stubFetch(handler: (url: string) => Response | Promise<Response>): Fetcher {
  return ((input: RequestInfo | URL) =>
    Promise.resolve(handler(String(input)))) as unknown as Fetcher;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('checkTeamMembership — the authorization boundary', () => {
  it('REJECTS a user who is not a member of the team (GitHub 404)', async () => {
    const decision = await checkTeamMembership(
      'random-internet-person',
      'tok',
      stubFetch(() => json(404, { message: 'Not Found' })),
    );

    expect(decision.allowed).toBe(false);
    expect(decision).toEqual({ allowed: false, reason: 'not-a-member' });
  });

  it('ADMITS an active member', async () => {
    const decision = await checkTeamMembership(
      'real-teammate',
      'tok',
      stubFetch(() => json(200, { state: 'active', role: 'member' })),
    );

    expect(decision).toEqual({ allowed: true, role: 'member' });
  });

  it('ADMITS an active maintainer and preserves the role', async () => {
    const decision = await checkTeamMembership(
      'lead',
      'tok',
      stubFetch(() => json(200, { state: 'active', role: 'maintainer' })),
    );

    expect(decision).toEqual({ allowed: true, role: 'maintainer' });
  });

  it('REJECTS a pending invitee who has not accepted yet', async () => {
    const decision = await checkTeamMembership(
      'invited-but-not-accepted',
      'tok',
      stubFetch(() => json(200, { state: 'pending', role: 'member' })),
    );

    expect(decision).toEqual({ allowed: false, reason: 'invitation-pending' });
  });

  it('FAILS CLOSED when GitHub returns an unexpected status', async () => {
    for (const status of [401, 403, 500, 502]) {
      const decision = await checkTeamMembership(
        'someone',
        'tok',
        stubFetch(() => json(status, { message: 'nope' })),
      );
      expect(decision, `status ${status} must deny`).toEqual({
        allowed: false,
        reason: 'lookup-failed',
      });
    }
  });

  it('FAILS CLOSED when the GitHub call throws (network/DNS failure)', async () => {
    const decision = await checkTeamMembership(
      'someone',
      'tok',
      (() => Promise.reject(new Error('ECONNREFUSED'))) as unknown as Fetcher,
    );

    expect(decision).toEqual({ allowed: false, reason: 'lookup-failed' });
  });

  it('FAILS CLOSED when GitHub returns 200 with an unparseable body', async () => {
    const decision = await checkTeamMembership(
      'someone',
      'tok',
      stubFetch(() => new Response('<html>gateway</html>', { status: 200 })),
    );

    expect(decision).toEqual({ allowed: false, reason: 'lookup-failed' });
  });

  it('REJECTS a 200 response whose state is neither active nor pending', async () => {
    const decision = await checkTeamMembership(
      'someone',
      'tok',
      stubFetch(() => json(200, { state: 'inactive', role: 'member' })),
    );

    expect(decision).toEqual({ allowed: false, reason: 'not-a-member' });
  });

  it('queries the membership endpoint for the correct org/team and escapes the login', async () => {
    let seen = '';
    await checkTeamMembership(
      'weird/login name',
      'tok',
      stubFetch((url) => {
        seen = url;
        return json(404, {});
      }),
    );

    expect(seen).toContain('/orgs/UA-MIS/teams/ida-llm/memberships/');
    expect(seen).toContain(encodeURIComponent('weird/login name'));
    expect(seen).not.toContain('weird/login name');
  });
});
