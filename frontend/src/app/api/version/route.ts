/**
 * What is actually deployed here — readable without SSH.
 *
 * WHY THIS EXISTS. On the GB10 appliance the images are built on the box from
 * the reconciled commit instead of being pulled as promoted Harbor digests
 * (aarch64 box, amd64-only promoted images). A registry digest used to answer
 * "what is running"; this endpoint replaces that property rather than dropping
 * it. It is the only published surface on the box — the api is bound to
 * loopback in every environment — so it is the one place the question can be
 * asked from outside.
 *
 * ⚠ DELIBERATELY NOT PART OF /api/healthz. healthz is the LIVENESS path, probed
 * every 10s, and this route does network I/O. Folding the two together would
 * make a brief api blip restart the frontend — the same mistake the api's own
 * split between /healthz (no DB) and /readyz (DB) exists to avoid.
 *
 * `force-dynamic` is load-bearing: without it Next prerenders this at BUILD
 * time and it answers from cache forever, which for a "what is deployed"
 * endpoint is worse than having no endpoint at all — it would confidently
 * report the version it was built at no matter what is running.
 */
import { buildDeployedIdentity, resolveVersion } from "@/lib/version";

export const dynamic = "force-dynamic";

/** Short, because this is an ops endpoint and a hung api must not hang it. */
const API_TIMEOUT_MS = 2000;

export async function GET() {
  const frontend = resolveVersion();
  const base = (process.env.API_URL ?? "").replace(/\/+$/, "");

  if (!base) {
    return Response.json(
      buildDeployedIdentity(frontend, null, "API_URL is not set in this container"),
      { status: 200 },
    );
  }

  try {
    const res = await fetch(`${base}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
    if (!res.ok) {
      return Response.json(
        buildDeployedIdentity(frontend, null, `api /healthz returned HTTP ${res.status}`),
        { status: 200 },
      );
    }
    return Response.json(buildDeployedIdentity(frontend, await res.json()), { status: 200 });
  } catch (e) {
    // Returns 200 with `reachable: false` rather than failing: the question
    // "what is deployed" still has a useful partial answer (this frontend's own
    // build) when the api is down, and that is exactly when it gets asked.
    return Response.json(
      buildDeployedIdentity(frontend, null, e instanceof Error ? e.message : String(e)),
      { status: 200 },
    );
  }
}
