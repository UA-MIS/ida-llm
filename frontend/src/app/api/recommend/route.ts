import { ApiError, postRecommendation } from "@/lib/api";

/**
 * Same-origin proxy for the recommendation intake.
 *
 * The browser cannot call the api directly — it has no Ingress in any
 * environment — so the wizard posts here, on the frontend's own origin, and
 * this handler (server-side, inside the namespace) forwards to `API_URL`. Same
 * reasoning as the transcript proxy; see src/lib/api.ts for why there is no
 * NEXT_PUBLIC_API_BASE_URL anywhere in this codebase.
 *
 * Why the intake posts at all rather than being fully server-rendered: the
 * question tree is adaptive, and a professor answering "yes, student work is
 * involved" must see the FERPA branch open immediately. A round trip per answer
 * would make an already-long form feel slow, which is precisely the failure
 * mode the adaptive design exists to avoid.
 *
 * `force-dynamic`: without it Next would prerender this and every professor
 * would get one frozen recommendation.
 */
export const dynamic = "force-dynamic";

/** Cap the payload. The intake is a dozen short enumerated answers; anything
 *  larger is not a professor filling in a form. */
const MAX_ANSWERS = 64;
const MAX_VALUE_LENGTH = 256;

export async function POST(request: Request) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return Response.json({ error: "Body must be JSON." }, { status: 400 });
  }

  const answers = (payload as { answers?: unknown })?.answers;
  if (answers === null || typeof answers !== "object" || Array.isArray(answers)) {
    return Response.json(
      { error: "Expected { answers: { [questionId]: string } }." },
      { status: 400 },
    );
  }

  const entries = Object.entries(answers as Record<string, unknown>);
  if (entries.length > MAX_ANSWERS) {
    return Response.json({ error: "Too many answers." }, { status: 400 });
  }
  // Values are forwarded, not trusted: the api rejects any value that is not an
  // option of its question. This only keeps obvious junk off the wire.
  const clean: Record<string, string> = {};
  for (const [key, value] of entries) {
    if (typeof value !== "string" || value.length > MAX_VALUE_LENGTH) {
      return Response.json(
        { error: `Answer for ${key} must be a short string.` },
        { status: 400 },
      );
    }
    clean[key] = value;
  }

  try {
    return Response.json(await postRecommendation(clean));
  } catch (cause) {
    if (cause instanceof ApiError) {
      // Status 0 means we never reached the api, which IS a 502 from here.
      const status = cause.status === 0 ? 502 : cause.status;
      return Response.json({ error: cause.message }, { status });
    }
    throw cause;
  }
}
