import { query, queryOne } from '@/lib/db/pool';
import { config } from '@/lib/env';
import { sha256Hex } from '@/lib/crypto';

/**
 * Idempotent creates.
 *
 * A client (or an agent retrying a timed-out call) may send
 * `Idempotency-Key: <key>`. The first request's response is stored and replayed
 * verbatim for any retry with the same key, so a retry never duplicates work.
 * Reusing a key with a *different* body is a conflict, not a silent overwrite.
 *
 * Records live in Postgres, so replay survives a pod restart.
 */
export interface Replay {
  status: number;
  body: string;
}

export async function lookupIdempotent(
  key: string,
  ownerLogin: string,
  requestBody: unknown,
): Promise<{ kind: 'miss' } | { kind: 'replay'; replay: Replay } | { kind: 'conflict' }> {
  const hash = sha256Hex(JSON.stringify(requestBody ?? null));
  const row = await queryOne<{ request_hash: string; response_body: string; status_code: number }>(
    `SELECT request_hash, response_body, status_code
       FROM idempotency_keys
      WHERE instance_key = $1 AND owner_login = $2 AND idem_key = $3`,
    [config.instanceKey, ownerLogin, key],
  );
  if (!row) return { kind: 'miss' };
  if (row.request_hash !== hash) return { kind: 'conflict' };
  return { kind: 'replay', replay: { status: row.status_code, body: row.response_body } };
}

export async function saveIdempotent(
  key: string,
  ownerLogin: string,
  requestBody: unknown,
  status: number,
  responseBody: unknown,
): Promise<void> {
  await query(
    `INSERT INTO idempotency_keys
       (instance_key, idem_key, owner_login, request_hash, response_body, status_code)
     VALUES ($1,$2,$3,$4,$5,$6)
     ON CONFLICT (instance_key, owner_login, idem_key) DO NOTHING`,
    [
      config.instanceKey,
      key,
      ownerLogin,
      sha256Hex(JSON.stringify(requestBody ?? null)),
      JSON.stringify(responseBody),
      status,
    ],
  );
}

/** Housekeeping so the table cannot grow without bound. */
export async function purgeOldIdempotencyKeys(olderThanDays = 7): Promise<number> {
  const rows = await query<{ id: number }>(
    `DELETE FROM idempotency_keys WHERE created_at < now() - ($1 || ' days')::interval RETURNING id`,
    [String(olderThanDays)],
  );
  return rows.length;
}
