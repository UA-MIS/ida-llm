/**
 * D-92: the demonstration-data tell, on a model's own report card
 * (`/models/[key]`).
 *
 * ⚠ THIS PAGE IS WHERE THE FINEST-GRAINED CLAIM LIVES. `ModelResult.demonstration`
 * is per TASK, not per model — a model can be mostly real with one seeded row
 * filling a gap, or the reverse. The page-level notice (scoped to THIS model,
 * unlike `/leaderboard`'s and `/compare`'s page-wide sentence) only fires when
 * every scored row behind the model was seeded; the per-task badge in the
 * "task by task" table has to carry the mixed case on its own.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { board, result, task } from "./fixtures";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

const { default: ModelReportPage } = await import("@/app/(site)/models/[key]/page");

async function renderReport(response: ReturnType<typeof board>, key = "luna") {
  getLeaderboard.mockResolvedValue(response);
  return render(await ModelReportPage({ params: Promise.resolve({ key }) }));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the demonstration-data tell on a model's report card", () => {
  it("shows a page-level note when every measured row behind this model is seeded", async () => {
    await renderReport(
      board([
        task({
          task_id: "slo2/a",
          slo: "SLO2",
          has_results: true,
          best_model_key: "luna",
          results: [result({ model_key: "luna", mean_score: 0.9, demonstration: true })],
        }),
      ]),
    );

    const notice = document.querySelector(".notice");
    expect(notice, "no demonstration notice on a fully-seeded model's report card").not.toBeNull();
    expect(notice!.textContent!.toLowerCase()).toMatch(/illustrat/);
    expect(notice!.textContent).toMatch(/this model has not been measured/i);

    const head = document.querySelector(".report-head")!;
    expect(head.querySelector(".badge-demo"), "the identity block carries no tell either").not.toBeNull();
  });

  it("does not show the page-level note for a genuinely measured model", async () => {
    await renderReport(
      board([
        task({
          task_id: "slo2/a",
          slo: "SLO2",
          has_results: true,
          best_model_key: "luna",
          results: [result({ model_key: "luna", mean_score: 0.9, demonstration: false })],
        }),
      ]),
    );

    expect(document.querySelector(".notice")).toBeNull();
    expect(document.querySelector(".report-head .badge-demo")).toBeNull();
  });

  /**
   * ⚠ THE CASE THE MODEL-LEVEL NOTE CANNOT CARRY ALONE. One real task and one
   * seeded task means the model is NOT wholly illustrative — `isSeeded`
   * correctly withholds the page-level claim — but the seeded row still needs
   * its own tell where it appears in the task-by-task table, or a reader
   * reading that one row has no way to know.
   */
  it("flags only the seeded task in a mixed model's task-by-task table", async () => {
    await renderReport(
      board([
        task({
          task_id: "slo2/a",
          slo: "SLO2",
          title: "Real task",
          has_results: true,
          best_model_key: "luna",
          results: [result({ model_key: "luna", mean_score: 0.9, demonstration: false })],
        }),
        task({
          task_id: "slo4/b",
          slo: "SLO4",
          title: "Seeded task",
          family: "slo4",
          kind: "subjective",
          has_results: true,
          best_model_key: "luna",
          results: [result({ model_key: "luna", mean_score: 0.6, demonstration: true })],
        }),
      ]),
    );

    // The model is mixed, so the page-level note must stay silent.
    expect(document.querySelector(".notice")).toBeNull();

    const rows = document.querySelectorAll("table.task-table tbody tr");
    const realRow = Array.from(rows).find((tr) => tr.textContent?.includes("Real task"))!;
    const seededRow = Array.from(rows).find((tr) => tr.textContent?.includes("Seeded task"))!;

    expect(realRow.querySelector(".badge-demo"), "the real task's row was flagged").toBeNull();
    expect(
      seededRow.querySelector(".badge-demo"),
      "the seeded task's row carries no demonstration tell",
    ).not.toBeNull();
  });
});
