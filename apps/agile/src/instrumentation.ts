/**
 * Runs once per server process, before the first request is served.
 *
 * Migrations belong here rather than in a page: API routes are reachable
 * without ever rendering a page, so schema setup driven only by page loads
 * left `/api/*` querying tables that did not exist yet.
 */
export async function register(): Promise<void> {
  // Only the Node.js runtime can open a Postgres connection.
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;
  // Skip during `next build`, which imports the app without a live database.
  if (process.env.NEXT_PHASE === 'phase-production-build') return;

  const { ensureSchema } = await import('@/lib/bootstrap');
  try {
    await ensureSchema();
    console.log('[startup] database schema is up to date');
    const { startBackgroundPoller } = await import('@/lib/sync/poller');
    startBackgroundPoller();
  } catch (err) {
    // Do not crash the process: the pod should stay up and report a clear
    // error per request rather than crash-looping and hiding the cause.
    console.error('[startup] migrations failed; requests will retry', err);
  }
}
