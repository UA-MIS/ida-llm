import { Pool, type PoolClient, type QueryResultRow } from 'pg';
import { config, assertSafeIdentifier } from '@/lib/env';

/**
 * A single pg Pool per process. Every connection is pinned to the app's own
 * schema via search_path, so unqualified table names in queries can never
 * touch the product's tables in the same database.
 */
let pool: Pool | undefined;

export function getPool(): Pool {
  if (!pool) {
    const schema = config.dbSchema;
    pool = new Pool({
      connectionString: config.databaseUrl,
      max: config.pgPoolMax,
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 10_000,
      // Applied to every new physical connection in the pool.
      options: `-c search_path=${schema},public`,
    });
    pool.on('error', (err) => {
      console.error('[db] idle client error', err);
    });
  }
  return pool;
}

export async function query<T extends QueryResultRow>(
  text: string,
  values: readonly unknown[] = [],
): Promise<T[]> {
  const result = await getPool().query<T>(text, values as unknown[]);
  return result.rows;
}

export async function queryOne<T extends QueryResultRow>(
  text: string,
  values: readonly unknown[] = [],
): Promise<T | null> {
  const rows = await query<T>(text, values);
  return rows[0] ?? null;
}

/** Run a set of statements in a single transaction. */
export async function withTransaction<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await getPool().connect();
  try {
    await client.query('BEGIN');
    const out = await fn(client);
    await client.query('COMMIT');
    return out;
  } catch (err) {
    try {
      await client.query('ROLLBACK');
    } catch (rollbackErr) {
      console.error('[db] rollback failed', rollbackErr);
    }
    throw err;
  } finally {
    client.release();
  }
}

export { assertSafeIdentifier };

export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = undefined;
  }
}
