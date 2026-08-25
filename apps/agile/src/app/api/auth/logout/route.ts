import { NextResponse } from 'next/server';
import { config } from '@/lib/env';
import { SESSION_COOKIE } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

/**
 * Is this POST one our own pages made?
 *
 * `Sec-Fetch-Site` first, because the BROWSER computes it and a page cannot
 * set it. `same-origin` is our own form. `none` means the user themselves
 * started the navigation -- a bookmark or the URL bar -- which no other page
 * can forge. Everything else, including `same-site`, is refused: a sibling
 * host on the same registrable domain is still not us.
 *
 * `Origin` is the fallback for a client that omits the fetch-metadata headers,
 * compared against the board's own configured URL rather than the request's,
 * because behind an ingress the request URL is the internal one while `Origin`
 * is what the browser saw.
 *
 * A request carrying NEITHER signal is refused. Every browser sends at least
 * one on a form POST, and a session cookie is meaningless to an API client --
 * those authenticate per-request with a bearer token and have nothing to log
 * out of. Failing closed here costs no real caller anything.
 */
function isSelfInitiated(request: Request): boolean {
  const site = request.headers.get('sec-fetch-site');
  if (site) return site === 'same-origin' || site === 'none';

  const origin = request.headers.get('origin');
  if (origin) {
    try {
      return origin === new URL(config.appUrl).origin;
    } catch {
      return false;
    }
  }

  return false;
}

/**
 * POST /api/auth/logout — end the session.
 *
 * POST ONLY, and same-origin only. Both halves are security boundaries, not
 * style preferences.
 *
 * ── Why not GET (review finding HIGH-1) ─────────────────────────────────────
 * A state-changing GET is reachable by anything that can put a URL on a page.
 * Narrative pages and work-item descriptions render user-authored markdown, and
 * that markdown may contain images, so `![](/api/auth/logout)` becomes
 * `<img src="/api/auth/logout">`. The browser fires that GET automatically,
 * same-origin, with cookies, before the reader does anything at all -- and the
 * response cleared their session. One poisoned description, or the shared
 * homepage that every member can write, logged out everyone who looked at it.
 *
 * The fix belongs here rather than in the sanitiser. Blocking `/api/` inside
 * markdown would be a blocklist that has to enumerate every dangerous endpoint
 * and stays wrong as endpoints are added; an image pointing at this route is
 * only dangerous because the route acts on a GET.
 *
 * `<img>`, `<link>`, prefetchers, link previewers and URL scanners can all
 * issue GET and none of them can issue POST, so refusing GET ends the class.
 * Next.js answers an unexported method with 405 on its own -- there is
 * deliberately no GET handler here to answer it more politely. Adding
 * `export const GET` back re-opens a stored CSRF.
 *
 * ── Why the same-origin check (review finding LOW-4) ────────────────────────
 * This docstring previously claimed `SameSite=Lax` on the session cookie
 * already blocked a cross-site POST. THAT WAS WRONG, and the correction is the
 * reason this function exists.
 *
 * `SameSite` governs whether the browser SENDS our cookie on a request. It says
 * nothing about whether the browser HONOURS a `Set-Cookie` on the RESPONSE, and
 * this route emitted its clearing `Set-Cookie` unconditionally -- it never
 * needed to read the session to destroy it. So a cross-site page could
 * auto-submit a form here and Chrome would honour the clearing cookie on the
 * resulting top-level navigation. Confirmed in real Chromium.
 *
 * The control is therefore an explicit check on the request, above: no
 * `Set-Cookie` is emitted at all unless the POST came from us.
 */
export function POST(request: Request): NextResponse {
  if (!isSelfInitiated(request)) {
    // Deliberately emits no `Set-Cookie`. Refusing while still clearing the
    // session would leave the finding exactly where it was.
    return new NextResponse('Sign-out must be initiated from the board itself.', {
      status: 403,
      headers: { 'content-type': 'text/plain; charset=utf-8' },
    });
  }

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
