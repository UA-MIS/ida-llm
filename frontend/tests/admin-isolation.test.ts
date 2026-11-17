/**
 * The admin console is isolated from the public site by code boundaries, not
 * by a second deployment (design AD-1, §6.6). These checks read the sources,
 * the same way `no-qa-exposure.test.ts` does, because the claim is about every
 * file at once, including files nobody has written yet.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("../src", import.meta.url));
const ROOT = fileURLToPath(new URL("..", import.meta.url));

function files(dir = SRC): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    return statSync(full).isDirectory() ? files(full) : [full];
  });
}

const ALL = files().filter((f) => /\.(ts|tsx|js|jsx|mjs)$/.test(f));
const rel = (f: string) => f.slice(SRC.length);
const read = (f: string) => readFileSync(f, "utf8");
const code = (f: string) => read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const ADMIN_TREES = ["/app/admin/", "/components/admin/", "/lib/admin/", "/app/api/auth/"];
const isAdmin = (f: string) => rel(f) === "/auth.ts" || ADMIN_TREES.some((t) => rel(f).startsWith(t));

describe("the public site cannot reach the admin console", () => {
  it("has admin files to check (the suite is not vacuous)", () => {
    expect(ALL.filter(isAdmin).length).toBeGreaterThan(5);
  });

  it("no non-admin file imports lib/admin, components/admin or auth", () => {
    const banned = /from\s+["'](@\/lib\/admin|@\/components\/admin|@\/auth)(["'/])|from\s+["'](\.\.?\/)+(lib\/admin|components\/admin|auth)(["'/])|import\(\s*["'](@\/lib\/admin|@\/components\/admin|@\/auth)/;
    for (const f of ALL.filter((p) => !isAdmin(p))) {
      expect(code(f), `${rel(f)} imports the admin console`).not.toMatch(banned);
    }
  });

  it("no public page links to /admin", () => {
    for (const f of ALL.filter((p) => !isAdmin(p) && p.endsWith(".tsx"))) {
      expect(code(f), `${rel(f)} links to /admin`).not.toMatch(/["'`]\/admin\b/);
    }
  });
});

describe("every admin page proves an admin before it renders", () => {
  const pages = ALL.filter((f) => /^\/app\/admin\/.*page\.tsx$/.test(rel(f)));
  const exempt = ["/app/admin/sign-in/page.tsx", "/app/admin/denied/page.tsx"];

  it("found the admin pages", () => {
    expect(pages.length).toBeGreaterThanOrEqual(3);
  });

  it.each(pages.filter((p) => !exempt.includes(rel(p))).map(rel))("%s calls requireAdmin() and is force-dynamic", (page) => {
    const body = code(join(SRC, page));
    expect(body).toMatch(/await requireAdmin\(/);
    expect(body).toMatch(/export const dynamic = "force-dynamic"/);
  });

  it.each(exempt)("%s is force-dynamic, 404s when disabled, and fetches no admin data", (page) => {
    const body = code(join(SRC, page));
    expect(body).toMatch(/export const dynamic = "force-dynamic"/);
    expect(body).toMatch(/adminConsoleEnabled\(\)\)\s*notFound\(\)/);
    expect(body).not.toMatch(/adminGet|adminFetch/);
  });

  it("the admin shell 404s when the console is disabled", () => {
    expect(code(join(SRC, "app/admin/layout.tsx"))).toMatch(/if \(!adminConsoleEnabled\(\)\) notFound\(\)/);
  });
});

describe("server secrets stay on the server", () => {
  it.each(["lib/admin/env.ts", "lib/admin/session.ts", "lib/admin/api.ts", "lib/admin/auth-config.ts"])(
    "%s imports server-only",
    (f) => {
      expect(read(join(SRC, f))).toMatch(/^import "server-only";/m);
    },
  );

  it("no client component imports a server-only admin module", () => {
    const clients = ALL.filter((f) => /^\s*["']use client["']/.test(read(f)));
    for (const f of clients) {
      expect(code(f), `${rel(f)} imports a server module`).not.toMatch(
        /@\/lib\/admin\/(env|session|api|auth-config)["']|@\/auth["']/,
      );
    }
  });

  it("no admin env var is exposed through NEXT_PUBLIC_", () => {
    for (const f of ALL) {
      expect(code(f), `${rel(f)} uses NEXT_PUBLIC_ for admin config`).not.toMatch(/NEXT_PUBLIC_(AUTH|IDA_ADMIN|ADMIN)/);
    }
  });
});

describe("no second way in (design AD-3)", () => {
  it("has no middleware", () => {
    for (const name of ["middleware.ts", "middleware.js", "src/middleware.ts", "src/middleware.js"]) {
      expect(existsSync(join(ROOT, name)), name).toBe(false);
    }
  });

  it("has no pages router", () => {
    expect(existsSync(join(ROOT, "src/pages"))).toBe(false);
    expect(existsSync(join(ROOT, "pages"))).toBe(false);
  });

  it('has no Server Actions ("use server")', () => {
    for (const f of ALL) {
      expect(code(f), `${rel(f)} declares a Server Action`).not.toMatch(/["']use server["']/);
    }
  });

  it("hardcodes no deployment hostname in the admin code", () => {
    for (const f of ALL.filter(isAdmin)) {
      expect(code(f), `${rel(f)} hardcodes a host`).not.toMatch(/uamishub\.com|capstone\./);
    }
  });
});
