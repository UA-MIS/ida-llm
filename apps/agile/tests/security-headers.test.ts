import { describe, it, expect, beforeAll } from 'vitest';

/**
 * Review finding MED-2 / F-1 — the app shipped with NO security headers at all.
 *
 * No CSP, no `Referrer-Policy`, no `nosniff`, no framing control, and the chart
 * test pins the agile Ingress as having no middleware, so nothing upstream was
 * adding them either. The markdown sanitiser was the only layer standing.
 *
 * These assert the POLICY, not merely that a header exists: a CSP that has been
 * quietly widened to `img-src *` or grown `'unsafe-eval'` is worse than no
 * header, because it still reads as "we have a CSP".
 */
describe('MED-2 — security response headers', () => {
  let headers: Record<string, string>;
  let csp: Map<string, string>;
  let rules: Array<{ source: string; headers: Array<{ key: string; value: string }> }>;

  beforeAll(async () => {
    const mod = await import('../next.config');
    const config = mod.default;
    rules = (await config.headers!()) as typeof rules;
    // One rule covering everything; flattened so order of declaration is not
    // what these tests are pinned to.
    headers = {};
    for (const rule of rules) {
      for (const h of rule.headers) headers[h.key.toLowerCase()] = h.value;
    }
    csp = new Map(
      headers['content-security-policy']!
        .split(';')
        .map((part) => part.trim())
        .filter(Boolean)
        .map((part) => {
          const [name, ...rest] = part.split(/\s+/);
          return [name!, rest.join(' ')] as [string, string];
        }),
    );
  });

  it('applies to every path, so no route is quietly exempt', () => {
    expect(rules).toHaveLength(1);
    expect(rules[0]!.source).toBe('/:path*');
  });

  it('sets a Content-Security-Policy', () => {
    expect(headers['content-security-policy']).toBeTruthy();
  });

  it('defaults to same-origin', () => {
    expect(csp.get('default-src')).toBe("'self'");
  });

  it('REFUSES framing — the board is not embeddable', () => {
    expect(csp.get('frame-ancestors')).toBe("'none'");
    expect(headers['x-frame-options']).toBe('DENY');
  });

  it('restricts images to same-origin plus the avatar host the UI actually uses', () => {
    const imgSrc = csp.get('img-src')!;
    expect(imgSrc.split(/\s+/)).toContain("'self'");
    // MED-1 defence in depth: an off-origin image in user markdown is a
    // tracking pixel that leaks IP, user-agent and timing. The sanitiser
    // already refuses one; this refuses it again at the browser.
    expect(imgSrc).not.toContain('*');
    expect(imgSrc.split(/\s+/)).not.toContain('https:');
    expect(imgSrc).not.toContain('data:');
  });

  it('does not permit an arbitrary host to be an image source', () => {
    const hosts = csp.get('img-src')!.split(/\s+/).filter((t) => !t.startsWith("'"));
    for (const host of hosts) {
      expect(host, `${host} must be a specific https host`).toMatch(/^https:\/\/[a-z0-9.-]+$/);
    }
  });

  it('NEVER allows eval', () => {
    expect(headers['content-security-policy']).not.toContain('unsafe-eval');
  });

  it('forbids plugins and locks <base>, so an injection cannot re-point relative URLs', () => {
    expect(csp.get('object-src')).toBe("'none'");
    expect(csp.get('base-uri')).toBe("'self'");
  });

  it('keeps form submissions same-origin, so an injected form cannot post the session elsewhere', () => {
    expect(csp.get('form-action')).toBe("'self'");
  });

  it('sends a Referrer-Policy that does not leak the item id off-origin', () => {
    expect(headers['referrer-policy']).toBe('strict-origin-when-cross-origin');
  });

  it('sends nosniff, so an attachment cannot be re-typed by the browser', () => {
    expect(headers['x-content-type-options']).toBe('nosniff');
  });

  it('does not re-introduce the framework version banner', async () => {
    const config = (await import('../next.config')).default;
    expect(config.poweredByHeader).toBe(false);
  });
});
