import { describe, it, expect } from 'vitest';
import {
  sealSession,
  unsealSession,
  createOAuthState,
  verifyOAuthState,
  safeReturnTo,
  SESSION_TTL_SECONDS,
} from '@/lib/auth/session';

const SECRET = 'a'.repeat(48);
const OTHER_SECRET = 'b'.repeat(48);

const identity = {
  login: 'octocat',
  name: 'Mona Lisa',
  avatarUrl: 'https://avatars.githubusercontent.com/u/1?v=4',
  token: 'gho_supersecrettoken',
};

describe('session cookie', () => {
  it('round-trips an identity', () => {
    const cookie = sealSession(identity, SECRET);
    const out = unsealSession(cookie, SECRET);
    expect(out).toMatchObject(identity);
  });

  it('does NOT leak the GitHub token in the cookie text', () => {
    const cookie = sealSession(identity, SECRET);
    expect(cookie).not.toContain('gho_supersecrettoken');
    expect(cookie).not.toContain('octocat');
    // ...and the decoded bytes are ciphertext, not JSON.
    expect(Buffer.from(cookie, 'base64url').toString('utf8')).not.toContain('octocat');
  });

  it('rejects a cookie sealed with a different secret', () => {
    const cookie = sealSession(identity, OTHER_SECRET);
    expect(unsealSession(cookie, SECRET)).toBeNull();
  });

  it('rejects a tampered cookie', () => {
    const cookie = sealSession(identity, SECRET);
    const bytes = Buffer.from(cookie, 'base64url');
    const at = bytes.length - 20;
    bytes.writeUInt8(bytes.readUInt8(at) ^ 0xff, at); // flip bits inside the ciphertext
    expect(unsealSession(bytes.toString('base64url'), SECRET)).toBeNull();
  });

  it('rejects an expired cookie', () => {
    const now = 1_000_000;
    const cookie = sealSession({ ...identity, exp: now - 1 }, SECRET, now);
    expect(unsealSession(cookie, SECRET, now)).toBeNull();
  });

  it('accepts a cookie that is still within its TTL', () => {
    const now = 1_000_000;
    const cookie = sealSession(identity, SECRET, now);
    expect(unsealSession(cookie, SECRET, now + SESSION_TTL_SECONDS - 1)).not.toBeNull();
    expect(unsealSession(cookie, SECRET, now + SESSION_TTL_SECONDS + 1)).toBeNull();
  });

  it.each([undefined, null, '', 'garbage', 'a.b', '....'])(
    'rejects malformed cookie %j',
    (bad) => {
      expect(unsealSession(bad as string | undefined, SECRET)).toBeNull();
    },
  );
});

describe('oauth state', () => {
  it('round-trips and preserves a local returnTo', () => {
    const state = createOAuthState(SECRET, '/board?sprint=3');
    expect(verifyOAuthState(state, SECRET)).toEqual({ returnTo: '/board?sprint=3' });
  });

  it('rejects state signed with another secret', () => {
    expect(verifyOAuthState(createOAuthState(OTHER_SECRET), SECRET)).toBeNull();
  });

  it('rejects expired state', () => {
    const state = createOAuthState(SECRET);
    expect(verifyOAuthState(state, SECRET, Math.floor(Date.now() / 1000) + 601)).toBeNull();
  });
});

describe('safeReturnTo — open redirect protection', () => {
  it('keeps genuine local paths', () => {
    expect(safeReturnTo('/board')).toBe('/board');
    expect(safeReturnTo('/items/12?tab=prs')).toBe('/items/12?tab=prs');
  });

  it.each([
    '//evil.com',
    '//evil.com/path',
    '/\\evil.com',
    'https://evil.com',
    'http://evil.com',
    'javascript:alert(1)',
    '',
    'board',
  ])('collapses hostile returnTo %j to /', (bad) => {
    expect(safeReturnTo(bad)).toBe('/');
  });

  it('collapses non-strings to /', () => {
    expect(safeReturnTo(undefined)).toBe('/');
    expect(safeReturnTo({ toString: () => '/evil' })).toBe('/');
  });
});
