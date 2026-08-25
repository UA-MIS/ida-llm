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

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ runId: string; sampleId: string }> },
) {
  const { runId, sampleId } = await params;

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
