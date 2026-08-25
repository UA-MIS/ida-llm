import { checkTeamMembership } from './team';
import { authProvider } from './providers';
import type { Fetcher } from './github-oauth';
import type { SessionPayload } from './session';

/**
 * Re-checks that an existing session still qualifies.
 *
 * The two providers can offer different guarantees, and the difference is
 * deliberate rather than hidden:
 *
 *  - **github**: membership is re-read from GitHub at most once per
 *    REVALIDATE_TTL_MS, so removing someone from the team revokes access within
 *    ~10 minutes.
 *  - **oidc**: the groups claim is asserted once at sign-in and there is no way
 *    to re-read it without another authorization round trip. The claim carried
 *    in the session is re-checked against REQUIRED_GROUP (so changing the
 *    required group takes effect immediately), but a user removed from the team
 *    upstream keeps access until their session expires. Session TTL is the
 *    freshness bound there — documented in the README.
 *
 * Failure policy for the github path: a provable denial revokes; an
 * inconclusive lookup (5xx, network) keeps the session, because a GitHub
 * outage must not sign out the whole team.
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

/** GitHub-backed membership re-check, with a short cache. */
export async function isStillOnTeam(
  login: string,
  token: string,
  opts: { now?: number; fetchImpl?: Fetcher } = {},
): Promise<boolean> {
  // No usable credential: nothing to check with, so do not revoke.
  if (!token) return true;

  const now = opts.now ?? Date.now();
  const hit = cache.get(login);
  if (hit && now - hit.checkedAt < REVALIDATE_TTL_MS) return hit.allowed;

  const decision = await checkTeamMembership(login, token, opts.fetchImpl ?? fetch);

  if (!decision.allowed && decision.reason === 'lookup-failed') {
    // Transient: keep the session, and do not cache the inconclusive result.
    return true;
  }

  cache.set(login, { allowed: decision.allowed, checkedAt: now });
  return decision.allowed;
}

/**
 * Provider-aware entry point used by every route guard.
 *
 * Delegates to the provider that issued the session rather than reimplementing
 * the rule here, so there is exactly one place per provider that decides
 * whether a session still qualifies. `unknown` keeps the session — it means
 * "could not tell", which must never revoke access on its own.
 */
export async function sessionStillValid(
  session: Pick<SessionPayload, 'login' | 'token' | 'groups' | 'provider'>,
  _opts: { now?: number; fetchImpl?: Fetcher } = {},
): Promise<boolean> {
  const provider = authProvider(session.provider);
  const verdict = await provider.revalidate({
    login: session.login,
    groups: session.groups,
    githubToken: session.token || null,
  });
  return verdict !== 'denied';
}
