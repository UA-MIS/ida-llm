import { createPrivateKey, type KeyObject } from 'node:crypto';
import { SignJWT } from 'jose';
import { config } from '@/lib/env';
import type { Fetcher } from '@/lib/auth/github-oauth';

/**
 * The board's own GitHub credential.
 *
 * Under Dex OIDC a session carries identity and groups but NO GitHub token, so
 * every GitHub-touching feature — the assignee picker, branch creation, PR
 * backlink comments — has nothing to call the API with. This module gives the
 * board an identity of its own: the platform's GitHub App, already installed
 * across the org, whose installation token can read the team roster, create
 * branches and comment on pull requests.
 *
 * ── Why minting rather than a stored token ──────────────────────────────────
 * An installation access token lives about ONE HOUR. Storing one in a Secret
 * would mean a board that works for an hour after each deploy and then silently
 * stops — the same class of silent failure this replaces. So the durable secret
 * is the App's private key, and the token is minted on demand, held in memory,
 * and renewed a little before it expires.
 *
 * ── Invariants ──────────────────────────────────────────────────────────────
 *  - **Never throws.** Every failure resolves to `null`. A GitHub outage must
 *    degrade the assignee picker, not 500 a page render.
 *  - **Never logs credential material.** Not the key, not the JWT, not the
 *    token. Failure logs carry a status code and nothing else.
 *  - **Single-flight.** Concurrent callers share one mint, so a burst of
 *    requests does not become a burst of token creations.
 *  - **Nothing durable in memory.** Losing the cache on pod restart costs one
 *    extra API call.
 */

/** GitHub rejects an App JWT with more than 10 minutes of life. */
const APP_JWT_TTL_SECONDS = 540;

/**
 * The App JWT's `iat` is backdated. GitHub rejects a future-dated token, and a
 * container clock a few seconds ahead of GitHub's is ordinary — it produces a
 * 401 that reads exactly like a bad private key, which is a miserable thing to
 * debug. One minute of backdating costs nothing and removes the failure mode.
 */
const CLOCK_SKEW_SECONDS = 60;

/**
 * Renew this long before the token actually expires, so a request that starts
 * with a valid token cannot finish with an expired one.
 */
const RENEW_MARGIN_MS = 5 * 60 * 1000;

/** Used when GitHub's response omits `expires_at`; deliberately pessimistic. */
const ASSUMED_TTL_MS = 10 * 60 * 1000;

interface CachedToken {
  token: string;
  expiresAt: number;
}

let cached: CachedToken | null = null;
let inFlight: Promise<string | null> | null = null;

/** Test seam: a fetch implementation used when no explicit one is passed. */
let fetchOverride: Fetcher | null = null;

/** Drops the cached token. For tests, and for a future explicit-rotation path. */
export function resetInstallationTokenCache(): void {
  cached = null;
  inFlight = null;
}

/**
 * Installs a fetch double for callers that cannot pass one down (the credential
 * seam resolves the App token internally). Pass `null` to restore real fetch.
 */
export function setInstallationTokenFetch(impl: Fetcher | null): void {
  fetchOverride = impl;
}

/** Cache visibility for tests and diagnostics. Never exposes the token itself. */
export function installationTokenState(): { cached: boolean; expiresAt: number } {
  return { cached: cached !== null, expiresAt: cached?.expiresAt ?? 0 };
}

function loadKey(): KeyObject | null {
  const pem = config.githubAppPrivateKey;
  if (!pem) return null;
  try {
    return createPrivateKey(pem);
  } catch {
    // Deliberately swallows the underlying error: OpenSSL error strings can
    // echo key material back, and this is enough to know the key is unusable.
    return null;
  }
}

/**
 * The short-lived JWT that authenticates as the APP itself (not as an
 * installation). Its only use is exchanging for an installation token.
 */
async function mintAppJwt(key: KeyObject): Promise<string> {
  const now = Math.floor(Date.now() / 1000) - CLOCK_SKEW_SECONDS;
  return new SignJWT({})
    .setProtectedHeader({ alg: 'RS256', typ: 'JWT' })
    .setIssuedAt(now)
    .setExpirationTime(now + APP_JWT_TTL_SECONDS)
    .setIssuer(config.githubAppId)
    .sign(key);
}

async function mintInstallationToken(fetchImpl: Fetcher): Promise<CachedToken | null> {
  const key = loadKey();
  if (!key) {
    console.warn('[github-app] private key is not usable; App credential disabled');
    return null;
  }

  let jwt: string;
  try {
    jwt = await mintAppJwt(key);
  } catch {
    console.warn('[github-app] could not sign the App JWT; App credential disabled');
    return null;
  }

  try {
    const res = await fetchImpl(
      `https://api.github.com/app/installations/${encodeURIComponent(
        config.githubAppInstallationId,
      )}/access_tokens`,
      {
        method: 'POST',
        headers: {
          authorization: `Bearer ${jwt}`,
          accept: 'application/vnd.github+json',
          'x-github-api-version': '2022-11-28',
          'user-agent': 'ida-agile',
        },
      },
    );

    if (!res.ok) {
      // Status only. The response body can echo the request back.
      console.warn(
        `[github-app] GitHub refused the installation token request (HTTP ${res.status}); ` +
          'check GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID and the private key',
      );
      return null;
    }

    const body = (await res.json()) as { token?: string; expires_at?: string };
    if (!body.token) {
      console.warn('[github-app] installation token response contained no token');
      return null;
    }

    const parsed = body.expires_at ? Date.parse(body.expires_at) : NaN;
    return {
      token: body.token,
      expiresAt: Number.isFinite(parsed) ? parsed : Date.now() + ASSUMED_TTL_MS,
    };
  } catch {
    // Network error, or a non-JSON body from a proxy. The thrown error can
    // carry the request (and therefore the JWT), so it is never logged.
    console.warn('[github-app] could not reach GitHub to mint an installation token');
    return null;
  }
}

/** Comfortably valid: not inside the renewal margin. */
function usable(entry: CachedToken | null): boolean {
  return entry !== null && entry.expiresAt - RENEW_MARGIN_MS > Date.now();
}

/**
 * An installation access token for the configured App, or null.
 *
 * Returns the cached token while it is comfortably valid, renews it inside the
 * margin, and — if the renewal fails but the old token has not actually expired
 * yet — keeps serving the old one rather than degrading a working board.
 */
export async function getInstallationToken(fetchImpl?: Fetcher): Promise<string | null> {
  if (!config.githubAppConfigured) return null;

  const previous = cached;
  if (previous && usable(previous)) return previous.token;

  const impl = fetchImpl ?? fetchOverride ?? fetch;

  // Single-flight: a page render that resolves the credential four times must
  // create one token, not four.
  if (!inFlight) {
    inFlight = mintInstallationToken(impl)
      .then((fresh) => {
        if (fresh) {
          cached = fresh;
          return fresh.token;
        }
        // Renewal failed. A token that is inside the renewal margin but not yet
        // expired is still perfectly good — keep using it.
        if (previous && previous.expiresAt > Date.now()) return previous.token;
        cached = null;
        return null;
      })
      .finally(() => {
        inFlight = null;
      });
  }

  return inFlight;
}
