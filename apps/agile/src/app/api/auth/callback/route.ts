import { NextResponse, type NextRequest } from 'next/server';
import { config } from '@/lib/env';
import { exchangeCodeForToken, fetchAuthenticatedUser } from '@/lib/auth/github-oauth';
import { checkTeamMembership } from '@/lib/auth/team';
import {
  OAUTH_STATE_COOKIE,
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  sealSession,
  verifyOAuthState,
} from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

/**
 * OAuth callback. This is the only place a session is ever minted, and it is
 * minted ONLY after an active team membership has been confirmed.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;

  if (params.get('error')) {
    return fail(`GitHub sign-in was cancelled (${params.get('error')}).`);
  }

  const code = params.get('code');
  const state = params.get('state');
  if (!code || !state) return fail('Malformed sign-in response from GitHub.');

  // CSRF: the state must match the one we set, and must verify.
  const cookieState = request.cookies.get(OAUTH_STATE_COOKIE)?.value;
  if (!cookieState || cookieState !== state) {
    return fail('Sign-in state did not match. Please try again.');
  }
  const verified = verifyOAuthState(state, config.sessionSecret);
  if (!verified) return fail('Sign-in state was invalid or expired. Please try again.');

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
    console.error('[auth] token exchange failed', err);
    return fail('Could not complete GitHub sign-in. Please try again.');
  }

  // THE authorization gate.
  const decision = await checkTeamMembership(user.login, token);
  if (!decision.allowed) {
    const res = NextResponse.redirect(
      new URL(`/denied?reason=${decision.reason}&login=${encodeURIComponent(user.login)}`, config.appUrl),
    );
    res.cookies.set(OAUTH_STATE_COOKIE, '', { path: '/', maxAge: 0 });
    return res;
  }

  const session = sealSession(
    { login: user.login, name: user.name, avatarUrl: user.avatarUrl, token },
    config.sessionSecret,
  );

  const res = NextResponse.redirect(new URL(verified.returnTo, config.appUrl));
  res.cookies.set(SESSION_COOKIE, session, {
    httpOnly: true,
    secure: config.isProduction,
    sameSite: 'lax',
    path: '/',
    maxAge: SESSION_TTL_SECONDS,
  });
  res.cookies.set(OAUTH_STATE_COOKIE, '', { path: '/', maxAge: 0 });
  return res;
}

function fail(message: string) {
  return NextResponse.redirect(
    new URL(`/login?error=${encodeURIComponent(message)}`, config.appUrl),
  );
}
