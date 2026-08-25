import { getPool } from '@/lib/db/pool';
import { schemaReady } from '@/lib/bootstrap';

export const dynamic = 'force-dynamic';

/**
 * READINESS. Reports whether this pod can actually serve traffic: the database
 * must be reachable and migrations must have completed. Unauthenticated on
 * purpose — it exposes no data.
 */
export async function GET() {
  if (!schemaReady()) {
    return Response.json({ status: 'starting', schema: 'pending' }, { status: 503 });
  }
  try {
    await getPool().query('SELECT 1');
    return Response.json({ status: 'ready' });
  } catch {
    return Response.json({ status: 'degraded', database: 'unreachable' }, { status: 503 });
  }
}
