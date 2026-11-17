import "server-only";

import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";

import { GITHUB_LOGIN } from "./api";
export { isAdminGroups, recordAuthEvent } from "./auth-config";
import { AdminConfigError, adminConsoleEnabled, adminEnv } from "./env";

/**
 * Who may use `/admin`, decided in one place.
 *
 * ⚠ SECURITY-TOUCHING. The group check runs ONCE, at sign-in (`auth.ts`'s
 * signIn callback): a non-member never receives a session cookie at all. After
 * that, a session is trusted for its lifetime (8 h by default, design R4) only
 * if it carries `admin: true` and a well-formed GitHub login, both of which
 * only our own jwt callback can write into the encrypted cookie.
 */

export interface AdminSession {
  login: string;
  sub: string;
}

/** The admin identity a session proves, or `null` if it proves none. */
export function adminFromSession(session: unknown): AdminSession | null {
  const user = (session as { user?: { login?: unknown; sub?: unknown; admin?: unknown } } | null | undefined)?.user;
  if (!user || user.admin !== true) return null;
  if (typeof user.login !== "string" || !GITHUB_LOGIN.test(user.login)) return null;
  return { login: user.login, sub: typeof user.sub === "string" ? user.sub : "" };
}

/** Only same-site `/admin` paths survive as a post-sign-in destination. */
export function safeCallbackUrl(raw: unknown): string {
  if (typeof raw !== "string") return "/admin";
  if (!/^\/admin(\/[A-Za-z0-9\-._~%/]*)?(\?[^\\]*)?$/.test(raw) || raw.startsWith("//") || raw.includes("..")) {
    return "/admin";
  }
  return raw;
}

/**
 * For pages: the signed-in admin, or a redirect.
 *  - console disabled → 404 (preview, base)
 *  - misconfigured   → the sign-in page, which names the unset variables
 *  - no admin session → `/admin/sign-in?callbackUrl=<here>`
 */
export async function requireAdmin(callbackUrl = "/admin"): Promise<AdminSession> {
  if (!adminConsoleEnabled()) notFound();
  try {
    adminEnv();
  } catch (err) {
    if (err instanceof AdminConfigError) {
      console.error(err.message);
      redirect("/admin/sign-in?error=Configuration");
    }
    throw err;
  }
  const admin = adminFromSession(await auth());
  if (!admin) redirect(`/admin/sign-in?callbackUrl=${encodeURIComponent(safeCallbackUrl(callbackUrl))}`);
  return admin;
}

function jsonError(status: number, code: string, message: string): Response {
  return Response.json({ detail: { code, message } }, { status, headers: { "cache-control": "no-store" } });
}

/** For route handlers (`fetch` callers): JSON 404/401/403/500 instead of a redirect. */
export async function requireAdminForRoute(): Promise<AdminSession | Response> {
  if (!adminConsoleEnabled()) return new Response("Not Found", { status: 404 });
  try {
    adminEnv();
  } catch (err) {
    if (err instanceof AdminConfigError) {
      console.error(err.message);
      return jsonError(500, "admin_misconfigured", "The admin console is misconfigured. An operator has been told.");
    }
    throw err;
  }
  const session = await auth();
  if (!session?.user) return jsonError(401, "unauthenticated", "You are signed out. Sign in again to continue.");
  const admin = adminFromSession(session);
  if (!admin) return jsonError(403, "forbidden", "Your account does not have admin access.");
  return admin;
}

/** The actor a page or route should pass to `adminFetch`. */
export function getActor(admin: AdminSession) {
  return { login: admin.login, sub: admin.sub || undefined };
}
