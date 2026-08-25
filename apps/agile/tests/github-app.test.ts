import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { generateKeyPairSync } from 'node:crypto';
import { jwtVerify } from 'jose';
import {
  getInstallationToken,
  resetInstallationTokenCache,
  installationTokenState,
} from '@/lib/github/app';
import { normalizePrivateKey, config } from '@/lib/env';

// One real RSA keypair for the whole suite: the App JWT is genuinely signed and
// genuinely verified, so a broken PEM path fails here rather than in production.
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const PKCS1 = privateKey.export({ type: 'pkcs1', format: 'pem' }).toString();
const PKCS8 = privateKey.export({ type: 'pkcs8', format: 'pem' }).toString();
// generateKeyPairSync already hands back a public KeyObject; jose verifies with it directly.
const PUBLIC = publicKey;

const APP_ID = '4097147';
const INSTALL_ID = '141394298';
const ACCESS_TOKEN_URL = `https://api.github.com/app/installations/${INSTALL_ID}/access_tokens`;

function inSeconds(n: number): string {
  return new Date(Date.now() + n * 1000).toISOString();
}

/** A fetch double that records calls and answers the access-token endpoint. */
function mintingFetch(
  responses: Array<{ status?: number; token?: string; expiresAt?: string; body?: unknown }>,
) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  let n = 0;
  const impl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const r = responses[Math.min(n++, responses.length - 1)]!;
    const status = r.status ?? 201;
    const body =
      r.body ?? { token: r.token ?? 'ghs_minted', expires_at: r.expiresAt ?? inSeconds(3600) };
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    });
  });
  return { impl: impl as unknown as typeof fetch, calls, fn: impl };
}

function configureApp(key: string = PKCS1): void {
  process.env.GITHUB_APP_ID = APP_ID;
  process.env.GITHUB_APP_PRIVATE_KEY = key;
  process.env.GITHUB_APP_INSTALLATION_ID = INSTALL_ID;
}

function clearApp(): void {
  delete process.env.GITHUB_APP_ID;
  delete process.env.GITHUB_APP_PRIVATE_KEY;
  delete process.env.GITHUB_APP_INSTALLATION_ID;
}

beforeEach(() => {
  resetInstallationTokenCache();
  clearApp();
  delete process.env.GITHUB_POLL_TOKEN;
  vi.useRealTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// ---------------------------------------------------------------- PEM shapes

describe('private key normalisation — the classic Vault→ESO→env mangling', () => {
  it('passes a well-formed PKCS#1 PEM through unchanged in substance', () => {
    const out = normalizePrivateKey(PKCS1);
    expect(out).toContain('-----BEGIN RSA PRIVATE KEY-----');
    expect(out).toContain('-----END RSA PRIVATE KEY-----');
    expect(out.split('\n').length).toBeGreaterThan(3);
  });

  it('accepts PKCS#8, which is what some tooling re-exports', () => {
    expect(normalizePrivateKey(PKCS8)).toContain('-----BEGIN PRIVATE KEY-----');
  });

  it('repairs a PEM whose newlines arrived as literal backslash-n', () => {
    const mangled = PKCS1.trim().replace(/\n/g, '\\n');
    expect(mangled).not.toContain('\n');
    const out = normalizePrivateKey(mangled);
    expect(out).toContain('\n');
    // Byte-for-byte the original key back, plus the trailing newline OpenSSL wants.
    expect(out).toBe(`${PKCS1.trim()}\n`);
  });

  it('repairs a PEM whose newlines arrived as literal CRLF escapes', () => {
    const mangled = PKCS1.trim().replace(/\n/g, '\\r\\n');
    expect(normalizePrivateKey(mangled)).toBe(`${PKCS1.trim()}\n`);
  });

  it('accepts a base64-wrapped PEM, the safest shape to put in Vault', () => {
    const wrapped = Buffer.from(PKCS1).toString('base64');
    expect(normalizePrivateKey(wrapped)).toContain('-----BEGIN RSA PRIVATE KEY-----');
  });

  it('returns empty for junk rather than pretending it has a key', () => {
    expect(normalizePrivateKey('')).toBe('');
    expect(normalizePrivateKey('   ')).toBe('');
    expect(normalizePrivateKey('not-a-key')).toBe('');
  });

  it('config.githubAppConfigured is false unless all three values are present', () => {
    expect(config.githubAppConfigured).toBe(false);
    process.env.GITHUB_APP_ID = APP_ID;
    expect(config.githubAppConfigured).toBe(false);
    process.env.GITHUB_APP_PRIVATE_KEY = PKCS1;
    expect(config.githubAppConfigured).toBe(false);
    process.env.GITHUB_APP_INSTALLATION_ID = INSTALL_ID;
    expect(config.githubAppConfigured).toBe(true);
  });

  it('is NOT configured when the private key is junk, even if the ids are set', () => {
    configureApp('not-a-key');
    expect(config.githubAppConfigured).toBe(false);
  });
});

// -------------------------------------------------------------------- minting

describe('installation token minting', () => {
  it('returns null, and calls nothing, when the App is not configured', async () => {
    const f = mintingFetch([{}]);
    expect(await getInstallationToken(f.impl)).toBeNull();
    expect(f.fn).not.toHaveBeenCalled();
  });

  it('POSTs to the installation access-token endpoint and returns the token', async () => {
    configureApp();
    const f = mintingFetch([{ token: 'ghs_realtoken', expiresAt: inSeconds(3600) }]);

    expect(await getInstallationToken(f.impl)).toBe('ghs_realtoken');
    expect(f.calls).toHaveLength(1);
    expect(f.calls[0]!.url).toBe(ACCESS_TOKEN_URL);
    expect(f.calls[0]!.init?.method).toBe('POST');
  });

  it('authenticates with an RS256 App JWT that GitHub would accept', async () => {
    configureApp();
    const f = mintingFetch([{}]);
    await getInstallationToken(f.impl);

    const headers = f.calls[0]!.init?.headers as Record<string, string>;
    const jwt = headers.authorization?.replace(/^Bearer /, '') ?? '';
    expect(jwt.split('.')).toHaveLength(3);

    const { payload, protectedHeader } = await jwtVerify(jwt, PUBLIC);
    expect(protectedHeader.alg).toBe('RS256');
    // The issuer is the App ID — the single most common thing to get wrong.
    expect(payload.iss).toBe(APP_ID);
    // iat is BACKDATED so a fast server clock does not produce a future-dated
    // token, which GitHub rejects with a 401 that reads like a bad key.
    const now = Math.floor(Date.now() / 1000);
    expect(payload.iat!).toBeLessThan(now);
    expect(payload.iat!).toBeGreaterThanOrEqual(now - 120);
    // GitHub caps App JWT lifetime at 10 minutes and rejects anything longer.
    expect(payload.exp! - payload.iat!).toBeLessThanOrEqual(600);
    expect(payload.exp!).toBeGreaterThan(now);
  });

  it('signs with a PKCS#8 key too', async () => {
    configureApp(PKCS8);
    const f = mintingFetch([{ token: 'ghs_pkcs8' }]);
    expect(await getInstallationToken(f.impl)).toBe('ghs_pkcs8');
  });

  it('signs with a key that arrived with mangled newlines', async () => {
    configureApp(PKCS1.trim().replace(/\n/g, '\\n'));
    const f = mintingFetch([{ token: 'ghs_unmangled' }]);
    expect(await getInstallationToken(f.impl)).toBe('ghs_unmangled');
  });

  it('sends the GitHub API version header, as the REST API requires', async () => {
    configureApp();
    const f = mintingFetch([{}]);
    await getInstallationToken(f.impl);
    const headers = f.calls[0]!.init?.headers as Record<string, string>;
    expect(headers.accept).toContain('application/vnd.github');
    expect(headers['x-github-api-version']).toBeTruthy();
  });
});

// -------------------------------------------------------------------- caching

describe('caching — an installation token lasts ~1h and must not be re-minted per request', () => {
  it('mints once and serves the cached token on subsequent calls', async () => {
    configureApp();
    const f = mintingFetch([{ token: 'ghs_first' }]);

    expect(await getInstallationToken(f.impl)).toBe('ghs_first');
    expect(await getInstallationToken(f.impl)).toBe('ghs_first');
    expect(await getInstallationToken(f.impl)).toBe('ghs_first');
    expect(f.fn).toHaveBeenCalledTimes(1);
  });

  it('mints ONCE for concurrent callers rather than once per caller', async () => {
    configureApp();
    const f = mintingFetch([{ token: 'ghs_single' }]);

    const results = await Promise.all([
      getInstallationToken(f.impl),
      getInstallationToken(f.impl),
      getInstallationToken(f.impl),
      getInstallationToken(f.impl),
    ]);

    expect(results).toEqual(['ghs_single', 'ghs_single', 'ghs_single', 'ghs_single']);
    expect(f.fn).toHaveBeenCalledTimes(1);
  });

  it('re-mints when the cached token has expired', async () => {
    configureApp();
    // Already expired on arrival: the very next call must go back to GitHub.
    const f = mintingFetch([
      { token: 'ghs_stale', expiresAt: inSeconds(-1) },
      { token: 'ghs_fresh', expiresAt: inSeconds(3600) },
    ]);

    expect(await getInstallationToken(f.impl)).toBe('ghs_stale');
    expect(await getInstallationToken(f.impl)).toBe('ghs_fresh');
    expect(f.fn).toHaveBeenCalledTimes(2);
  });

  it('re-mints EARLY, before expiry, so an in-flight call cannot expire mid-request', async () => {
    configureApp();
    // 30s of life left: still technically valid, but inside the safety margin.
    const f = mintingFetch([
      { token: 'ghs_nearly_done', expiresAt: inSeconds(30) },
      { token: 'ghs_renewed', expiresAt: inSeconds(3600) },
    ]);

    expect(await getInstallationToken(f.impl)).toBe('ghs_nearly_done');
    expect(await getInstallationToken(f.impl)).toBe('ghs_renewed');
  });

  it('keeps a comfortably-valid token instead of renewing it', async () => {
    configureApp();
    const f = mintingFetch([{ token: 'ghs_plenty', expiresAt: inSeconds(3000) }]);
    await getInstallationToken(f.impl);
    await getInstallationToken(f.impl);
    expect(f.fn).toHaveBeenCalledTimes(1);
  });

  it('tolerates a response with no expires_at by assuming a short life', async () => {
    configureApp();
    const f = mintingFetch([{ body: { token: 'ghs_noexpiry' } }]);
    expect(await getInstallationToken(f.impl)).toBe('ghs_noexpiry');
    expect(installationTokenState().expiresAt).toBeGreaterThan(Date.now());
  });
});

// ------------------------------------------------------------------ failures

describe('failure handling — a GitHub outage must not 500 a page render', () => {
  it('returns null instead of throwing when GitHub rejects the App JWT', async () => {
    configureApp();
    const f = mintingFetch([{ status: 401, body: { message: 'Bad credentials' } }]);
    await expect(getInstallationToken(f.impl)).resolves.toBeNull();
  });

  it('returns null instead of throwing when the installation is gone', async () => {
    configureApp();
    const f = mintingFetch([{ status: 404, body: { message: 'Not Found' } }]);
    await expect(getInstallationToken(f.impl)).resolves.toBeNull();
  });

  it('returns null instead of throwing when the network is down', async () => {
    configureApp();
    const impl = (async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    await expect(getInstallationToken(impl)).resolves.toBeNull();
  });

  it('returns null when the response is not JSON', async () => {
    configureApp();
    const impl = (async () =>
      new Response('<html>502</html>', { status: 200 })) as unknown as typeof fetch;
    await expect(getInstallationToken(impl)).resolves.toBeNull();
  });

  it('does not cache a failure — the next call retries', async () => {
    configureApp();
    const f = mintingFetch([
      { status: 500, body: { message: 'server error' } },
      { token: 'ghs_recovered' },
    ]);
    expect(await getInstallationToken(f.impl)).toBeNull();
    expect(await getInstallationToken(f.impl)).toBe('ghs_recovered');
  });

  it('serves a still-valid cached token even if a later refresh attempt fails', async () => {
    configureApp();
    // First mint succeeds with a token inside the renewal margin, so the second
    // call tries to renew; the renewal fails, but the old token is still valid.
    const f = mintingFetch([
      { token: 'ghs_old', expiresAt: inSeconds(45) },
      { status: 500, body: { message: 'nope' } },
    ]);
    expect(await getInstallationToken(f.impl)).toBe('ghs_old');
    expect(await getInstallationToken(f.impl)).toBe('ghs_old');
  });
});

// ------------------------------------------------------------------- secrecy

describe('secrecy — no credential material is ever written to a log', () => {
  it('logs nothing containing the private key or the minted token, on success or failure', async () => {
    configureApp();
    const written: string[] = [];
    for (const level of ['log', 'info', 'warn', 'error', 'debug'] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
        written.push(args.map((a) => (a instanceof Error ? a.stack ?? a.message : String(a))).join(' '));
      });
    }

    const ok = mintingFetch([{ token: 'ghs_supersecret' }]);
    await getInstallationToken(ok.impl);
    resetInstallationTokenCache();
    const bad = mintingFetch([{ status: 401, body: { message: 'Bad credentials' } }]);
    await getInstallationToken(bad.impl);
    resetInstallationTokenCache();
    const boom = (async () => {
      throw new Error(`connect failed while using ${PKCS1}`);
    }) as unknown as typeof fetch;
    await getInstallationToken(boom);

    const all = written.join('\n');
    expect(all).not.toContain('ghs_supersecret');
    expect(all).not.toContain('PRIVATE KEY');
    expect(all).not.toContain(PKCS1.split('\n')[1]);
  });

  it('never puts the private key into the error message it returns', async () => {
    configureApp('-----BEGIN RSA PRIVATE KEY-----\nnot-really-base64\n-----END RSA PRIVATE KEY-----');
    const f = mintingFetch([{}]);
    // A key that parses as a PEM shape but is not a usable key: minting must
    // fail closed, not surface the material.
    await expect(getInstallationToken(f.impl)).resolves.toBeNull();
  });
});
