import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { hasDb, installTestEnv } from './helpers/db';
import { parseNonNegativeInt } from '@/lib/api/respond';

const SCHEMA = 'agile_query_params_test';
installTestEnv(SCHEMA);
const d = hasDb ? describe : describe.skip;

/**
 * Review finding M-1 — hostile query parameters must not 500.
 *
 * `Number('abc')` is NaN and `typeof NaN === 'number'`, so an unguarded
 * `Number()` slips past every downstream `!== undefined` / `typeof` check and
 * arrives at Postgres as a bind parameter. Three entry points carried the
 * pattern and all three were confirmed live 500s:
 *
 *   GET /api/v1/items?sprintId=abc  -> invalid input syntax for type integer: "NaN"
 *   GET /api/v1/ready?sprintId=abc  -> invalid input syntax for type integer: "NaN"
 *   GET /api/v1/items?limit=abc     -> invalid input syntax for type bigint:  "NaN"
 *
 * (`offset=abc` happened to survive only because `if (filters.offset)` treats
 * NaN as falsy — an accident, not a guard, so it is pinned here too.)
 *
 * These call the REAL route handlers through `withApi`, so authentication,
 * rate limiting and the catch-all error wrapper are all in the path.
 */

const HOSTILE = [
  'abc',
  'NaN',
  'Infinity',
  '-Infinity',
  '1.5',
  '-1',
  'null',
  'undefined',
  '[]',
  '{}',
  'true',
  '1; DROP TABLE work_items',
  '1e999',
  ' ',
  '0x10',
];

describe('parseNonNegativeInt (M-1)', () => {
  it('reads a usable non-negative integer', () => {
    expect(parseNonNegativeInt('0')).toBe(0);
    expect(parseNonNegativeInt('1')).toBe(1);
    expect(parseNonNegativeInt('500')).toBe(500);
    expect(parseNonNegativeInt(' 7 ')).toBe(7);
  });

  it('treats absent or empty as no filter', () => {
    expect(parseNonNegativeInt(null)).toBeUndefined();
    expect(parseNonNegativeInt(undefined)).toBeUndefined();
    expect(parseNonNegativeInt('')).toBeUndefined();
    expect(parseNonNegativeInt('   ')).toBeUndefined();
  });

  it('degrades every hostile value to no filter, never NaN', () => {
    for (const raw of HOSTILE) {
      const parsed = parseNonNegativeInt(raw);
      expect(parsed === undefined || Number.isInteger(parsed), `${JSON.stringify(raw)}`).toBe(true);
      expect(Number.isNaN(parsed as number), `${JSON.stringify(raw)} produced NaN`).toBe(false);
    }
  });

  it('rejects negatives — offset must never go backwards', () => {
    expect(parseNonNegativeInt('-1')).toBeUndefined();
    expect(parseNonNegativeInt('-500')).toBeUndefined();
  });
});

d('hostile query parameters on the real API routes (M-1)', () => {
  let db: typeof import('@/lib/db/pool');
  let token: string;
  let sprintId: number;

  async function get(path: string): Promise<Response> {
    const route = await import('@/app/api/v1/items/route');
    return route.GET(
      new Request(`http://localhost${path}`, { headers: { authorization: `Bearer ${token}` } }),
    );
  }

  async function getReady(path: string): Promise<Response> {
    const route = await import('@/app/api/v1/ready/route');
    return route.GET(
      new Request(`http://localhost${path}`, { headers: { authorization: `Bearer ${token}` } }),
    );
  }

  beforeAll(async () => {
    db = await import('@/lib/db/pool');
    await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);
    await (await import('@/lib/db/migrate')).runMigrations();

    const q = await import('@/lib/domain/queries');
    const sprint = await q.createSprint({
      name: 'Sprint 1',
      goal: '',
      startsOn: '2026-08-01',
      endsOn: '2026-08-14',
      position: 0,
    });
    sprintId = sprint.id;
    await q.createWorkItem({ title: 'In the sprint', sprintId }, 'tester');
    await q.createWorkItem({ title: 'In the backlog' }, 'tester');

    token = (await (await import('@/lib/auth/tokens')).createApiToken({
      name: 'query-param-test',
      ownerLogin: 'tester',
    })).token;
  });

  afterAll(async () => {
    if (db) {
      await db.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`).catch(() => {});
      await db.closePool();
    }
  });

  it.each(HOSTILE)('GET /items?sprintId=%j does not 500', async (raw) => {
    const res = await get(`/api/v1/items?sprintId=${encodeURIComponent(raw)}`);
    expect(res.status).toBe(200);
  });

  it.each(HOSTILE)('GET /ready?sprintId=%j does not 500', async (raw) => {
    const res = await getReady(`/api/v1/ready?sprintId=${encodeURIComponent(raw)}`);
    expect(res.status).toBe(200);
  });

  it.each(HOSTILE)('GET /items?limit=%j does not 500', async (raw) => {
    const res = await get(`/api/v1/items?limit=${encodeURIComponent(raw)}`);
    expect(res.status).toBe(200);
  });

  it.each(HOSTILE)('GET /items?offset=%j does not 500', async (raw) => {
    const res = await get(`/api/v1/items?offset=${encodeURIComponent(raw)}`);
    expect(res.status).toBe(200);
  });

  // ---------------------------------------------------------------- behaviour

  it('an unusable sprintId degrades to "all sprints", not to an empty result', async () => {
    const res = await get('/api/v1/items?sprintId=abc');
    const body = (await res.json()) as { count: number };
    expect(body.count).toBe(2);
  });

  it('still filters by a real sprint id', async () => {
    const body = (await (await get(`/api/v1/items?sprintId=${sprintId}`)).json()) as {
      items: Array<{ title: string }>;
    };
    expect(body.items).toHaveLength(1);
    expect(body.items[0]!.title).toBe('In the sprint');
  });

  it('still supports the "none" and "all" sentinels', async () => {
    const none = (await (await get('/api/v1/items?sprintId=none')).json()) as {
      items: Array<{ title: string }>;
    };
    expect(none.items).toHaveLength(1);
    expect(none.items[0]!.title).toBe('In the backlog');

    const all = (await (await get('/api/v1/items?sprintId=all')).json()) as { count: number };
    expect(all.count).toBe(2);
  });

  it('still honours a usable limit', async () => {
    const body = (await (await get('/api/v1/items?limit=1')).json()) as { count: number };
    expect(body.count).toBe(1);
  });

  it('an unusable limit returns the full page rather than erroring', async () => {
    const body = (await (await get('/api/v1/items?limit=abc')).json()) as { count: number };
    expect(body.count).toBe(2);
  });

  it('still honours a usable offset', async () => {
    const body = (await (await get('/api/v1/items?offset=1')).json()) as { count: number };
    expect(body.count).toBe(1);
  });

  it('the ready queue still returns its shape under a hostile sprintId', async () => {
    const body = (await (await getReady('/api/v1/ready?sprintId=abc')).json()) as {
      ready: unknown[];
      blocked: unknown[];
      count: number;
    };
    expect(Array.isArray(body.ready)).toBe(true);
    expect(Array.isArray(body.blocked)).toBe(true);
    expect(body.count).toBe(2);
  });
});
