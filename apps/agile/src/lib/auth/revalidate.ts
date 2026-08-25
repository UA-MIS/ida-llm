import { checkTeamMembership } from './team';
import type { Fetcher } from './github-oauth';

/**
 * Re-checks team membership for an already-authenticated session.
 *
 * Without this, a user removed from the `ida-llm` team would keep access until
 * their cookie expired. Membership is re-read from GitHub at most once per
 * REVALIDATE_TTL_MS per user, so the common path costs nothing.
 *
 * Failure policy differs from sign-in on purpose:
 *   - `not-a-member` / `invitation-pending` -> REVOKE. The user provably lost access.
 *   - `lookup-failed` (GitHub 5xx, network) -> KEEP. This session already proved
 *     membership at sign-in; a GitHub outage must not sign out the whole team.
 * Sign-in itself still fails closed — see checkTeamMembership.
 */
export const REVALIDATE_TTL_MS = 10 * 60 * 1000;

interface CacheEntry {
  allowed: boolean;
  checkedAt: number;
}

const cache = new Map<string, CacheEntry>();

export function clearRevalidationCache(): void {
  cache.clear();
}

export async function isStillOnTeam(
  login: string,
  token: string,
  opts: { now?: number; fetchImpl?: Fetcher } = {},
): Promise<boolean> {
  const now = opts.now ?? Date.now();
  const hit = cache.get(login);
  if (hit && now - hit.checkedAt < REVALIDATE_TTL_MS) {
    return hit.allowed;
  }

  const decision = await checkTeamMembership(login, token, opts.fetchImpl ?? fetch);

  if (!decision.allowed && decision.reason === 'lookup-failed') {
    // Transient: keep the session, and do not cache the inconclusive result.
    return true;
  }

  cache.set(login, { allowed: decision.allowed, checkedAt: now });
  return decision.allowed;
}
