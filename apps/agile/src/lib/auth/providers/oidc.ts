import { createHash, randomBytes } from 'node:crypto';
import { createRemoteJWKSet, jwtVerify, type JWTPayload } from 'jose';
import { config } from '@/lib/env';
import { encryptString, decryptString } from '@/lib/crypto';
import { safeReturnTo } from '../session';
import type {
  AuthCallbackResult,
  AuthProvider,
  AuthStartResult,
} from './types';

/**
 * Dex OIDC provider (authorization code + PKCE).
 *
 * Verified against the live Dex at id.capstone.uamishub.com:
 *  - `teamNameField: slug` and `orgs: [UA-MIS]`, so the groups claim is
 *    `UA-MIS:<team-slug>` — e.g. `UA-MIS:ida-llm`. The bare org is never
 *    emitted as a group.
 *  - `useLoginAsID: true`, so `preferred_username` is the GitHub login.
 *  - Confidential client (`client_secret_basic`/`_post`); `none` is not
 *    advertised, so a client secret is required even with PKCE.
 *  - `code_challenge_methods_supported: ["S256","plain"]` — S256 is used here.
 */
const STATE_INFO = 'ida-agile-oidc-state-v1';
const STATE_TTL_SECONDS = 600;

interface Discovery {
  authorization_endpoint: string;
  token_endpoint: string;
  jwks_uri: string;
  userinfo_endpoint?: string;
  issuer: string;
}

let discoveryCache: { value: Discovery; expiresAt: number } | null = null;
let jwks: ReturnType<typeof createRemoteJWKSet> | null = null;

export async function discover(fetchImpl: typeof fetch = fetch): Promise<Discovery> {
  if (discoveryCache && discoveryCache.expiresAt > Date.now()) return discoveryCache.value;

  const url = `${config.oidcIssuer}/.well-known/openid-configuration`;
  const res = await fetchImpl(url);
  if (!res.ok) {
    throw new Error(`OIDC discovery failed at ${url} (HTTP ${res.status}).`);
  }
  const value = (await res.json()) as Discovery;
  if (!value.authorization_endpoint || !value.token_endpoint || !value.jwks_uri) {
    throw new Error('OIDC discovery document is missing required endpoints.');
  }
  discoveryCache = { value, expiresAt: Date.now() + 10 * 60 * 1000 };
  return value;
}

/** Exported for tests. */
export function resetDiscoveryCache(): void {
  discoveryCache = null;
  jwks = null;
}

interface StatePayload {
  state: string;
  verifier: string;
  returnTo: string;
  exp: number;
}

function base64url(buf: Buffer): string {
  return buf.toString('base64url');
}

export function createPkcePair(): { verifier: string; challenge: string } {
  const verifier = base64url(randomBytes(32));
  const challenge = base64url(createHash('sha256').update(verifier).digest());
  return { verifier, challenge };
}

/** Claim shape we care about. Everything else is ignored. */
export interface OidcClaims extends JWTPayload {
  preferred_username?: string;
  name?: string;
  email?: string;
  groups?: string[];
  picture?: string;
}

export function extractGroups(claims: OidcClaims): string[] {
  const raw = claims.groups;
  if (!Array.isArray(raw)) return [];
  return raw.filter((g): g is string => typeof g === 'string');
}

/**
 * Case-insensitive membership test.
 * Dex emits the team slug, but org casing varies by how it is typed in config,
 * so the comparison is normalised rather than exact.
 */
export function hasRequiredGroup(groups: string[], required: string): boolean {
  const want = required.trim().toLowerCase();
  return groups.some((g) => g.trim().toLowerCase() === want);
}

export class OidcProvider implements AuthProvider {
  readonly id = 'oidc' as const;
  readonly label = 'Sign in with GitHub';

  constructor(private readonly fetchImpl: typeof fetch = fetch) {}

  async start(returnTo: string): Promise<AuthStartResult> {
    const disco = await discover(this.fetchImpl);
    const { verifier, challenge } = createPkcePair();
    const state = base64url(randomBytes(24));

    const payload: StatePayload = {
      state,
      verifier,
      returnTo: safeReturnTo(returnTo),
      exp: Math.floor(Date.now() / 1000) + STATE_TTL_SECONDS,
    };

    const url = new URL(disco.authorization_endpoint);
    url.searchParams.set('response_type', 'code');
    url.searchParams.set('client_id', config.oidcClientId);
    url.searchParams.set('redirect_uri', config.oidcRedirectUri);
    url.searchParams.set('scope', config.oidcScopes);
    url.searchParams.set('state', state);
    url.searchParams.set('code_challenge', challenge);
    url.searchParams.set('code_challenge_method', 'S256');
    // Ask Dex to guarantee groups in the ID token rather than only /userinfo
    // (the pattern ArgoCD uses against this same Dex).
    url.searchParams.set(
      'claims',
      JSON.stringify({ id_token: { groups: { essential: true } } }),
    );

    return {
      redirectUrl: url.toString(),
      stateCookie: encryptString(JSON.stringify(payload), config.sessionSecret, STATE_INFO),
    };
  }

  async callback(
    params: URLSearchParams,
    stateCookie: string | undefined,
  ): Promise<AuthCallbackResult> {
    if (params.get('error')) {
      return {
        ok: false,
        reason: 'exchange-failed',
        message: `Sign-in was cancelled (${params.get('error')}).`,
      };
    }

    const code = params.get('code');
    const state = params.get('state');
    if (!code || !state || !stateCookie) {
      return { ok: false, reason: 'state-mismatch', message: 'Malformed sign-in response.' };
    }

    const decrypted = decryptString(stateCookie, config.sessionSecret, STATE_INFO);
    if (!decrypted) {
      return {
        ok: false,
        reason: 'state-mismatch',
        message: 'Sign-in state was invalid. Please try again.',
      };
    }

    let saved: StatePayload;
    try {
      saved = JSON.parse(decrypted) as StatePayload;
    } catch {
      return { ok: false, reason: 'state-mismatch', message: 'Sign-in state was unreadable.' };
    }

    if (saved.exp <= Math.floor(Date.now() / 1000)) {
      return { ok: false, reason: 'state-mismatch', message: 'Sign-in took too long. Try again.' };
    }
    if (saved.state !== state) {
      return {
        ok: false,
        reason: 'state-mismatch',
        message: 'Sign-in state did not match. Please try again.',
      };
    }

    const disco = await discover(this.fetchImpl);

    // Confidential client: Dex advertises client_secret_basic / _post only.
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: config.oidcRedirectUri,
      client_id: config.oidcClientId,
      code_verifier: saved.verifier,
    });
    if (config.oidcClientSecret) body.set('client_secret', config.oidcClientSecret);

    const tokenRes = await this.fetchImpl(disco.token_endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded', accept: 'application/json' },
      body: body.toString(),
    });

    if (!tokenRes.ok) {
      return {
        ok: false,
        reason: 'exchange-failed',
        message: `Could not complete sign-in (token endpoint returned HTTP ${tokenRes.status}).`,
      };
    }

    const tokens = (await tokenRes.json()) as { id_token?: string; access_token?: string };
    if (!tokens.id_token) {
      return { ok: false, reason: 'exchange-failed', message: 'No ID token was returned.' };
    }

    let claims: OidcClaims;
    try {
      jwks ??= createRemoteJWKSet(new URL(disco.jwks_uri));
      const verified = await jwtVerify(tokens.id_token, jwks, {
        issuer: disco.issuer || config.oidcIssuer,
        audience: config.oidcClientId,
      });
      claims = verified.payload as OidcClaims;
    } catch (err) {
      return {
        ok: false,
        reason: 'exchange-failed',
        message: `The ID token failed verification: ${(err as Error).message}`,
      };
    }

    const login = claims.preferred_username ?? (typeof claims.sub === 'string' ? claims.sub : '');
    if (!login) {
      return { ok: false, reason: 'exchange-failed', message: 'The ID token carried no username.' };
    }

    let groups = extractGroups(claims);

    // Fall back to /userinfo if the ID token carried no groups.
    if (groups.length === 0 && disco.userinfo_endpoint && tokens.access_token) {
      try {
        const ui = await this.fetchImpl(disco.userinfo_endpoint, {
          headers: { authorization: `Bearer ${tokens.access_token}` },
        });
        if (ui.ok) groups = extractGroups((await ui.json()) as OidcClaims);
      } catch {
        // Leave groups empty; the check below denies, which is the safe outcome.
      }
    }

    if (!hasRequiredGroup(groups, config.requiredGroup)) {
      return {
        ok: false,
        reason: 'not-a-member',
        login,
        message: `You are not a member of ${config.requiredGroup}.`,
      };
    }

    return {
      ok: true,
      returnTo: saved.returnTo,
      identity: {
        login,
        name: claims.name ?? login,
        avatarUrl: typeof claims.picture === 'string' ? claims.picture : '',
        groups,
        // The board never receives a GitHub credential on this path.
        githubToken: null,
      },
    };
  }

  /**
   * Group membership is asserted at sign-in and carried in the session. There
   * is no cheap way to re-read it without a new authorization round trip, so
   * this returns 'unknown' (never revokes) and freshness comes from the
   * session TTL instead. Documented in the README.
   */
  async revalidate(): Promise<'ok' | 'denied' | 'unknown'> {
    return 'unknown';
  }
}
