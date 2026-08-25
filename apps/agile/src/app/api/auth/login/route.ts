import { NextResponse, type NextRequest } from 'next/server';
import { config } from '@/lib/env';
import { buildAuthorizeUrl } from '@/lib/auth/github-oauth';
import { createOAuthState, OAUTH_STATE_COOKIE, safeReturnTo } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const returnTo = safeReturnTo(request.nextUrl.searchParams.get('returnTo'));
  const state = createOAuthState(config.sessionSecret, returnTo);

  const url = buildAuthorizeUrl({
    clientId: config.githubClientId,
    redirectUri: `${config.appUrl}/api/auth/callback`,
    state,
  });

  const res = NextResponse.redirect(url);
  res.cookies.set(OAUTH_STATE_COOKIE, state, {
    httpOnly: true,
    secure: config.isProduction,
    sameSite: 'lax',
    path: '/',
    maxAge: 600,
  });
  return res;
}
