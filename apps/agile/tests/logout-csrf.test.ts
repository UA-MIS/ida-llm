import { describe, it, expect, beforeAll } from 'vitest';
import { installTestEnv } from './helpers/db';
import { renderMarkdown } from '@/lib/markdown';

installTestEnv('agile_logout_csrf_test');

/**
 * Review finding HIGH-1 — stored, zero-interaction forced logout.
 *
 * Allowing `img` in rendered markdown gave any page author a same-origin GET
 * that fires on view. The logout route exported `GET = clear`, so
 * `![](/api/auth/logout)` was a stored CSRF: every reader of a poisoned
 * work-item description -- or of the shared homepage, which any member may
 * write -- was logged out before touching anything.
 *
 * These tests pin the fix AT THE ROOT. The first one deliberately asserts that
 * the sanitiser still renders the image: if someone "fixes" this by
 * blocklisting `/api/` in markdown.ts, that is the guess-the-endpoint
 * anti-pattern this PR exists to avoid, and this test fails to say so. The
 * safety has to come from the route refusing GET, which the rest assert.
 */

const APP_ORIGIN = 'http://localhost:3000';

/** What the browser actually sends for the in-app `<form method="post">`. */
function sameOriginPost(extra: Record<string, string> = {}): Request {
  return new Request(`${APP_ORIGIN}/api/auth/logout`, {
    method: 'POST',
    headers: {
      origin: APP_ORIGIN,
      'sec-fetch-site': 'same-origin',
      'sec-fetch-mode': 'navigate',
      ...extra,
    },
  });
}

/** What a cross-site auto-submitting form looks like on the wire. */
function crossSitePost(origin = 'https://evil.example'): Request {
  return new Request(`${APP_ORIGIN}/api/auth/logout`, {
    method: 'POST',
    headers: { origin, 'sec-fetch-site': 'cross-site', 'sec-fetch-mode': 'navigate' },
  });
}

function clearsSession(res: Response): boolean {
  const cookie = res.headers.get('set-cookie') ?? '';
  return cookie.includes('agile_session=') && cookie.toLowerCase().includes('max-age=0');
}

describe('HIGH-1 — logout cannot be triggered by a subresource GET', () => {
  let route: typeof import('@/app/api/auth/logout/route');

  beforeAll(async () => {
    route = await import('@/app/api/auth/logout/route');
  });

  it('still renders the image — the sanitiser is NOT where this was fixed', () => {
    const html = renderMarkdown('![](/api/auth/logout)');
    expect(html).toContain('<img');
    expect(html).toContain('src="/api/auth/logout"');
  });

  it('exports no GET handler, so a browser subresource fetch gets 405', () => {
    // An <img>, <link>, prefetcher or URL scanner can only issue GET. Next.js
    // answers an unexported method with 405 by itself, so the absence of this
    // export IS the control.
    expect((route as Record<string, unknown>).GET).toBeUndefined();
  });

  it('a POST still ends the session, and clears the cookie', () => {
    const res = route.POST(sameOriginPost());
    const cookie = res.headers.get('set-cookie') ?? '';
    expect(cookie).toContain('agile_session=');
    expect(cookie.toLowerCase()).toContain('max-age=0');
    expect(cookie.toLowerCase()).toContain('httponly');
  });

  it('redirects a POST with 303, so the browser does not re-POST to /login', () => {
    // The default for NextResponse.redirect is 307, which preserves the
    // method -- that would send POST /login and break sign-out entirely.
    const res = route.POST(sameOriginPost());
    expect(res.status).toBe(303);
    expect(res.headers.get('location')).toContain('/login');
  });

  it('the only logout call sites are POST forms, never links', async () => {
    const { readFileSync } = await import('node:fs');
    for (const file of ['../src/components/Shell.tsx', '../src/app/denied/page.tsx']) {
      const src = readFileSync(new URL(file, import.meta.url), 'utf8');
      expect(src, `${file} must not link to logout`).not.toMatch(
        /<a[^>]*href=["']\/api\/auth\/logout/,
      );
      expect(src, `${file} must POST to logout`).toContain(
        'action="/api/auth/logout" method="post"',
      );
    }
  });
});

/**
 * Review finding LOW-4 — logout POST was unguarded against cross-site forms.
 *
 * HIGH-1 closed the zero-interaction GET. What remained was a cross-site
 * auto-submitting `<form method="post">`: the route emitted its clearing
 * `Set-Cookie` UNCONDITIONALLY, and the route's own docstring claimed
 * `SameSite=Lax` covered this. It does not. Lax governs whether the browser
 * SENDS our cookie; it says nothing about whether the browser HONOURS a
 * `Set-Cookie` on the response to a cross-site top-level navigation, and Chrome
 * honours it. Confirmed in real Chromium during the PR #18 review.
 *
 * The control is an explicit same-origin check on the request, asserted here.
 */
describe('LOW-4 — logout refuses a cross-site POST', () => {
  let route: typeof import('@/app/api/auth/logout/route');

  beforeAll(async () => {
    route = await import('@/app/api/auth/logout/route');
  });

  it('CLEARS the session for the in-app same-origin form POST', () => {
    const res = route.POST(sameOriginPost());
    expect(res.status).toBe(303);
    expect(res.headers.get('location')).toContain('/login');
    expect(clearsSession(res)).toBe(true);
  });

  it('REFUSES a cross-site form POST and does NOT clear the session', () => {
    const res = route.POST(crossSitePost());
    expect(res.status).toBe(403);
    expect(res.headers.get('set-cookie')).toBeNull();
  });

  it('refuses a foreign Origin even when Sec-Fetch-Site is absent', () => {
    // Sec-Fetch-Site is the primary signal, but a client that omits it must not
    // thereby get a weaker check.
    const res = route.POST(
      new Request(`${APP_ORIGIN}/api/auth/logout`, {
        method: 'POST',
        headers: { origin: 'https://evil.example' },
      }),
    );
    expect(res.status).toBe(403);
    expect(res.headers.get('set-cookie')).toBeNull();
  });

  it('refuses a SAME-SITE-but-cross-origin POST, so a sibling host cannot log you out', () => {
    const res = route.POST(
      new Request(`${APP_ORIGIN}/api/auth/logout`, {
        method: 'POST',
        headers: { origin: 'http://other.localhost:3000', 'sec-fetch-site': 'same-site' },
      }),
    );
    expect(res.status).toBe(403);
    expect(res.headers.get('set-cookie')).toBeNull();
  });

  it('FAILS CLOSED when the request carries neither signal', () => {
    // A modern browser always sends at least one for a form POST. Anything that
    // sends neither is not the sign-out button, and a session cookie is useless
    // to a non-browser client anyway.
    const res = route.POST(new Request(`${APP_ORIGIN}/api/auth/logout`, { method: 'POST' }));
    expect(res.status).toBe(403);
    expect(res.headers.get('set-cookie')).toBeNull();
  });

  it('allows a direct navigation (Sec-Fetch-Site: none), which no other page can forge', () => {
    // `none` means the user themselves initiated it -- a bookmark or the URL
    // bar. A form on another page can never produce it.
    const res = route.POST(
      new Request(`${APP_ORIGIN}/api/auth/logout`, {
        method: 'POST',
        headers: { 'sec-fetch-site': 'none' },
      }),
    );
    expect(res.status).toBe(303);
    expect(clearsSession(res)).toBe(true);
  });

  it('trusts Sec-Fetch-Site over a mismatched Origin, since the browser computes it', () => {
    const res = route.POST(
      new Request(`${APP_ORIGIN}/api/auth/logout`, {
        method: 'POST',
        headers: { origin: APP_ORIGIN, 'sec-fetch-site': 'cross-site' },
      }),
    );
    expect(res.status).toBe(403);
  });

  it('does not claim SameSite closes this — the docstring must not mislead the next reader', async () => {
    const { readFileSync } = await import('node:fs');
    const src = readFileSync(new URL('../src/app/api/auth/logout/route.ts', import.meta.url), 'utf8');
    expect(src).not.toMatch(/SameSite=Lax[^.]*already blocks a CROSS-site POST/);
    // ...and it must name the control that actually does the work.
    expect(src.toLowerCase()).toContain('sec-fetch-site');
  });
});
