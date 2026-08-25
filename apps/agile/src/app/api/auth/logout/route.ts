import { NextResponse } from 'next/server';
import { config } from '@/lib/env';
import { SESSION_COOKIE } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

/**
 * POST /api/auth/logout — end the session.
 *
 * POST ONLY. That is a security boundary, not a style preference, and adding
 * `export const GET` back re-opens a stored CSRF.
 *
 * A state-changing GET is reachable by anything that can put a URL on a page.
 * Narrative pages and work-item descriptions render user-authored markdown, and
 * that markdown may contain images, so `![](/api/auth/logout)` becomes
 * `<img src="/api/auth/logout">`. The browser fires that GET automatically,
 * same-origin, with cookies, before the reader does anything at all -- and the
 * response clears their session. One poisoned description, or the shared
 * homepage that every member can write, logs out everyone who looks at it.
 * Re-logging in returns to `/`, which may be the poisoned page again.
 *
 * The fix belongs here rather than in the sanitiser. Blocking `/api/` inside
 * markdown would be a blocklist that has to enumerate every dangerous endpoint
 * and stays wrong as endpoints are added; an image pointing at this route is
 * only dangerous because the route acts on a GET.
 *
 * `<img>`, `<link>`, prefetchers, link previewers and URL scanners can all
 * issue GET and none of them can issue POST, so refusing GET ends the class.
 * Next.js answers an unexported method with 405 on its own -- there is
 * deliberately no GET handler here to answer it more politely.
 *
 * SameSite=Lax on the session cookie already blocks a CROSS-site POST, so the
 * remaining same-origin POST path is reachable only from our own form.
 */
export function POST() {
  // 303, not the default 307. A 307 preserves the method, so the browser would
  // re-issue this as POST /login; 303 is what turns a POST into the plain GET
  // navigation the login page expects.
  const res = NextResponse.redirect(new URL('/login', config.appUrl), 303);
  res.cookies.set(SESSION_COOKIE, '', {
    httpOnly: true,
    secure: config.isProduction,
    sameSite: 'lax',
    path: '/',
    maxAge: 0,
  });
  return res;
}
