/**
 * Liveness/readiness endpoint for the frontend.
 *
 * Next.js standalone serves no health route of its own, and the chart would
 * otherwise have to fall back to a bare TCP check -- which passes as soon as the
 * socket is open, i.e. before the app can actually render. This gives the probes
 * something that means "the Next server is serving", not just "a port is bound".
 *
 * `force-dynamic` matters: without it Next would statically prerender this at
 * build time and the route would answer from cache regardless of process state.
 */
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" });
}
