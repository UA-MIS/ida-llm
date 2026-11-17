import "server-only";

import type { NextAuthConfig } from "next-auth";

import { GITHUB_LOGIN, adminFetch } from "./api";
import type { AdminEnv } from "./env";

/**
 * The Auth.js configuration, built per request from validated env.
 *
 * ⚠ SECURITY-TOUCHING. Kept apart from `src/auth.ts` so the callbacks can be
 * tested without Next's request machinery. The rules it encodes:
 *
 *  - ONE generic OIDC provider, `dex`, at `AUTH_DEX_ISSUER`, with PKCE, state
 *    and nonce. Dex brokers GitHub and emits the `groups` claim as
 *    `"<org>:<team-slug>"`.
 *  - The group check happens in `signIn`. A non-member is redirected to
 *    `/admin/denied` and never receives a session cookie.
 *  - The JWT carries only `login`, `sub` and `admin: true`. No email, no
 *    groups, no tokens from Dex: nothing we do not use is stored.
 */

/**
 * Exact, case-sensitive membership. `UA-MIS:ida-llm-x` and `ua-mis:ida-llm`
 * are NOT `UA-MIS:ida-llm`: a prefix or case-folded match would admit teams
 * that merely look like ours.
 */
export function isAdminGroups(groups: unknown, allowed: string[]): boolean {
  if (!Array.isArray(groups)) return false;
  return groups.some((g) => typeof g === "string" && allowed.includes(g));
}

export type AuthEventAction = "auth.sign_in" | "auth.denied" | "auth.sign_out";

/**
 * Record a sign-in, denial or sign-out in the API's audit log (§5.2
 * `POST /admin/audit/events`), the ONLY record of a denied attempt. It never
 * throws and gives up after two seconds: an audit outage must neither lock
 * admins out nor turn a denial into an admission.
 */
export async function recordAuthEvent(event: {
  action: AuthEventAction;
  login: string;
  sub?: string;
  groups_ok: boolean;
}): Promise<void> {
  const login = GITHUB_LOGIN.test(event.login) ? event.login : "unknown";
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      adminFetch(
        "/admin/audit/events",
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ action: event.action, login, sub: event.sub, groups_ok: event.groups_ok }),
        },
        { login, sub: event.sub },
      ),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("timed out")), 2000);
      }),
    ]);
  } catch (err) {
    console.error(`admin audit event ${event.action} not recorded: ${err instanceof Error ? err.message : "error"}`);
  } finally {
    clearTimeout(timer);
  }
}

type Claims = { sub?: unknown; preferred_username?: unknown; groups?: unknown };

function loginOf(profile: Claims | undefined): string {
  const login = profile?.preferred_username;
  return typeof login === "string" ? login : "";
}

export function buildAuthConfig(env: AdminEnv): NextAuthConfig {
  return {
    secret: env.AUTH_SECRET,
    // Behind Cloudflare + Traefik. AUTH_URL (read by Auth.js from env at
    // request time) pins the canonical origin, so the Host header is not
    // what builds the redirect URI.
    trustHost: true,
    session: { strategy: "jwt", maxAge: env.SESSION_MAX_AGE_S },
    pages: { signIn: "/admin/sign-in", error: "/admin/denied" },
    providers: [
      {
        id: "dex",
        name: "GitHub (UA-MIS)",
        type: "oidc",
        issuer: env.AUTH_DEX_ISSUER,
        clientId: env.AUTH_DEX_ID,
        clientSecret: env.AUTH_DEX_SECRET,
        authorization: { params: { scope: "openid profile email groups federated:id" } },
        checks: ["pkce", "state", "nonce"],
      },
    ],
    callbacks: {
      async signIn({ profile }) {
        const claims = profile as Claims | undefined;
        const login = loginOf(claims);
        const sub = typeof claims?.sub === "string" ? claims.sub : undefined;
        const ok = GITHUB_LOGIN.test(login) && isAdminGroups(claims?.groups, env.ADMIN_GROUPS);
        await recordAuthEvent({ action: ok ? "auth.sign_in" : "auth.denied", login: login || "unknown", sub, groups_ok: ok });
        if (ok) return true;
        return GITHUB_LOGIN.test(login) ? `/admin/denied?login=${encodeURIComponent(login)}` : "/admin/denied";
      },
      async jwt({ token, profile }) {
        // `profile` is present only on the sign-in that passed `signIn` above.
        if (profile) {
          const claims = profile as Claims;
          return {
            sub: typeof claims.sub === "string" ? claims.sub : token.sub,
            login: loginOf(claims),
            admin: true,
          };
        }
        return token;
      },
      async session({ session, token }) {
        // Replace, do not merge: the browser-visible session carries nothing else.
        return {
          expires: session.expires,
          user: { login: token.login, sub: token.sub, admin: token.admin === true },
        } as unknown as typeof session;
      },
    },
    events: {
      async signOut(message) {
        const token = "token" in message ? (message.token as { login?: unknown; sub?: unknown } | null) : null;
        const login = typeof token?.login === "string" ? token.login : "unknown";
        const sub = typeof token?.sub === "string" ? token.sub : undefined;
        await recordAuthEvent({ action: "auth.sign_out", login, sub, groups_ok: true });
      },
    },
  };
}
