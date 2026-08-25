import { cookies } from 'next/headers';
import { config } from '@/lib/env';
import { SESSION_COOKIE, unsealSession } from './session';
import { sessionStillValid } from './revalidate';
import { verifyApiToken, TOKEN_PREFIX } from './tokens';
import { authenticateGitHubToken, looksLikeGitHubToken } from './github-passthrough';
import type { Actor, ActorSource } from '@/lib/domain/workitem';

/**
 * Who is making this request.
 *
 * Both authentication methods resolve to the same shape, so every route — UI or
 * API — runs the same authorization and the two can never drift:
 *   - `session`: a signed-in team member (encrypted cookie)
 *   - `api`:     a board-issued token acting AS the human who created it
 */
/** How the caller proved who they are. Recorded in history. */
export type CredentialKind = 'session' | 'board-token' | 'github-token';

export interface Principal {
  login: string;
  source: ActorSource;
  credential: CredentialKind;
  /** GitHub OAuth token, present only for cookie sessions. */
  githubToken: string | null;
  avatarUrl: string;
  name: string;
  tokenId?: number;
}

export function principalToActor(p: Principal, note?: string): Actor {
  // A GitHub token is a broader credential than a board token, so the two are
  // distinguishable in item history rather than both reading as "via API".
  const via =
    p.credential === 'github-token'
      ? 'via API (github token)'
      : p.credential === 'board-token'
        ? 'via API'
        : undefined;
  const combined = [via, note].filter(Boolean).join(' — ');
  return { login: p.login, source: p.source, note: combined || undefined };
}

export type AuthFailure =
  | { reason: 'anonymous'; status: 401; message: string }
  | { reason: 'not-on-team'; status: 403; message: string }
  | { reason: 'bad-token'; status: 401; message: string };

export type AuthResult = { ok: true; principal: Principal } | { ok: false; failure: AuthFailure };

function bearerFrom(request: Request): string | null {
  const header = request.headers.get('authorization');
  if (!header) return null;
  const match = header.match(/^Bearer\s+(.+)$/i);
  return match ? match[1]!.trim() : null;
}

/**
 * Resolves a request to a Principal, or an explicit failure.
 * A bearer token takes precedence: an explicit credential should never be
 * silently ignored in favour of an ambient cookie.
 */
export async function authenticate(request: Request): Promise<AuthResult> {
  const bearer = bearerFrom(request);

  if (bearer && looksLikeGitHubToken(bearer)) {
    // Passthrough: validate with GitHub, authorize with the same team rule as
    // the web path, and never store the token.
    const verdict = await authenticateGitHubToken(bearer);
    if (!verdict.ok) {
      return {
        ok: false,
        failure: {
          reason: verdict.reason === 'not-on-team' ? 'not-on-team' : 'bad-token',
          status: verdict.reason === 'not-on-team' ? 403 : 401,
          message: verdict.message,
        } as AuthFailure,
      };
    }
    return {
      ok: true,
      principal: {
        login: verdict.login,
        source: 'api',
        credential: 'github-token',
        githubToken: bearer,
        avatarUrl: '',
        name: verdict.login,
      },
    };
  }

  if (bearer) {
    const verdict = await verifyApiToken(bearer);
    if (!verdict.ok) {
      const message =
        verdict.reason === 'not-on-team'
          ? `That token's owner is no longer a member of ${config.teamLabel}; the token has been revoked.`
          : verdict.reason === 'revoked'
            ? 'That API token has been revoked.'
            : verdict.reason === 'expired'
              ? 'That API token has expired.'
              : `Invalid API token. Send a board token (${TOKEN_PREFIX}...) or a GitHub token.`;
      return {
        ok: false,
        failure: { reason: verdict.reason === 'not-on-team' ? 'not-on-team' : 'bad-token', status: verdict.reason === 'not-on-team' ? 403 : 401, message } as AuthFailure,
      };
    }
    return {
      ok: true,
      principal: {
        login: verdict.ownerLogin,
        source: 'api',
        credential: 'board-token',
        githubToken: null,
        avatarUrl: '',
        name: verdict.ownerLogin,
        tokenId: verdict.tokenId,
      },
    };
  }

  const jar = await cookies();
  const session = unsealSession(jar.get(SESSION_COOKIE)?.value, config.sessionSecret);
  if (!session) {
    return {
      ok: false,
      failure: {
        reason: 'anonymous',
        status: 401,
        message: 'Not authenticated. Sign in with GitHub, or send an API token as "Authorization: Bearer <token>".',
      },
    };
  }

  if (!(await sessionStillValid(session))) {
    return {
      ok: false,
      failure: {
        reason: 'not-on-team',
        status: 403,
        message: `You are no longer a member of ${config.teamLabel}.`,
      },
    };
  }

  return {
    ok: true,
    principal: {
      login: session.login,
      source: 'user',
      credential: 'session',
      githubToken: session.token,
      avatarUrl: session.avatarUrl,
      name: session.name,
      tokenId: undefined,
    },
  };
}
