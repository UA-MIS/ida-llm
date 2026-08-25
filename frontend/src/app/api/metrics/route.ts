import { collectDefaultMetrics, register } from "prom-client";

/**
 * Prometheus exposition for the frontend.
 *
 * Traefik already gives us request/latency/error rates for this host
 * (`traefik_service_*`), and that is what the Grafana dashboard's golden-signal
 * panels use. What Traefik CANNOT see is what is happening INSIDE the Node
 * process -- event-loop lag, heap growth, handle counts -- which is exactly the
 * class of problem that makes a Next.js pod slow without making it fail. That is
 * what this endpoint adds.
 *
 * `force-dynamic` matters: without it Next would statically prerender this at
 * build time and every scrape would return the same frozen numbers.
 *
 * No Ingress rule points here, so it is reachable only from inside the namespace
 * and from `monitoring` (which the tenant netpol explicitly allows).
 */
export const dynamic = "force-dynamic";

// collectDefaultMetrics registers into the default registry and THROWS if called
// twice with the same prefix. In dev, Next re-evaluates route modules on every
// edit, so this guard is what keeps a hot reload from crashing the route.
declare global {
  var __idaMetricsStarted: boolean | undefined;
}
if (!globalThis.__idaMetricsStarted) {
  collectDefaultMetrics({ prefix: "ida_llm_frontend_" });
  globalThis.__idaMetricsStarted = true;
}

export async function GET() {
  return new Response(await register.metrics(), {
    status: 200,
    headers: { "Content-Type": register.contentType },
  });
}
