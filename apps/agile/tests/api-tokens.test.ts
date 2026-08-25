import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_tokens_test';
installTestEnv(SCHEMA);

const d = hasDb ? describe : describe.skip;

d('API tokens (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let tokens: typeof import('@/lib/auth/tokens');

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();
    tokens = await import('@/lib/auth/tokens');
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  it('issues a token that authenticates as its owner', async () => {
    const { token, record } = await tokens.createApiToken({ name: 'agent', ownerLogin: 'alice' });
    expect(token.startsWith('iag_')).toBe(true);
    expect(record.ownerLogin).toBe('alice');

    const verdict = await tokens.verifyApiToken(token);
    expect(verdict).toMatchObject({ ok: true, ownerLogin: 'alice' });
  });

  it('NEVER stores the token itself — only a hash', async () => {
    const { token } = await tokens.createApiToken({ name: 'secret-check', ownerLogin: 'bob' });
    const rows = await db.query<{ token_hash: string; token_prefix: string }>(
      'SELECT token_hash, token_prefix FROM api_tokens WHERE owner_login = $1',
      ['bob'],
    );
    for (const row of rows) {
      expect(row.token_hash).not.toBe(token);
      expect(row.token_hash).toMatch(/^[0-9a-f]{64}$/);
      // The stored prefix is a non-secret fragment used only for display.
      expect(token.startsWith(row.token_prefix)).toBe(true);
    }
    // The full value appears nowhere in the row.
    const dump = await db.query<Record<string, unknown>>(
      'SELECT * FROM api_tokens WHERE owner_login = $1',
      ['bob'],
    );
    expect(JSON.stringify(dump)).not.toContain(token.slice(10));
  });

  it('REJECTS a revoked token', async () => {
    const { token, record } = await tokens.createApiToken({ name: 'to-revoke', ownerLogin: 'carol' });
    expect((await tokens.verifyApiToken(token)).ok).toBe(true);

    expect(await tokens.revokeApiToken(record.id, 'carol')).toBe(true);
    expect(await tokens.verifyApiToken(token)).toEqual({ ok: false, reason: 'revoked' });
  });

  it('does not let one user revoke another user\'s token', async () => {
    const { token, record } = await tokens.createApiToken({ name: 'mine', ownerLogin: 'dave' });
    expect(await tokens.revokeApiToken(record.id, 'mallory')).toBe(false);
    // ...and it still works for its real owner.
    expect((await tokens.verifyApiToken(token)).ok).toBe(true);
  });

  it('REJECTS an expired token', async () => {
    const { token, record } = await tokens.createApiToken({ name: 'short', ownerLogin: 'erin' });
    await db.query('UPDATE api_tokens SET expires_at = now() - interval \'1 hour\' WHERE id = $1', [
      record.id,
    ]);
    expect(await tokens.verifyApiToken(token)).toEqual({ ok: false, reason: 'expired' });
  });

  it.each(['', 'not-a-token', 'Bearer iag_x', 'iag_', 'iag_short'])(
    'REJECTS malformed token %j',
    async (bad) => {
      expect(await tokens.verifyApiToken(bad)).toEqual({ ok: false, reason: 'malformed' });
    },
  );

  it('REJECTS a well-formed token that was never issued', async () => {
    const fake = `iag_${'z'.repeat(43)}`;
    expect(await tokens.verifyApiToken(fake)).toEqual({ ok: false, reason: 'unknown' });
  });

  it('lists only the caller\'s own tokens and never their secret value', async () => {
    const { token } = await tokens.createApiToken({ name: 'frank-1', ownerLogin: 'frank' });
    const mine = await tokens.listApiTokens('frank');

    expect(mine.length).toBeGreaterThan(0);
    expect(mine.every((t) => t.ownerLogin === 'frank')).toBe(true);

    // The short prefix IS shown deliberately (it is how a user tells tokens
    // apart); the secret remainder must never appear.
    const secretPart = token.slice('iag_'.length + 6);
    expect(secretPart.length).toBeGreaterThan(20);
    expect(JSON.stringify(mine)).not.toContain(secretPart);
    expect(JSON.stringify(mine)).not.toContain(token);

    expect(await tokens.listApiTokens('nobody-here')).toEqual([]);
  });

  it('records last_used_at when a token authenticates', async () => {
    const { token, record } = await tokens.createApiToken({ name: 'used', ownerLogin: 'grace' });
    expect((await tokens.listApiTokens('grace')).find((t) => t.id === record.id)?.lastUsedAt).toBeNull();
    await tokens.verifyApiToken(token);
    const after = (await tokens.listApiTokens('grace')).find((t) => t.id === record.id);
    expect(after?.lastUsedAt).not.toBeNull();
  });

  it('REVOKES a token whose owner has left the team', async () => {
    // A stored GitHub token lets membership be re-checked on every API call.
    const { token } = await tokens.createApiToken({
      name: 'ex-member',
      ownerLogin: 'departed',
      githubToken: 'gho_stored',
    });

    const realFetch = globalThis.fetch;
    // GitHub reports "not a member".
    globalThis.fetch = (async () => new Response('{}', { status: 404 })) as typeof fetch;
    try {
      expect(await tokens.verifyApiToken(token)).toEqual({ ok: false, reason: 'not-on-team' });
      // The token is retired, not merely refused this once.
      const rows = await db.query<{ revoked_at: Date | null }>(
        'SELECT revoked_at FROM api_tokens WHERE owner_login = $1',
        ['departed'],
      );
      expect(rows[0]?.revoked_at).not.toBeNull();
    } finally {
      globalThis.fetch = realFetch;
    }
  });

  it('keeps working through a transient GitHub outage', async () => {
    const { token } = await tokens.createApiToken({
      name: 'flaky-github',
      ownerLogin: 'steady',
      githubToken: 'gho_stored',
    });
    const realFetch = globalThis.fetch;
    globalThis.fetch = (async () => new Response('boom', { status: 500 })) as typeof fetch;
    try {
      expect((await tokens.verifyApiToken(token)).ok).toBe(true);
    } finally {
      globalThis.fetch = realFetch;
    }
  });
});
