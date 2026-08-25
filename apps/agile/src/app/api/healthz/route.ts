export const dynamic = 'force-dynamic';

/**
 * LIVENESS. Deliberately does NOT touch the database.
 *
 * A liveness probe that depends on Postgres turns a brief database blip into a
 * cluster-wide restart storm. This answers only "is this process still able to
 * serve?"; database health belongs to /readyz.
 */
export async function GET() {
  return Response.json({ status: 'ok' });
}
