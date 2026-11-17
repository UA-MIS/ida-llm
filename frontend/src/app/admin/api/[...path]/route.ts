import type { NextRequest } from "next/server";

import { adminFetch } from "@/lib/admin/api";
import { upstreamPath } from "@/lib/admin/bff-path";
import { adminEnv } from "@/lib/admin/env";
import { getActor, requireAdminForRoute } from "@/lib/admin/session";

/**
 * THE BFF: the one route through which the browser reaches the admin API.
 *
 * ⚠ SECURITY-TOUCHING, AND DELIBERATELY THE ONLY ONE (design AD-3). No
 * middleware, no Server Actions: every admin read a client component makes and
 * every admin write goes through these handlers, in this order:
 *
 *  1. console disabled                        → 404
 *  2. no session / not an admin               → 401 / 403 (JSON, the caller is fetch)
 *  3. non-GET: Origin must be exactly AUTH_URL's origin, and Content-Type
 *     must be JSON or multipart               → 403 / 415
 *  4. path: every segment re-encoded under `/admin/`; `..`, `.` and empty
 *     segments refused                        → 400
 *  5. forward ONLY content-type / if-match / accept from the browser. Its
 *     `cookie` and `authorization` NEVER reach the API. Add the admin bearer,
 *     the session's actor and a request id (`lib/admin/api.ts`).
 *  6. stream back status, body, content-type, etag, content-disposition, with
 *     `Cache-Control: no-store`.
 */
export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path?: string[] }> };

const FORWARD_REQUEST = ["content-type", "if-match", "accept"] as const;
const FORWARD_RESPONSE = ["content-type", "etag", "content-disposition"] as const;
const BODY_SLACK_BYTES = 64 * 1024;

function problem(status: number, code: string, message: string): Response {
  return Response.json({ detail: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

async function handle(request: NextRequest, ctx: Ctx): Promise<Response> {
  const admin = await requireAdminForRoute();
  if (admin instanceof Response) return admin;
  const env = adminEnv();
  const method = request.method.toUpperCase();
  const writes = method !== "GET" && method !== "HEAD";

  if (writes) {
    if (request.headers.get("origin") !== env.origin) {
      return problem(403, "forbidden", "This request did not come from the admin console.");
    }
    const type = (request.headers.get("content-type") ?? "").split(";")[0]!.trim().toLowerCase();
    if (type !== "application/json" && type !== "multipart/form-data") {
      return problem(415, "unsupported_media_type", "Send JSON or a file upload.");
    }
  }

  const path = upstreamPath((await ctx.params).path);
  if (!path) return problem(400, "bad_path", "That admin address is not valid.");

  const headers: Record<string, string> = {};
  for (const name of FORWARD_REQUEST) {
    const value = request.headers.get(name);
    if (value) headers[name] = value;
  }

  let body: ArrayBuffer | null = null;
  if (writes) {
    const cap = env.UPLOAD_MAX_BYTES + BODY_SLACK_BYTES;
    const declared = Number(request.headers.get("content-length") ?? "0");
    if (declared > cap) return problem(413, "too_large", "That file is too large.");
    body = await request.arrayBuffer();
    if (body.byteLength > cap) return problem(413, "too_large", "That file is too large.");
  }

  let upstream: Response;
  try {
    upstream = await adminFetch(path + request.nextUrl.search, { method, headers, body }, getActor(admin));
  } catch {
    return problem(502, "upstream_unavailable", "The admin service could not be reached. Try again in a minute.");
  }

  const out = new Headers({ "cache-control": "no-store" });
  for (const name of FORWARD_RESPONSE) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  const empty = upstream.status === 204 || upstream.status === 304 || method === "HEAD";
  return new Response(empty ? null : upstream.body, { status: upstream.status, headers: out });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
