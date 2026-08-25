import { NextResponse, type NextRequest } from 'next/server';
import { config } from '@/lib/env';
import { authProvider } from '@/lib/auth/providers';
import {
  OAUTH_STATE_COOKIE,
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  sealSession,
} from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

/**
 * Provider callback. This is the ONLY place a session is minted, and it is
 * minted only after the provider has confirmed the caller belongs to the
 * configured team/group.
 */
export async function GET(request: NextRequest) {
  const provider = authProvider();
  const stateCookie = request.cookies.get(OAUTH_STATE_COOKIE)?.value;

  let result: Awaited<ReturnType<typeof provider.callback>>;
  try {
    result = await provider.callback(request.nextUrl.searchParams, stateCookie);
  } catch (err) {
    console.error('[auth] callback failed', err);
    result = {
      ok: false,
      reason: 'exchange-failed',
      message: 'Could not complete sign-in. Please try again.',
    };
  }

  if (!result.ok) {
    // A failed authorization goes to /denied; a broken handshake goes back to
    // /login, because retrying is the right action there.
    const target =
      result.reason === 'not-a-member' || result.reason === 'invitation-pending'
        ? `/denied?reason=${result.reason}${result.login ? `&login=${encodeURIComponent(result.login)}` : ''}`
        : `/login?error=${encodeURIComponent(result.message)}`;

    const res = NextResponse.redirect(new URL(target, config.appUrl));
    res.cookies.set(OAUTH_STATE_COOKIE, '', { path: '/', maxAge: 0 });
    return res;
  }

  const session = sealSession(
    {
      login: result.identity.login,
      name: result.identity.name,
      avatarUrl: result.identity.avatarUrl,
      token: result.identity.githubToken ?? '',
      groups: result.identity.groups,
      provider: provider.id,
    },
    config.sessionSecret,
  );

  const res = NextResponse.redirect(new URL(result.returnTo, config.appUrl));
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
