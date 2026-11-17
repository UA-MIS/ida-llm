/**
 * Every admin page, signed out, redirects to `/admin/sign-in` and fetches
 * nothing; with the console disabled, every admin page is a 404. Pages are
 * discovered from the filesystem, so a page added later is covered without
 * touching this file.
 */

/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.fn();
vi.mock("@/auth", () => ({ auth: () => authMock() }));

const modules = import.meta.glob<{ default: (props: unknown) => unknown }>("../src/app/admin/**/{page,layout}.tsx");
// The two shells guard differently: the outer one only 404s when disabled, the
// console one withholds its chrome (tested below) and leaves redirects to pages.
const EXEMPT = /\/admin\/(sign-in|denied)\/page\.tsx$|\/layout\.tsx$/;
const guarded = Object.keys(modules).filter((p) => !EXEMPT.test(p));

const props = {
  params: Promise.resolve({ key: "k", family: "f", id: ["f", "t"], course: "MIS 200", runId: "r", sweepId: "s", path: ["x"] }),
  searchParams: Promise.resolve({}),
  children: null,
};

async function digestOf(run: () => unknown): Promise<string> {
  try {
    await run();
  } catch (err) {
    return String((err as { digest?: string }).digest ?? err);
  }
  return "rendered";
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubEnv("ADMIN_CONSOLE_ENABLED", "true");
  vi.stubEnv("AUTH_URL", "https://admin.example.test");
  vi.stubEnv("AUTH_SECRET", "s".repeat(32));
  vi.stubEnv("AUTH_DEX_ISSUER", "https://dex.example.test");
  vi.stubEnv("AUTH_DEX_ID", "ida-llm");
  vi.stubEnv("AUTH_DEX_SECRET", "dex-secret");
  vi.stubEnv("IDA_ADMIN_TOKENS", "admin-console:tok_0123456789abcdefghij");
  authMock.mockResolvedValue(null);
  fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("signed-out admin pages", () => {
  it("found guarded pages", () => {
    expect(guarded.length).toBeGreaterThanOrEqual(2);
  });

  it.each(guarded)("%s redirects to /admin/sign-in and fetches nothing", async (path) => {
    const mod = await modules[path]!();
    const digest = await digestOf(() => mod.default(props));
    expect(digest).toMatch(/^NEXT_REDIRECT;[a-z]+;\/admin\/sign-in\?callbackUrl=%2Fadmin/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(guarded)("%s also redirects a non-admin session", async (path) => {
    authMock.mockResolvedValue({ user: { login: "outsider", admin: false } });
    const mod = await modules[path]!();
    expect(await digestOf(() => mod.default(props))).toMatch(/\/admin\/sign-in/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("with the console disabled", () => {
  it.each(Object.keys(modules))("%s is a 404", async (path) => {
    vi.stubEnv("ADMIN_CONSOLE_ENABLED", "");
    authMock.mockResolvedValue({ user: { login: "ccsmith33", admin: true } });
    const mod = await modules[path]!();
    expect(await digestOf(() => mod.default(props))).toMatch(/^NEXT_HTTP_ERROR_FALLBACK;404/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("the console layout", () => {
  it("renders no chrome (and no signed-in name) without an admin session", async () => {
    const path = Object.keys(modules).find((p) => p.endsWith("(console)/layout.tsx"))!;
    const mod = await modules[path]!();
    const out = await mod.default({ children: "CHILD" });
    expect(JSON.stringify(out)).not.toMatch(/Signed in as|adm-header/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("misconfigured", () => {
  it("sends admins to the sign-in page, which names the unset variable", async () => {
    vi.stubEnv("AUTH_DEX_SECRET", "");
    const page = guarded.find((p) => p.endsWith("(console)/page.tsx"))!;
    const mod = await modules[page]!();
    expect(await digestOf(() => mod.default(props))).toMatch(/\/admin\/sign-in\?error=Configuration/);
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
});

describe("the auth route", () => {
  it("404s every Auth.js endpoint when the console is disabled", async () => {
    vi.stubEnv("ADMIN_CONSOLE_ENABLED", "");
    const { GET, POST } = await import("@/app/api/auth/[...nextauth]/route");
    const { NextRequest } = await import("next/server");
    expect((await GET(new NextRequest("https://x.test/api/auth/session"))).status).toBe(404);
    expect((await POST(new NextRequest("https://x.test/api/auth/signin/dex", { method: "POST" }))).status).toBe(404);
  });
});
