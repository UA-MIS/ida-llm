import { ApiError, getTranscript } from "@/lib/api";

/**
 * Same-origin proxy for the lazy transcript viewer.
 *
 * The transcript is the ONE thing this UI fetches from the browser rather than
 * on the server: a run can have hundreds of samples whose transcripts live in
 * object storage, so loading them all with the run detail would turn one page
 * view into hundreds of MinIO round trips.
 *
 * The browser cannot call the api directly -- it has no Ingress in any
 * environment -- so the request lands here instead, on the frontend's own
 * origin, and this handler (which runs server-side, inside the namespace)
 * forwards it to `API_URL`. No CORS, no public api hostname, and nothing about
 * the api's address baked into a client bundle that is promoted unchanged from
 * dev to prod.
 *
 * `force-dynamic`: without it Next would prerender this at build time and every
 * viewer would get one frozen transcript.
 */
export const dynamic = "force-dynamic";

/**
 * Reject path segments that are not really segments.
 *
 * ⚠ `encodeURIComponent` ENCODES `/` BUT NOT `.`, so a dot-segment survives
 * encoding and a URL parser then COLLAPSES it:
 *
 *   runId=".."                 ->  /api/results/{sampleId}/transcript
 *   sampleId=".."              ->  /api/runs/{runId}/transcript
 *   runId=".." & sampleId=".." ->  /api/transcript
 *
 * THIS GUARD IS A BACKSTOP, NOT A PATCH FOR A LIVE HOLE -- said plainly so the
 * next reader does not overrate it. Probed against the running app: Next
 * normalises dot-segments (raw AND `%2E`-encoded) before routing, so all four
 * shapes 404 at the router and never reach this function today. The host is
 * never attacker-influenced either (`API_URL` is server-side), so there is no
 * SSRF.
 *
 * It is here because the protection is entirely incidental -- it comes from the
 * router's normalisation and the fact that none of those collapsed shapes is a
 * real route. Add any endpoint ending in `/transcript`, restructure this path,
 * or serve this handler from anything other than Next, and the collapse becomes
 * a real traversal -- introduced by an edit somewhere else entirely, where
 * nobody is thinking about this file.
 *
 * Rejecting rather than re-encoding: a run id or sample id is an opaque token,
 * and `.`/`..`/empty are not values either one can legitimately take.
 */
function isUsableSegment(value: string): boolean {
  return value.length > 0 && value !== "." && value !== "..";
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ runId: string; sampleId: string }> },
) {
  const { runId, sampleId } = await params;

  if (!isUsableSegment(runId) || !isUsableSegment(sampleId)) {
    return Response.json(
      { error: "runId and sampleId must be non-empty and must not be path segments." },
      { status: 400 },
    );
  }

  try {
    return Response.json(await getTranscript(runId, sampleId));
  } catch (cause) {
    if (cause instanceof ApiError) {
      // The api's status is passed through -- a 404 for a sample that has no
      // archived transcript must not read as a proxy failure. Status 0 means we
      // never reached the api at all, which IS a 502 from the browser's view.
      const status = cause.status === 0 ? 502 : cause.status;
      return Response.json({ error: cause.message }, { status });
    }
    throw cause;
  }
}
