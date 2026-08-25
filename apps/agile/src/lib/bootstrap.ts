import { runMigrations } from '@/lib/db/migrate';

/**
 * Migrations run once per process, before traffic is served.
 *
 * A fresh pod against an EMPTY database self-initialises; a fresh pod against an
 * existing database applies only what is missing. Concurrent replicas are safe:
 * the runner takes a Postgres advisory lock.
 */
let started: Promise<void> | null = null;

export function ensureSchema(): Promise<void> {
  if (!started) {
    started = runMigrations()
      .then(() => undefined)
      .catch((err) => {
        // Reset so the next request retries rather than caching the failure.
        started = null;
        throw err;
      });
  }
  return started;
}
