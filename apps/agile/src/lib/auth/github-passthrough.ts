import { config } from '@/lib/env';
import { sha256Hex } from '@/lib/crypto';
import { fetchAuthenticatedUser, type Fetcher } from './github-oauth';
import { checkTeamMembership } from './team';

/**
 * Accepts a raw GitHub token as an API credential.
 *
 * This exists so the common case is a one-liner from any machine with `gh`:
 *
 *   curl -H "Authorization: Bearer $(gh auth token)" ...
 *
 * Rules, deliberately strict:
 *  - The token is **never persisted** — not to the database, not to disk.
 *  - Only the *derived identity* is cached, keyed by a SHA-256 of the token, for
 *    a short TTL. The cache key is a hash so the raw token never sits in memory
 *    as a map key either.
 *  - Authorization is the same org/team check the web path uses.
 *  - It is distinguishable in history from a board-issued token, because a
 *    GitHub token is a broader credential.
 */
export const PASSTHROUGH_TTL_MS = 5 * 60 * 1000;

interface CacheEntry {
  login: string;
  allowed: boolean;
  expiresAt: number;
}

const cache = new Map<string, CacheEntry>();

export function clearPassthroughCache(): void {
  cache.clear();
}

export type PassthroughVerdict =
  | { ok: true; login: string }
  | { ok: false; reason: 'invalid-token' | 'not-on-team' | 'lookup-failed'; message: string };

/** A GitHub token, as opposed to a board-issued `iag_` token. */
export function looksLikeGitHubToken(token: string): boolean {
  return /^(gh[pousr]_|github_pat_)/.test(token);
}

export async function authenticateGitHubToken(
  token: string,
  fetchImpl: Fetcher = fetch,
  now: number = Date.now(),
): Promise<PassthroughVerdict> {
  const key = sha256Hex(token);
  const hit = cache.get(key);
  if (hit && hit.expiresAt > now) {
    return hit.allowed
      ? { ok: true, login: hit.login }
      : {
          ok: false,
          reason: 'not-on-team',
          message: `${hit.login} is not a member of ${config.teamLabel}.`,
        };
  }

  let login: string;
  try {
    const user = await fetchAuthenticatedUser(token, fetchImpl);
    login = user.login;
  } catch {
    return {
      ok: false,
      reason: 'invalid-token',
      message:
        'That GitHub token was rejected by GitHub. It may be expired, or missing the read:org scope.',
    };
  }

  const decision = await checkTeamMembership(login, token, fetchImpl);

  if (!decision.allowed) {
    if (decision.reason === 'lookup-failed') {
      // Do not cache an inconclusive result.
      return {
        ok: false,
        reason: 'lookup-failed',
        message:
          `Could not verify ${login}'s membership of ${config.teamLabel}. ` +
          'A GitHub token needs the read:org scope for this check.',
      };
    }
    cache.set(key, { login, allowed: false, expiresAt: now + PASSTHROUGH_TTL_MS });
    return {
      ok: false,
      reason: 'not-on-team',
      message: `${login} is not a member of ${config.teamLabel}.`,
    };
  }

  cache.set(key, { login, allowed: true, expiresAt: now + PASSTHROUGH_TTL_MS });
  return { ok: true, login };
}
