import {
  createCipheriv,
  createDecipheriv,
  createHmac,
  hkdfSync,
  randomBytes,
  timingSafeEqual,
} from 'node:crypto';

/**
 * Sessions live in an HTTP-only cookie that is *encrypted and authenticated*
 * (AES-256-GCM), not merely signed.
 *
 * Encryption is required rather than optional here: the session carries the
 * user's GitHub OAuth access token, which the app replays to list team members
 * and read pull requests. A signed-but-readable cookie would hand that token
 * to anyone who could read the cookie jar. GCM also authenticates, so tampering
 * is detected without a separate HMAC.
 */
export const SESSION_COOKIE = 'ida_agile_session';
export const OAUTH_STATE_COOKIE = 'ida_agile_oauth_state';

/** 7 days. */
export const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;

const KEY_INFO = 'ida-agile-session-v1';
const IV_BYTES = 12;
const TAG_BYTES = 16;

export interface SessionPayload {
  /** GitHub login of the authenticated, team-verified user. */
  login: string;
  name: string;
  avatarUrl: string;
  /**
   * Upstream GitHub token, when the provider supplies one. Empty for OIDC,
   * where the board never receives a GitHub credential.
   */
  token: string;
  /** Groups asserted at sign-in, e.g. ["UA-MIS:ida-llm"]. */
  groups: string[];
  /** Which provider issued this session. */
  provider: 'oidc' | 'github';
  /** Unix seconds. */
  exp: number;
}

function deriveKey(secret: string): Buffer {
  return Buffer.from(hkdfSync('sha256', Buffer.from(secret), Buffer.alloc(0), KEY_INFO, 32));
}

export function sealSession(
  payload: Omit<SessionPayload, 'exp' | 'groups' | 'provider'> & {
    exp?: number;
    groups?: string[];
    provider?: 'oidc' | 'github';
  },
  secret: string,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): string {
  const full: SessionPayload = {
    login: payload.login,
    name: payload.name,
    avatarUrl: payload.avatarUrl,
    token: payload.token,
    groups: payload.groups ?? [],
    provider: payload.provider ?? 'github',
    exp: payload.exp ?? nowSeconds + SESSION_TTL_SECONDS,
  };
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv('aes-256-gcm', deriveKey(secret), iv);
  const ct = Buffer.concat([cipher.update(JSON.stringify(full), 'utf8'), cipher.final()]);
  return Buffer.concat([iv, ct, cipher.getAuthTag()]).toString('base64url');
}

/**
 * Decrypts and validates. Returns null for anything suspicious — callers must
 * treat null as "not authenticated", never as "unknown user".
 */
export function unsealSession(
  token: string | undefined | null,
  secret: string,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): SessionPayload | null {
  if (!token) return null;

  let raw: Buffer;
  try {
    raw = Buffer.from(token, 'base64url');
  } catch {
    return null;
  }
  if (raw.length <= IV_BYTES + TAG_BYTES) return null;

  const iv = raw.subarray(0, IV_BYTES);
  const tag = raw.subarray(raw.length - TAG_BYTES);
  const ct = raw.subarray(IV_BYTES, raw.length - TAG_BYTES);

  let plaintext: string;
  try {
    const decipher = createDecipheriv('aes-256-gcm', deriveKey(secret), iv);
    decipher.setAuthTag(tag);
    plaintext = Buffer.concat([decipher.update(ct), decipher.final()]).toString('utf8');
  } catch {
    // Wrong key or tampered ciphertext.
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(plaintext);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null) return null;

  const p = parsed as Record<string, unknown>;
  if (
    typeof p.login !== 'string' ||
    typeof p.name !== 'string' ||
    typeof p.avatarUrl !== 'string' ||
    typeof p.token !== 'string' ||
    typeof p.exp !== 'number'
  ) {
    return null;
  }
  if (p.exp <= nowSeconds) return null;

  return {
    login: p.login,
    name: p.name,
    avatarUrl: p.avatarUrl,
    token: p.token,
    groups: Array.isArray(p.groups) ? p.groups.filter((g): g is string => typeof g === 'string') : [],
    provider: p.provider === 'oidc' ? 'oidc' : 'github',
    exp: p.exp,
  };
}

// ---------------------------------------------------------------------------
// OAuth CSRF state — signed only; it carries no secret material.
// ---------------------------------------------------------------------------

function sign(data: string, secret: string): string {
  return createHmac('sha256', secret).update(data).digest('base64url');
}

function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

export function createOAuthState(secret: string, returnTo = '/'): string {
  const nonce = randomBytes(16).toString('base64url');
  const body = Buffer.from(
    JSON.stringify({ nonce, returnTo: safeReturnTo(returnTo), exp: Math.floor(Date.now() / 1000) + 600 }),
  ).toString('base64url');
  return `${body}.${sign(body, secret)}`;
}

export function verifyOAuthState(
  token: string | undefined | null,
  secret: string,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): { returnTo: string } | null {
  if (!token) return null;
  const dot = token.lastIndexOf('.');
  if (dot <= 0) return null;
  const body = token.slice(0, dot);
  if (!safeEqual(token.slice(dot + 1), sign(body, secret))) return null;
  try {
    const parsed = JSON.parse(Buffer.from(body, 'base64url').toString('utf8')) as {
      returnTo?: unknown;
      exp?: unknown;
    };
    if (typeof parsed.exp !== 'number' || parsed.exp <= nowSeconds) return null;
    return { returnTo: safeReturnTo(parsed.returnTo) };
  } catch {
    return null;
  }
}

/**
 * Only same-origin, path-absolute redirects are allowed.
 *
 * `//evil.com` and `/\evil.com` are protocol-relative URLs that browsers
 * resolve to a *different origin*, so a naive `startsWith('/')` check is an
 * open redirect. Anything not provably local collapses to '/'.
 */
export function safeReturnTo(value: unknown): string {
  if (typeof value !== 'string') return '/';
  if (!value.startsWith('/')) return '/';
  if (value.startsWith('//') || value.startsWith('/\\')) return '/';
  return value;
}
