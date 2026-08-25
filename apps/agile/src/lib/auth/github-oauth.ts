import { config } from '@/lib/env';

/**
 * `read:org` is required to read team membership. `read:user` gives us the
 * profile (login, name, avatar). We never request write scopes.
 */
export const OAUTH_SCOPES = 'read:user read:org';

export interface GitHubUser {
  login: string;
  name: string;
  avatarUrl: string;
}

export type Fetcher = typeof fetch;

export function buildAuthorizeUrl(params: {
  clientId: string;
  redirectUri: string;
  state: string;
}): string {
  const u = new URL('https://github.com/login/oauth/authorize');
  u.searchParams.set('client_id', params.clientId);
  u.searchParams.set('redirect_uri', params.redirectUri);
  u.searchParams.set('scope', OAUTH_SCOPES);
  u.searchParams.set('state', params.state);
  u.searchParams.set('allow_signup', 'false');
  return u.toString();
}

export class OAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OAuthError';
  }
}

/** Exchanges the temporary code for a user access token. */
export async function exchangeCodeForToken(
  args: { code: string; clientId: string; clientSecret: string; redirectUri: string },
  fetchImpl: Fetcher = fetch,
): Promise<string> {
  const res = await fetchImpl('https://github.com/login/oauth/access_token', {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify({
      client_id: args.clientId,
      client_secret: args.clientSecret,
      code: args.code,
      redirect_uri: args.redirectUri,
    }),
  });

  if (!res.ok) {
    throw new OAuthError(`GitHub token exchange failed with HTTP ${res.status}`);
  }

  const body = (await res.json()) as { access_token?: string; error_description?: string };
  if (!body.access_token) {
    throw new OAuthError(body.error_description ?? 'GitHub did not return an access token');
  }
  return body.access_token;
}

export async function fetchAuthenticatedUser(
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<GitHubUser> {
  const res = await fetchImpl('https://api.github.com/user', {
    headers: ghHeaders(token),
  });
  if (!res.ok) {
    throw new OAuthError(`Could not read GitHub profile (HTTP ${res.status})`);
  }
  const u = (await res.json()) as { login?: string; name?: string | null; avatar_url?: string };
  if (!u.login) throw new OAuthError('GitHub profile response had no login');
  return {
    login: u.login,
    name: u.name ?? u.login,
    avatarUrl: u.avatar_url ?? '',
  };
}

export function ghHeaders(token: string): Record<string, string> {
  return {
    authorization: `Bearer ${token}`,
    accept: 'application/vnd.github+json',
    'x-github-api-version': '2022-11-28',
    'user-agent': 'ida-agile',
  };
}

export const TEAM_MEMBERSHIP_URL = (login: string) =>
  `https://api.github.com/orgs/${config.githubOrg}/teams/${config.githubTeam}/memberships/${encodeURIComponent(
    login,
  )}`;
