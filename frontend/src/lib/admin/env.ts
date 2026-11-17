import "server-only";

/**
 * Admin console configuration, read from the environment AT CALL TIME.
 *
 * ⚠ NEVER AT MODULE SCOPE. One frontend image is built once and promoted
 * byte-identically through dev, staging and prod (see `lib/api.ts`). Anything
 * read while the module loads would be frozen by whatever `next build` saw, and
 * `next build` sees nothing. Every value below is looked up when a request
 * asks for it, so moving the deployment to a new host is an overlay change
 * (`AUTH_URL` + the ingress host) and never a code change. There is
 * deliberately no hostname anywhere in this file.
 *
 * ⚠ NO SECRET VALUE MAY APPEAR IN AN ERROR MESSAGE. Errors raised here name
 * the VARIABLE that is wrong, never its value: these messages are logged and
 * one of them is rendered on the sign-in page.
 */

/** The GitHub-team group that grants admin unless `IDA_ADMIN_GROUPS` says otherwise. */
export const DEFAULT_ADMIN_GROUPS = ["UA-MIS:ida-llm"];
const DEFAULT_TOKEN_SUBJECT = "admin-console";
const DEFAULT_SESSION_MAX_AGE_S = 8 * 60 * 60;
const DEFAULT_UPLOAD_MAX_BYTES = 1024 * 1024;
/** Mirrors `MIN_TOKEN_LENGTH` in `services/api/ida_api/auth.py`. */
const MIN_TOKEN_LENGTH = 16;

export interface AdminEnv {
  AUTH_URL: string;
  /** `new URL(AUTH_URL).origin`: the only Origin the BFF accepts writes from. */
  origin: string;
  AUTH_SECRET: string;
  AUTH_DEX_ISSUER: string;
  AUTH_DEX_ID: string;
  AUTH_DEX_SECRET: string;
  ADMIN_GROUPS: string[];
  SESSION_MAX_AGE_S: number;
  /** The admin bearer: the `IDA_ADMIN_TOKENS` entry whose subject is `IDA_ADMIN_TOKEN_SUBJECT`. */
  ADMIN_TOKEN: string;
  UPLOAD_MAX_BYTES: number;
  API_URL: string;
}

export class AdminConfigError extends Error {
  constructor(readonly problems: string[]) {
    super(`admin console misconfigured: ${problems.join("; ")}`);
    this.name = "AdminConfigError";
  }
}

/** `/admin` exists only when this is exactly `"true"`. Unset (base, preview) → 404 everywhere. */
export function adminConsoleEnabled(): boolean {
  return process.env.ADMIN_CONSOLE_ENABLED === "true";
}

/** Same grammar as `parse_auth_tokens`: `subject:token` entries split on commas/whitespace, first colon only. */
export function pickAdminToken(raw: string, subject: string): { token?: string; problem?: string } {
  for (const [position, entry] of raw.trim().split(/[\s,]+/).filter(Boolean).entries()) {
    const at = entry.indexOf(":");
    if (at < 0) return { problem: `IDA_ADMIN_TOKENS entry ${position + 1} has no ':'` };
    if (entry.slice(0, at).trim() !== subject) continue;
    const token = entry.slice(at + 1).trim();
    if (token.length < MIN_TOKEN_LENGTH) {
      return { problem: `IDA_ADMIN_TOKENS entry for subject '${subject}' is shorter than ${MIN_TOKEN_LENGTH} characters` };
    }
    return { token };
  }
  return { problem: `IDA_ADMIN_TOKENS has no entry for subject '${subject}' (IDA_ADMIN_TOKEN_SUBJECT)` };
}

function positiveInt(name: string, fallback: number, problems: string[]): number {
  const raw = process.env[name];
  if (raw === undefined || raw.trim() === "") return fallback;
  const n = Number(raw);
  if (!Number.isInteger(n) || n <= 0) {
    problems.push(`${name} must be a positive whole number`);
    return fallback;
  }
  return n;
}

/** Every configuration problem, as variable names and reasons. Empty means healthy. */
export function adminConfigProblems(): string[] {
  try {
    adminEnv();
    return [];
  } catch (err) {
    if (err instanceof AdminConfigError) return err.problems;
    throw err;
  }
}

/** The validated admin configuration. Throws {@link AdminConfigError} naming every unset/invalid variable. */
export function adminEnv(): AdminEnv {
  const env = process.env;
  const problems: string[] = [];
  const required = (name: string): string => {
    const value = env[name]?.trim();
    if (!value) problems.push(`${name} unset`);
    return value ?? "";
  };

  const AUTH_URL = required("AUTH_URL");
  const AUTH_SECRET = required("AUTH_SECRET");
  const AUTH_DEX_ISSUER = required("AUTH_DEX_ISSUER");
  const AUTH_DEX_ID = required("AUTH_DEX_ID");
  const AUTH_DEX_SECRET = required("AUTH_DEX_SECRET");
  const rawTokens = required("IDA_ADMIN_TOKENS");

  let origin = "";
  if (AUTH_URL) {
    try {
      origin = new URL(AUTH_URL).origin;
    } catch {
      problems.push("AUTH_URL is not an absolute URL");
    }
  }
  if (AUTH_DEX_ISSUER) {
    try {
      new URL(AUTH_DEX_ISSUER);
    } catch {
      problems.push("AUTH_DEX_ISSUER is not an absolute URL");
    }
  }

  const groups = (env.IDA_ADMIN_GROUPS ?? "").split(",").map((g) => g.trim()).filter(Boolean);
  const subject = env.IDA_ADMIN_TOKEN_SUBJECT?.trim() || DEFAULT_TOKEN_SUBJECT;
  let ADMIN_TOKEN = "";
  if (rawTokens) {
    const picked = pickAdminToken(rawTokens, subject);
    if (picked.problem) problems.push(picked.problem);
    ADMIN_TOKEN = picked.token ?? "";
  }

  const SESSION_MAX_AGE_S = positiveInt("IDA_ADMIN_SESSION_MAX_AGE_S", DEFAULT_SESSION_MAX_AGE_S, problems);
  const UPLOAD_MAX_BYTES = positiveInt("IDA_ADMIN_UPLOAD_MAX_BYTES", DEFAULT_UPLOAD_MAX_BYTES, problems);

  if (problems.length) throw new AdminConfigError(problems);
  return {
    AUTH_URL,
    origin,
    AUTH_SECRET,
    AUTH_DEX_ISSUER,
    AUTH_DEX_ID,
    AUTH_DEX_SECRET,
    ADMIN_GROUPS: groups.length ? groups : DEFAULT_ADMIN_GROUPS,
    SESSION_MAX_AGE_S,
    ADMIN_TOKEN,
    UPLOAD_MAX_BYTES,
    // Same resolution as the public `lib/api.ts`, read at call time.
    API_URL: env.API_URL ?? env.API_BASE_URL ?? "http://localhost:8000",
  };
}
