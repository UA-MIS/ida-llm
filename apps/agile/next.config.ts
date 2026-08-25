import type { NextConfig } from 'next';

/**
 * The one off-origin host the board's OWN UI loads an image from.
 *
 * `Shell`, `chips` and `ItemDetail` render `<img src={avatarUrl}>`, and for a
 * GitHub-backed session that URL is a githubusercontent avatar. A bare
 * `img-src 'self'` would therefore blank every avatar in the product, so this
 * is the minimum widening that keeps the UI intact.
 *
 * It is deliberately ONE exact host rather than `https:`. The point of the
 * image policy is that a tracking pixel in user-authored markdown cannot reach
 * a host the author controls (review finding MED-1); an attacker who can only
 * name GitHub's avatar CDN learns nothing, because they cannot read its logs.
 *
 * NOTE for an OIDC/Dex board: if the identity provider serves the `picture`
 * claim from some other host, that host has to be added here or its avatars
 * will not render. Nothing else breaks -- `<img>` simply does not load.
 */
const AVATAR_HOST = 'https://avatars.githubusercontent.com';

/**
 * Content-Security-Policy (review finding MED-2 / F-1).
 *
 * The board had no CSP, no referrer policy, no nosniff and no framing control,
 * and the Ingress adds no middleware, so the markdown sanitiser was the only
 * layer between a page author and a reader's browser. This is the second layer.
 *
 * ── Why `'unsafe-inline'` appears, and what it does and does not cost ───────
 * Next's App Router streams the RSC payload and React's hydration bootstrap as
 * INLINE `<script>` tags, and the framework's own styles arrive as inline
 * `<style>`; the product additionally uses React `style={{...}}` attributes
 * throughout, which `style-src` governs. The clean fix for the script half is a
 * per-request nonce, and that requires Next middleware -- which this deployment
 * deliberately does not have (the chart test asserts the agile Ingress runs
 * none, and adding middleware to satisfy a header is a much larger change than
 * the finding warrants). So inline is allowed, and the honest accounting is:
 *
 *   - What this CSP still buys: no off-origin script, style, frame, font,
 *     connection or image; no `eval`; no plugins; no framing of the board; no
 *     `<base>` rewrite; no form posting the session to another origin.
 *   - What it does NOT buy: it is not an XSS backstop. If markup ever reaches a
 *     page unsanitised, `'unsafe-inline'` lets it run. The sanitiser in
 *     `src/lib/markdown.ts` remains the control that matters, and this policy
 *     must never be treated as a reason to relax it.
 *
 * `'unsafe-eval'` is NOT present and must not be added: nothing in the app
 * needs it, and it is the directive that turns a data-injection into code
 * execution.
 */
const CSP = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  `img-src 'self' ${AVATAR_HOST}`,
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self'",
  "connect-src 'self'",
].join('; ');

const SECURITY_HEADERS = [
  { key: 'Content-Security-Policy', value: CSP },
  // The board's URLs carry work-item ids. `strict-origin-when-cross-origin`
  // sends the full path only to ourselves; anywhere off-origin sees the origin
  // alone, so following a PR link does not tell GitHub which item you were on.
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  // Attachments are served with a stored filename and no sniffing protection;
  // this stops a browser re-typing one into something executable.
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  // `frame-ancestors` above is the modern control and covers more cases; this
  // is here for anything that still only understands the legacy header.
  { key: 'X-Frame-Options', value: 'DENY' },
];

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  // One rule for every path, including `/api/*`: a header policy with an
  // exemption is a header policy with a hole, and there is no route here that
  // wants weaker rules than the rest.
  async headers() {
    return [{ source: '/:path*', headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
