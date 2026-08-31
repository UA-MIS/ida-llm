/**
 * QA-33. Two title-only labels on the raw run log:
 *   1. `ScoreCell`'s null-score branch was a non-focusable `<span title=…>—</span>`
 *      — its only visible/accessible content was an em dash, so the REASON a
 *      run has no score (failed samples vs. not-yet-scorable vs. something
 *      else) was mouse-hover-only.
 *   2. The "Tokens" header's explanation of what a token roughly is lived
 *      only in `title`.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunRecord } from "@/lib/types";

const listRuns = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  listRuns,
  ApiError: class ApiError extends Error {},
}));

const { default: RunsPage } = await import("@/app/(site)/runs/page");

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "run-1",
    status: "succeeded",
    task_id: "slo2/l3-break-even",
    model_key: "luna",
    label: null,
    sweep_id: null,
    task_git_sha: "abc123def456",
    task_content_sha: null,
    harness_version: "unknown",
    serving_config: null,
    sample_count: 4,
    scored_count: 0,
    error_count: 4,
    mean_score: null,
    total_usage: { prompt_tokens: 100, completion_tokens: 40 },
    total_cost_usd: 0,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:01:00Z",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderRuns(runs: RunRecord[]) {
  listRuns.mockResolvedValue({ runs, total: runs.length, limit: 50, offset: 0 });
  render(await RunsPage());
}

describe("the run log's null-score cell", () => {
  it("carries the reason as text an assistive technology can read, not just as title", async () => {
    await renderRuns([run({ mean_score: null, error_count: 4, status: "failed" })]);

    const cell = document.querySelector("td.num")!;
    const dash = cell.querySelector('[aria-hidden="true"]');
    expect(dash?.textContent).toBe("—");

    const srOnly = cell.querySelector(".sr-only");
    expect(srOnly, "the score cell's reason has no accessible text of its own").not.toBeNull();
    expect(srOnly!.textContent).toMatch(/not scored/i);
  });
});

describe('the "Tokens" header', () => {
  it("keeps its explanation reachable beyond title, without changing its accessible name", async () => {
    await renderRuns([run()]);

    const header = Array.from(document.querySelectorAll("th")).find((th) =>
      th.textContent?.trim().startsWith("Tokens"),
    );
    expect(header, 'no "Tokens" header rendered').not.toBeUndefined();
    expect(header!.getAttribute("title")).toBeTruthy();

    const srOnly = header!.querySelector(".sr-only");
    expect(srOnly, "the Tokens header's explanation has no accessible text of its own").not.toBeNull();
  });
});
