/**
 * Browser-side calls to the BFF (`/admin/api/...`). Imported only by
 * `components/admin/*` client components. Holds no secret and no server
 * import: the BFF adds the bearer and actor; this only speaks JSON to it.
 */

import type { AdminError, Issue, Version } from "./types";

export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: AdminError };

const FRIENDLY: Record<number, string> = {
  0: "The admin service could not be reached. Check your connection and try again.",
  401: "Your sign-in has expired. Reload the page to sign in again.",
  403: "Your account does not have permission to do that.",
  404: "That item no longer exists. It may have been removed by someone else.",
  413: "That file is too large.",
  428: "The page was out of date. Reload it and try again.",
  429: "Please wait a few seconds before trying that again.",
  501: "This feature is not available yet. It will work once that part of the service is deployed.",
  502: "The admin service could not be reached. Try again in a minute.",
  503: "The admin service is not switched on yet. Ask an operator.",
};

/**
 * Callers name the API path itself (`/admin/models/x`), exactly as the
 * contract publishes it; the BFF lives one level down at `/admin/api/...`.
 */
export function bffUrl(path: string): string {
  if (!path.startsWith("/admin/")) throw new Error(`adminApi: expected an /admin/ API path, got ${path}`);
  return `/admin/api${path.slice("/admin".length)}`;
}

export async function adminApi<T = unknown>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  options: { body?: unknown; version?: Version; form?: FormData } = {},
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { accept: "application/json" };
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form; // the browser sets multipart/form-data with its boundary
  } else if (method !== "GET") {
    headers["content-type"] = "application/json";
    body = JSON.stringify(options.body ?? {});
  }
  if (options.version !== undefined) headers["if-match"] = String(options.version);

  let response: Response;
  try {
    response = await fetch(bffUrl(path), { method, headers, body, credentials: "same-origin" });
  } catch {
    return { ok: false, status: 0, error: { code: "conflict", message: FRIENDLY[0]! } };
  }
  if (response.status === 204) return { ok: true, status: 204, data: undefined as T };
  let parsed: unknown = null;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  if (response.ok) return { ok: true, status: response.status, data: parsed as T };
  const detail = (parsed as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    const error = detail as AdminError;
    return { ok: false, status: response.status, error: { ...error, message: error.message || FRIENDLY[response.status] || "Something went wrong." } };
  }
  return {
    ok: false,
    status: response.status,
    error: { code: "conflict", message: typeof detail === "string" ? detail : FRIENDLY[response.status] ?? `Something went wrong (${response.status}).` },
  };
}

/** Split issues into those pinned to a known field and the rest (shown at the top). */
export function partitionIssues(issues: Issue[] | undefined, fields: string[]): { byField: Record<string, Issue[]>; other: Issue[] } {
  const byField: Record<string, Issue[]> = {};
  const other: Issue[] = [];
  for (const issue of issues ?? []) {
    const field = fields.find((f) => issue.path === f || issue.path.startsWith(`${f}.`) || issue.path.startsWith(`${f}[`));
    if (field) (byField[field] ??= []).push(issue);
    else other.push(issue);
  }
  return { byField, other };
}
