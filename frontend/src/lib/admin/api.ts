import "server-only";

import { adminEnv } from "./env";
import type { AdminError } from "./types";

/**
 * The admin console's only door to the API.
 *
 * ⚠ THE BEARER NEVER LEAVES THIS PROCESS. It is read from env per call and
 * attached here, server-side; `server-only` makes importing this module from a
 * client component a build error, so it cannot be bundled for a browser.
 *
 * The API believes `X-IDA-Actor` only because the request also carries the
 * admin bearer (design AD-4). The actor is the Dex-verified GitHub login from
 * the session, never anything the browser sent.
 */

export interface Actor {
  login: string;
  sub?: string;
}

export const GITHUB_LOGIN = /^[A-Za-z0-9-]{1,39}$/;

export class AdminApiError extends Error {
  constructor(
    readonly status: number,
    readonly error: AdminError | null,
    message: string,
  ) {
    super(message);
    this.name = "AdminApiError";
  }
}

/** Raw fetch to `API_URL + path`, with the bearer and actor headers. `path` must be under `/admin/`. */
export async function adminFetch(
  path: string,
  init: { method?: string; headers?: Record<string, string>; body?: BodyInit | null; requestId?: string } = {},
  actor?: Actor,
): Promise<Response> {
  if (!path.startsWith("/admin/")) throw new Error(`adminFetch: refusing non-admin path ${path}`);
  const env = adminEnv();
  const headers: Record<string, string> = {
    accept: "application/json",
    ...init.headers,
    authorization: `Bearer ${env.ADMIN_TOKEN}`,
    "x-request-id": init.requestId ?? crypto.randomUUID(),
  };
  if (actor && GITHUB_LOGIN.test(actor.login)) {
    headers["x-ida-actor"] = actor.login;
    if (actor.sub) headers["x-ida-actor-sub"] = actor.sub;
  }
  return fetch(`${env.API_URL}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body ?? undefined,
    cache: "no-store",
  });
}

/** Parse the `{detail: {...}}` envelope (§5.1); `null` when the body is not one. */
export async function readAdminError(response: Response): Promise<AdminError | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "code" in detail) return detail as AdminError;
    if (typeof detail === "string") return { code: "conflict", message: detail } as AdminError;
  } catch {
    // Not JSON: fall through.
  }
  return null;
}

/** GET a JSON resource for a server component. Throws {@link AdminApiError} on any failure. */
export async function adminGet<T>(path: string, actor?: Actor): Promise<T> {
  let response: Response;
  try {
    response = await adminFetch(path, {}, actor);
  } catch (cause) {
    if (cause instanceof Error && cause.name === "AdminConfigError") throw cause;
    throw new AdminApiError(0, null, "The admin API could not be reached.");
  }
  if (!response.ok) {
    const error = await readAdminError(response);
    throw new AdminApiError(response.status, error, error?.message ?? `GET ${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}
