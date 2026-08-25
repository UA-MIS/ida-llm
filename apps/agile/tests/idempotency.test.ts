import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';

const SCHEMA = 'agile_idem_test';
installTestEnv(SCHEMA);
const d = hasDb ? describe : describe.skip;

d('idempotent creates (real Postgres)', () => {
  let db: typeof import('@/lib/db/pool');
  let idem: typeof import('@/lib/api/idempotency');

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();
    idem = await import('@/lib/api/idempotency');
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  const body = { title: 'Seeded story' };

  it('misses on a key it has never seen', async () => {
    expect(await idem.lookupIdempotent('key-1', 'alice', body)).toEqual({ kind: 'miss' });
  });

  it('replays the original response for a repeated key and body', async () => {
    await idem.saveIdempotent('key-2', 'alice', body, 201, { item: { id: 7 } });
    const found = await idem.lookupIdempotent('key-2', 'alice', body);

    expect(found.kind).toBe('replay');
    if (found.kind !== 'replay') throw new Error('expected a replay');
    expect(found.replay.status).toBe(201);
    expect(JSON.parse(found.replay.body)).toEqual({ item: { id: 7 } });
  });

  it('CONFLICTS when the same key is reused with a different body', async () => {
    await idem.saveIdempotent('key-3', 'alice', body, 201, { item: { id: 8 } });
    expect(await idem.lookupIdempotent('key-3', 'alice', { title: 'Something else' })).toEqual({
      kind: 'conflict',
    });
  });

  it('scopes keys per user, so two people may use the same key', async () => {
    await idem.saveIdempotent('shared-key', 'alice', body, 201, { item: { id: 9 } });
    expect(await idem.lookupIdempotent('shared-key', 'bob', body)).toEqual({ kind: 'miss' });
  });

  it('distinguishes an identical body from a merely similar one', async () => {
    await idem.saveIdempotent('key-4', 'alice', { a: 1, b: 2 }, 201, { ok: true });
    expect((await idem.lookupIdempotent('key-4', 'alice', { a: 1, b: 2 })).kind).toBe('replay');
    expect((await idem.lookupIdempotent('key-4', 'alice', { a: 1, b: 3 })).kind).toBe('conflict');
  });

  it('does not overwrite an existing record if saved twice', async () => {
    await idem.saveIdempotent('key-5', 'alice', body, 201, { item: { id: 10 } });
    await idem.saveIdempotent('key-5', 'alice', body, 500, { error: 'nope' });

    const found = await idem.lookupIdempotent('key-5', 'alice', body);
    if (found.kind !== 'replay') throw new Error('expected a replay');
    expect(found.replay.status).toBe(201);
    expect(JSON.parse(found.replay.body)).toEqual({ item: { id: 10 } });
  });

  it('purges old keys so the table cannot grow without bound', async () => {
    await idem.saveIdempotent('old-key', 'alice', body, 201, {});
    await db.query("UPDATE idempotency_keys SET created_at = now() - interval '30 days'");

    expect(await idem.purgeOldIdempotencyKeys(7)).toBeGreaterThan(0);
    expect(await idem.lookupIdempotent('old-key', 'alice', body)).toEqual({ kind: 'miss' });
  });
});
