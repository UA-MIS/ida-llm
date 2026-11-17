/**
 * Who gets an admin session (design §6.3, §6.4). SECURITY-TOUCHING: the group
 * rule is exact, and a non-member is turned away inside Auth.js's signIn
 * callback, so they never receive a cookie.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/auth", () => ({ auth: vi.fn() }));

import { buildAuthConfig, isAdminGroups } from "@/lib/admin/auth-config";
import { AdminConfigError, adminConfigProblems, adminEnv, pickAdminToken } from "@/lib/admin/env";
import { adminFromSession, safeCallbackUrl } from "@/lib/admin/session";

const TOKEN = "tok_0123456789abcdefghij";
const ENV = {
  ADMIN_CONSOLE_ENABLED: "true",
  AUTH_URL: "https://admin.example.test",
  AUTH_SECRET: "s".repeat(32),
  AUTH_DEX_ISSUER: "https://dex.example.test",
  AUTH_DEX_ID: "ida-llm",
  AUTH_DEX_SECRET: "dex-secret-value",
  IDA_ADMIN_TOKENS: `runner-bot:${"r".repeat(20)},admin-console:${TOKEN}`,
  API_URL: "http://api.internal",
};

function setEnv(overrides: Record<string, string | undefined> = {}) {
  for (const [k, v] of Object.entries({ ...ENV, ...overrides })) {
    if (v === undefined) vi.stubEnv(k, undefined as unknown as string);
    else vi.stubEnv(k, v);
  }
}

describe("isAdminGroups", () => {
  const allowed = ["UA-MIS:ida-llm"];

  it("admits an exact member", () => {
    expect(isAdminGroups(["UA-MIS:other", "UA-MIS:ida-llm"], allowed)).toBe(true);
  });

  it.each([
    ["a longer team name", ["UA-MIS:ida-llm-x"]],
    ["a different case", ["ua-mis:ida-llm"]],
    ["the org alone", ["UA-MIS"]],
    ["a prefix", ["UA-MIS:ida"]],
    ["padding", [" UA-MIS:ida-llm"]],
  ])("rejects %s", (_label, groups) => {
    expect(isAdminGroups(groups, allowed)).toBe(false);
  });

  it.each([undefined, null, "UA-MIS:ida-llm", { 0: "UA-MIS:ida-llm" }, [1, 2], []])("rejects non-array or empty groups (%j)", (groups) => {
    expect(isAdminGroups(groups, allowed)).toBe(false);
  });

  it("honours the configured list", () => {
    expect(isAdminGroups(["UA-MIS:staff"], ["UA-MIS:ida-llm", "UA-MIS:staff"])).toBe(true);
    expect(isAdminGroups(["UA-MIS:ida-llm"], ["UA-MIS:staff"])).toBe(false);
  });
});

describe("adminFromSession", () => {
  it("accepts only admin:true with a well-formed GitHub login", () => {
    expect(adminFromSession({ user: { login: "ccsmith33", sub: "abc", admin: true } })).toEqual({ login: "ccsmith33", sub: "abc" });
    expect(adminFromSession({ user: { login: "ccsmith33", admin: false } })).toBeNull();
    expect(adminFromSession({ user: { login: "ccsmith33" } })).toBeNull();
    expect(adminFromSession({ user: { login: "bad login!", admin: true } })).toBeNull();
    expect(adminFromSession({ user: { login: "x".repeat(40), admin: true } })).toBeNull();
    expect(adminFromSession(null)).toBeNull();
    expect(adminFromSession({})).toBeNull();
  });
});

describe("safeCallbackUrl", () => {
  it.each(["/admin", "/admin/models", "/admin/models/gpt-5?tab=x"])("keeps %s", (url) => {
    expect(safeCallbackUrl(url)).toBe(url);
  });
  it.each(["https://evil.test/admin", "//evil.test", "/", "/runs", "/admin/../runs", "/adminx", undefined, 3])("refuses %s", (url) => {
    expect(safeCallbackUrl(url)).toBe("/admin");
  });
});

describe("admin env", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("picks the token for IDA_ADMIN_TOKEN_SUBJECT (default admin-console)", () => {
    setEnv();
    expect(adminEnv().ADMIN_TOKEN).toBe(TOKEN);
    setEnv({ IDA_ADMIN_TOKEN_SUBJECT: "runner-bot" });
    expect(adminEnv().ADMIN_TOKEN).toBe("r".repeat(20));
  });

  it("defaults the admin group to UA-MIS:ida-llm and accepts a list", () => {
    setEnv();
    expect(adminEnv().ADMIN_GROUPS).toEqual(["UA-MIS:ida-llm"]);
    setEnv({ IDA_ADMIN_GROUPS: "UA-MIS:ida-llm, UA-MIS:staff" });
    expect(adminEnv().ADMIN_GROUPS).toEqual(["UA-MIS:ida-llm", "UA-MIS:staff"]);
  });

  it("derives the CSRF origin from AUTH_URL, so a host move is config only", () => {
    setEnv({ AUTH_URL: "https://somewhere-new.example.org/" });
    expect(adminEnv().origin).toBe("https://somewhere-new.example.org");
  });

  it("names every missing variable and never quotes a secret", () => {
    setEnv({ AUTH_SECRET: undefined, AUTH_DEX_SECRET: undefined, IDA_ADMIN_TOKENS: "admin-console:short" });
    const problems = adminConfigProblems();
    expect(problems).toContain("AUTH_SECRET unset");
    expect(problems).toContain("AUTH_DEX_SECRET unset");
    expect(problems.join(" ")).toMatch(/IDA_ADMIN_TOKENS entry for subject 'admin-console' is shorter/);
    expect(() => adminEnv()).toThrow(AdminConfigError);
    const all = problems.join(" ");
    for (const secret of ["short", ENV.AUTH_SECRET, ENV.AUTH_DEX_SECRET]) expect(all).not.toContain(`:${secret}`);
    expect(all).not.toContain(ENV.AUTH_DEX_SECRET);
  });

  it("reads env at call time, not at import", () => {
    setEnv({ AUTH_URL: "https://one.example.test" });
    expect(adminEnv().origin).toBe("https://one.example.test");
    setEnv({ AUTH_URL: "https://two.example.test" });
    expect(adminEnv().origin).toBe("https://two.example.test");
  });

  it("parses tokens with the API's grammar", () => {
    expect(pickAdminToken(`a:${"x".repeat(16)}\nadmin-console:${TOKEN}`, "admin-console")).toEqual({ token: TOKEN });
    expect(pickAdminToken("no-colon", "admin-console").problem).toMatch(/entry 1 has no ':'/);
    expect(pickAdminToken(`other:${TOKEN}`, "admin-console").problem).toMatch(/no entry for subject/);
  });
});

describe("the signIn callback", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    setEnv();
    fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  const signIn = (profile: Record<string, unknown>) => {
    const config = buildAuthConfig(adminEnv());
    return config.callbacks!.signIn!({ profile, user: { id: "u" } } as never);
  };

  const postedEvent = () => {
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    return { url, init, body: JSON.parse(String(init.body)) as Record<string, unknown>, headers: init.headers as Record<string, string> };
  };

  it("lets a member in and records auth.sign_in", async () => {
    await expect(signIn({ sub: "s1", preferred_username: "ccsmith33", groups: ["UA-MIS:ida-llm"] })).resolves.toBe(true);
    const ev = postedEvent();
    expect(ev.url).toBe("http://api.internal/admin/audit/events");
    expect(ev.body).toEqual({ action: "auth.sign_in", login: "ccsmith33", sub: "s1", groups_ok: true });
    expect(ev.headers.authorization).toBe(`Bearer ${TOKEN}`);
    expect(ev.headers["x-ida-actor"]).toBe("ccsmith33");
  });

  it("sends a non-member to the denied page and records auth.denied", async () => {
    await expect(signIn({ sub: "s2", preferred_username: "outsider", groups: ["UA-MIS:ida-llm-x"] })).resolves.toBe(
      "/admin/denied?login=outsider",
    );
    expect(postedEvent().body).toMatchObject({ action: "auth.denied", login: "outsider", groups_ok: false });
  });

  it("denies a member whose login is missing or malformed", async () => {
    await expect(signIn({ sub: "s3", groups: ["UA-MIS:ida-llm"] })).resolves.toBe("/admin/denied");
    await expect(signIn({ sub: "s3", preferred_username: "<script>", groups: ["UA-MIS:ida-llm"] })).resolves.toBe("/admin/denied");
  });

  it("still denies when the audit call fails", async () => {
    fetchMock.mockRejectedValue(new Error("down"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    await expect(signIn({ preferred_username: "outsider", groups: [] })).resolves.toBe("/admin/denied?login=outsider");
  });

  it("puts only login, sub and admin into the JWT and the session", async () => {
    const config = buildAuthConfig(adminEnv());
    const token = await config.callbacks!.jwt!({
      token: { name: "N", email: "e@x", picture: "p" },
      profile: { sub: "s1", preferred_username: "ccsmith33", groups: ["UA-MIS:ida-llm"], email: "e@x" },
      user: { id: "u" },
    } as never);
    expect(token).toEqual({ sub: "s1", login: "ccsmith33", admin: true });
    const session = await config.callbacks!.session!({ session: { expires: "2099-01-01", user: {} }, token } as never);
    expect(session).toEqual({ expires: "2099-01-01", user: { login: "ccsmith33", sub: "s1", admin: true } });
  });

  it("asks Dex for groups with PKCE, state and nonce", () => {
    const provider = buildAuthConfig(adminEnv()).providers![0] as unknown as Record<string, unknown>;
    expect(provider).toMatchObject({ id: "dex", type: "oidc", issuer: "https://dex.example.test", clientId: "ida-llm" });
    expect(provider.checks).toEqual(["pkce", "state", "nonce"]);
    expect(JSON.stringify(provider.authorization)).toContain("groups");
  });
});
