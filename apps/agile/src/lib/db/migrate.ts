import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import type { PoolClient } from 'pg';
import { getPool } from './pool';
import { config } from '@/lib/env';

const MIGRATIONS_DIR = path.join(process.cwd(), 'src', 'lib', 'db', 'migrations');

/**
 * Applies every pending migration inside the app's dedicated schema.
 *
 * Idempotent: safe to run on every boot and safe to run concurrently from
 * multiple replicas — an advisory lock serialises them and each migration is
 * recorded in schema_migrations so it is applied at most once.
 */
export async function runMigrations(dir: string = MIGRATIONS_DIR): Promise<string[]> {
  const schema = config.dbSchema;
  const pool = getPool();
  const client: PoolClient = await pool.connect();
  const applied: string[] = [];

  try {
    // Create the schema first; search_path alone does not create it.
    await client.query(`CREATE SCHEMA IF NOT EXISTS ${schema}`);
    await client.query(`SET search_path TO ${schema}, public`);
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version     TEXT PRIMARY KEY,
        applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
      )
    `);

    // Serialise concurrent migrators (multiple pods starting at once).
    await client.query('SELECT pg_advisory_lock($1)', [hashLockKey(schema)]);

    try {
      const files = (await readdir(dir)).filter((f) => f.endsWith('.sql')).sort();
      const { rows } = await client.query<{ version: string }>(
        'SELECT version FROM schema_migrations',
      );
      const done = new Set(rows.map((r) => r.version));

      for (const file of files) {
        if (done.has(file)) continue;
        const sql = await readFile(path.join(dir, file), 'utf8');
        await client.query('BEGIN');
        try {
          // Which board this deploy is. Data-repair migrations need it for the
          // same reason every runtime query does: `instance_key` scopes a row to
          // one board, and a migration that ignores it edits rows it does not
          // own. Exposed as a GUC because a .sql file takes no parameters.
          // is_local = true: scoped to THIS transaction, so it cannot leak to
          // the next migration file, nor back into the pool on a connection
          // this runner borrowed.
          await client.query('SELECT set_config($1, $2, true)', [
            'ida_agile.instance_key',
            config.instanceKey,
          ]);
          await client.query(sql);
          await client.query('INSERT INTO schema_migrations (version) VALUES ($1)', [file]);
          await client.query('COMMIT');
          applied.push(file);
          console.log(`[migrate] applied ${file}`);
        } catch (err) {
          await client.query('ROLLBACK');
          throw new Error(`Migration ${file} failed: ${(err as Error).message}`, { cause: err });
        }
      }
    } finally {
      await client.query('SELECT pg_advisory_unlock($1)', [hashLockKey(schema)]);
    }
  } finally {
    client.release();
  }

  return applied;
}

/** Stable 32-bit advisory-lock key derived from the schema name. */
function hashLockKey(schema: string): number {
  let h = 2166136261;
  for (let i = 0; i < schema.length; i++) {
    h ^= schema.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  // Keep it inside int4 range, which pg_advisory_lock(int) requires.
  return h | 0;
}
