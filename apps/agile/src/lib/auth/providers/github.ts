import { config } from '@/lib/env';
import { createOAuthState, verifyOAuthState } from '../session';
import {
  buildAuthorizeUrl,
  exchangeCodeForToken,
  fetchAuthenticatedUser,
} from '../github-oauth';
import { checkTeamMembership } from '../team';
import { isStillOnTeam } from '../revalidate';
import type { AuthCallbackResult, AuthProvider, AuthStartResult } from './types';

/**
 * Direct GitHub OAuth. Retained as a fallback implementation — it needs one
 * OAuth app per instance (GitHub allows a single callback URL per app), which
 * is why Dex is the default for wizard-provisioned boards.
 */
export class GitHubProvider implements AuthProvider {
  readonly id = 'github' as const;
  readonly label = 'Sign in with GitHub';

  async start(returnTo: string): Promise<AuthStartResult> {
    const state = createOAuthState(config.sessionSecret, returnTo);
    return {
      redirectUrl: buildAuthorizeUrl({
        clientId: config.githubClientId,
        redirectUri: `${config.appUrl}/api/auth/callback`,
        state,
      }),
      stateCookie: state,
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
        message: `GitHub sign-in was cancelled (${params.get('error')}).`,
      };
    }

    const code = params.get('code');
    const state = params.get('state');
    if (!code || !state) {
      return { ok: false, reason: 'state-mismatch', message: 'Malformed sign-in response.' };
    }
    if (!stateCookie || stateCookie !== state) {
      return {
        ok: false,
        reason: 'state-mismatch',
        message: 'Sign-in state did not match. Please try again.',
      };
    }
    const verified = verifyOAuthState(state, config.sessionSecret);
    if (!verified) {
      return { ok: false, reason: 'state-mismatch', message: 'Sign-in state expired.' };
    }

    let token: string;
    let user: Awaited<ReturnType<typeof fetchAuthenticatedUser>>;
    try {
      token = await exchangeCodeForToken({
        code,
        clientId: config.githubClientId,
        clientSecret: config.githubClientSecret,
        redirectUri: `${config.appUrl}/api/auth/callback`,
      });
      user = await fetchAuthenticatedUser(token);
    } catch (err) {
      console.error('[auth] github exchange failed', err);
      return {
        ok: false,
        reason: 'exchange-failed',
        message: 'Could not complete GitHub sign-in. Please try again.',
      };
    }

    const decision = await checkTeamMembership(user.login, token);
    if (!decision.allowed) {
      return {
        ok: false,
        reason: decision.reason,
        login: user.login,
        message: `You are not an active member of ${config.teamLabel}.`,
      };
    }

    return {
      ok: true,
      returnTo: verified.returnTo,
      identity: {
        login: user.login,
        name: user.name,
        avatarUrl: user.avatarUrl,
        groups: [`${config.githubOrg}:${config.githubTeam}`],
        githubToken: token,
      },
    };
  }

  async revalidate(identity: {
    login: string;
    githubToken: string | null;
  }): Promise<'ok' | 'denied' | 'unknown'> {
    // A GitHub-provider session always has a token; if one is somehow missing
    // there is nothing to check with, so report "cannot tell" rather than
    // revoking a session that may be perfectly valid.
    if (!identity.githubToken) return 'unknown';
    return (await isStillOnTeam(identity.login, identity.githubToken)) ? 'ok' : 'denied';
  }
}
