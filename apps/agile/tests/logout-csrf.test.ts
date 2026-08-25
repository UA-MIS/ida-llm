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
    const res = route.POST();
    const cookie = res.headers.get('set-cookie') ?? '';
    expect(cookie).toContain('agile_session=');
    expect(cookie.toLowerCase()).toContain('max-age=0');
    expect(cookie.toLowerCase()).toContain('httponly');
  });

  it('redirects a POST with 303, so the browser does not re-POST to /login', () => {
    // The default for NextResponse.redirect is 307, which preserves the
    // method -- that would send POST /login and break sign-out entirely.
    const res = route.POST();
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
