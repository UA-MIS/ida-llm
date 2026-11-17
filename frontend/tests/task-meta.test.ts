/** `getTaskMeta`: the public run page's only view of a task (admin-console B6). */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getTaskMeta } from "@/lib/api";

const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("getTaskMeta", () => {
  it("asks for /meta", async () => {
    const fetchMock = vi.fn(async () => ok({ id: "t", samples: [{ id: "s1", metadata: { skill: "x" } }] }));
    vi.stubGlobal("fetch", fetchMock);
    const meta = await getTaskMeta("fam/t");
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toMatch(/\/tasks\/fam\/t\/meta$/);
    expect(meta.samples[0]).toEqual({ id: "s1", metadata: { skill: "x" } });
  });

  it("falls back to the full spec on an older API, keeping only id and metadata", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 404, statusText: "Not Found" }))
      .mockResolvedValueOnce(ok({ id: "t", samples: [{ id: "s1", input: "THE PROMPT", target: "GOLD", metadata: { skill: "x" } }] }));
    vi.stubGlobal("fetch", fetchMock);
    const meta = await getTaskMeta("fam/t");
    expect(JSON.stringify(meta)).not.toMatch(/THE PROMPT|GOLD/);
    expect(meta).toEqual({ id: "t", samples: [{ id: "s1", metadata: { skill: "x" } }] });
  });

  it("does not fall back on other errors", async () => {
    const fetchMock = vi.fn(async () => new Response("", { status: 500, statusText: "boom" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getTaskMeta("t")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
