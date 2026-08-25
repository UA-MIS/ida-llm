import { getPool } from '@/lib/db/pool';
import { ensureSchema } from '@/lib/bootstrap';

export const dynamic = 'force-dynamic';

/**
 * READINESS: can this pod actually serve traffic?
 *
 * It deliberately does NOT consult an in-memory "migrations done" flag.
 * `instrumentation.ts` runs in a different module instance from route handlers
 * in a standalone build, so such a flag is never observed here and the pod
 * would report "starting" forever — the Deployment would never go Ready.
 *
 * Instead this awaits ensureSchema() directly. That call is memoised per module
 * instance and the migration runner is idempotent and advisory-locked, so after
 * the first request it is a no-op, and it is safe even if instrumentation
 * already ran the migrations.
 */
export async function GET() {
  try {
    await ensureSchema();
  } catch (err) {
    return Response.json(
      { status: 'starting', schema: 'pending', detail: (err as Error).message },
      { status: 503 },
    );
  }

  try {
    await getPool().query('SELECT 1');
    return Response.json({ status: 'ready' });
  } catch {
    return Response.json({ status: 'degraded', database: 'unreachable' }, { status: 503 });
  }
}
