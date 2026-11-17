/**
 * The BFF (`app/admin/api/[...path]/route.ts`) is the only way a browser
 * reaches the admin API. SECURITY-TOUCHING: each rule below is one of the
 * ordered checks in design §6.4.
 */

import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.fn();
vi.mock("@/auth", () => ({ auth: () => authMock() }));

import * as route from "@/app/admin/api/[...path]/route";
import { upstreamPath } from "@/lib/admin/bff-path";

const TOKEN = "tok_0123456789abcdefghij";
const ORIGIN = "https://admin.example.test";
const ADMIN = { user: { login: "ccsmith33", sub: "dex-sub-1", admin: true }, expires: "2099-01-01" };

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubEnv("ADMIN_CONSOLE_ENABLED", "true");
  vi.stubEnv("AUTH_URL", ORIGIN);
  vi.stubEnv("AUTH_SECRET", "s".repeat(32));
  vi.stubEnv("AUTH_DEX_ISSUER", "https://dex.example.test");
  vi.stubEnv("AUTH_DEX_ID", "ida-llm");
  vi.stubEnv("AUTH_DEX_SECRET", "dex-secret");
  vi.stubEnv("IDA_ADMIN_TOKENS", `admin-console:${TOKEN}`);
  vi.stubEnv("API_URL", "http://api.internal");
  authMock.mockResolvedValue(ADMIN);
  fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json", etag: '"3"', "set-cookie": "leak=1", "x-internal": "no" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  authMock.mockReset();
});

function call(
  method: string,
  path: string[],
  init: { headers?: Record<string, string>; body?: string; search?: string } = {},
): Promise<Response> {
  const url = `${ORIGIN}/admin/api/${path.join("/")}${init.search ?? ""}`;
  const req = new NextRequest(url, { method, headers: init.headers, body: init.body });
  const handler = (route as unknown as Record<string, (r: NextRequest, c: unknown) => Promise<Response>>)[method]!;
  return handler(req, { params: Promise.resolve({ path }) });
}

const writeHeaders = { origin: ORIGIN, "content-type": "application/json" };
const forwarded = () => {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }];
  return { url, init, headers: init.headers };
};

describe("gates", () => {
  it("404s when the console is disabled, before looking at the session", async () => {
    vi.stubEnv("ADMIN_CONSOLE_ENABLED", "");
    const res = await call("GET", ["system"]);
    expect(res.status).toBe(404);
    expect(authMock).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("401s with no session", async () => {
    authMock.mockResolvedValue(null);
    const res = await call("GET", ["system"]);
    expect(res.status).toBe(401);
    expect((await res.json()).detail.code).toBe("unauthenticated");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("403s a session that is not an admin one", async () => {
    authMock.mockResolvedValue({ user: { login: "someone", admin: false } });
    expect((await call("GET", ["system"])).status).toBe(403);
    authMock.mockResolvedValue({ user: { login: "bad login", admin: true } });
    expect((await call("GET", ["system"])).status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["POST", "PUT", "PATCH", "DELETE"])("403s a cross-origin %s", async (method) => {
    const res = await call(method, ["models"], { headers: { origin: "https://evil.test", "content-type": "application/json" }, body: "{}" });
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("403s a write with no Origin at all", async () => {
    const res = await call("POST", ["models"], { headers: { "content-type": "application/json" }, body: "{}" });
    expect(res.status).toBe(403);
  });

  it("415s a form-encoded or text write (the classic CSRF shapes)", async () => {
    for (const type of ["application/x-www-form-urlencoded", "text/plain"]) {
      const res = await call("POST", ["models"], { headers: { origin: ORIGIN, "content-type": type }, body: "a=1" });
      expect(res.status).toBe(415);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([[[".."]], [["models", "..", "x"]], [["."]], [["a", ""]], [["a%2Fb".replace("%2F", "/")]], [[]]])(
    "400s an escaping path %j",
    async (path) => {
      const res = await call("GET", path as string[]);
      expect(res.status).toBe(400);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("413s an oversized body", async () => {
    vi.stubEnv("IDA_ADMIN_UPLOAD_MAX_BYTES", "10");
    const res = await call("POST", ["material", "upload"], { headers: writeHeaders, body: "x".repeat(70 * 1024) });
    expect(res.status).toBe(413);
  });
});

describe("forwarding", () => {
  it("keeps every request under /admin/ and re-encodes segments", () => {
    expect(upstreamPath(["tasks", "family-a", "task one"])).toBe("/admin/tasks/family-a/task%20one");
    expect(upstreamPath(["x?y=1"])).toBe("/admin/x%3Fy%3D1");
    expect(upstreamPath(["..%2f"])).toBe("/admin/..%252f");
  });

  it("injects the bearer and actor, and forwards the query string", async () => {
    await call("GET", ["runs"], { search: "?status=running&limit=5" });
    const { url, headers } = forwarded();
    expect(url).toBe("http://api.internal/admin/runs?status=running&limit=5");
    expect(headers.authorization).toBe(`Bearer ${TOKEN}`);
    expect(headers["x-ida-actor"]).toBe("ccsmith33");
    expect(headers["x-ida-actor-sub"]).toBe("dex-sub-1");
    expect(headers["x-request-id"]).toMatch(/[0-9a-f-]{36}/);
  });

  it("forwards only content-type, if-match and accept; never the browser's cookie or authorization", async () => {
    await call("PUT", ["models", "gpt-5"], {
      headers: {
        ...writeHeaders,
        "if-match": "7",
        accept: "application/json",
        cookie: "__Secure-authjs.session-token=SESSION",
        authorization: "Bearer BROWSER-SUPPLIED",
        "x-ida-actor": "impersonated",
        "x-forwarded-for": "1.2.3.4",
      },
      body: JSON.stringify({ display_name: "x" }),
    });
    const { init, headers } = forwarded();
    expect(init.method).toBe("PUT");
    expect(headers["if-match"]).toBe("7");
    expect(headers["content-type"]).toBe("application/json");
    expect(headers.authorization).toBe(`Bearer ${TOKEN}`);
    expect(headers["x-ida-actor"]).toBe("ccsmith33");
    const wire = JSON.stringify(headers);
    for (const leaked of ["SESSION", "BROWSER-SUPPLIED", "impersonated", "1.2.3.4", "cookie"]) expect(wire).not.toContain(leaked);
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe(JSON.stringify({ display_name: "x" }));
  });

  it("returns status, body and only allowlisted response headers, uncached", async () => {
    const res = await call("GET", ["models"]);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(res.headers.get("etag")).toBe('"3"');
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("x-internal")).toBeNull();
  });

  it("passes API errors through so forms can show them", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "version_conflict", message: "changed" } }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );
    const res = await call("DELETE", ["models", "x"], { headers: writeHeaders, body: "{}" });
    expect(res.status).toBe(409);
    expect((await res.json()).detail.code).toBe("version_conflict");
  });

  it("502s politely when the API is unreachable", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED 10.0.0.1"));
    const res = await call("GET", ["system"]);
    expect(res.status).toBe(502);
    expect(await res.text()).not.toContain("10.0.0.1");
  });
});
