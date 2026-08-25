import { config } from '@/lib/env';
import { ghHeaders, TEAM_MEMBERSHIP_URL, type Fetcher } from './github-oauth';

/**
 * Authorization boundary for the whole application.
 *
 * Tenant apps on this platform are PUBLIC — there is no platform login in
 * front of them. This check is therefore the only thing standing between the
 * open internet and the team's board, so it fails CLOSED: any outcome that is
 * not an explicit, active membership is a denial.
 */

export type DenialReason = 'not-a-member' | 'invitation-pending' | 'lookup-failed';

export type MembershipDecision =
  | { allowed: true; role: 'member' | 'maintainer' }
  | { allowed: false; reason: DenialReason };

/**
 * GitHub returns 200 with {state, role} for members, 404 for non-members.
 * A *pending* membership means the user was invited but has not accepted —
 * they are not yet on the team, so they are denied.
 */
export async function checkTeamMembership(
  login: string,
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<MembershipDecision> {
  let res: Response;
  try {
    res = await fetchImpl(TEAM_MEMBERSHIP_URL(login), { headers: ghHeaders(token) });
  } catch {
    // Network/DNS failure: fail closed rather than letting anyone through.
    return { allowed: false, reason: 'lookup-failed' };
  }

  if (res.status === 404) return { allowed: false, reason: 'not-a-member' };

  if (!res.ok) return { allowed: false, reason: 'lookup-failed' };

  let body: { state?: unknown; role?: unknown };
  try {
    body = (await res.json()) as { state?: unknown; role?: unknown };
  } catch {
    return { allowed: false, reason: 'lookup-failed' };
  }

  if (body.state === 'pending') return { allowed: false, reason: 'invitation-pending' };
  if (body.state !== 'active') return { allowed: false, reason: 'not-a-member' };

  const role = body.role === 'maintainer' ? 'maintainer' : 'member';
  return { allowed: true, role };
}



export function teamLabel(): string {
  return config.teamLabel;
}

export function denialMessage(reason: DenialReason): string {
  const TEAM_LABEL = config.teamLabel;
  switch (reason) {
    case 'invitation-pending':
      return `You have a pending invitation to ${TEAM_LABEL}. Accept it on GitHub, then sign in again.`;
    case 'lookup-failed':
      return `We could not verify your ${TEAM_LABEL} membership with GitHub. Please try again in a moment.`;
    default:
      return `You are not a member of the ${TEAM_LABEL} team.`;
  }
}
