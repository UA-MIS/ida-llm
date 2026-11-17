import NextAuth from "next-auth";

import { buildAuthConfig } from "@/lib/admin/auth-config";
import { adminEnv } from "@/lib/admin/env";

/**
 * Auth.js v5 (`next-auth@5.0.0-beta.32`, pinned exactly: v5 has only ever
 * shipped as a beta, design R1). Admin-only: no public module may import this
 * file (`tests/admin-isolation.test.ts`, ESLint `no-restricted-imports`).
 *
 * ⚠ THE CONFIG IS LAZY. NextAuth receives a function, so env is read per
 * request and never at build time. That keeps one image promotable through
 * every environment, and a misconfigured env fails the admin request (naming
 * the unset variable) instead of the build or the public site.
 */
export const { handlers, auth, signIn, signOut } = NextAuth(() => buildAuthConfig(adminEnv()));
