import { NextResponse, type NextRequest } from 'next/server';
import { config } from '@/lib/env';
import { authProvider } from '@/lib/auth/providers';
import { OAUTH_STATE_COOKIE, safeReturnTo } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const returnTo = safeReturnTo(request.nextUrl.searchParams.get('returnTo'));

  let start: Awaited<ReturnType<ReturnType<typeof authProvider>['start']>>;
  try {
    start = await authProvider().start(returnTo);
  } catch (err) {
    console.error('[auth] could not begin sign-in', err);
    return NextResponse.redirect(
      new URL(
        `/login?error=${encodeURIComponent(
          `Sign-in is unavailable: ${(err as Error).message}`,
        )}`,
        config.appUrl,
      ),
    );
  }

  const res = NextResponse.redirect(start.redirectUrl);
  res.cookies.set(OAUTH_STATE_COOKIE, start.stateCookie, {
    httpOnly: true,
    secure: config.isProduction,
    sameSite: 'lax',
    path: '/',
    maxAge: 600,
  });
  return res;
}
