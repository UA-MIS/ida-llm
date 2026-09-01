/**
 * D-92: the demonstration-data tell, on `/compare`.
 *
 * ⚠ THE SAME BOARD `/overview` ALREADY DISCLOSES. Every seeded row carries
 * `demonstration: true` in the API payload — `/overview` reads it and shows a
 * calm, per-card caveat. This grid read the identical rows and rendered them
 * as a flat comparison: full colour tint, a real-looking score, no caveat
 * anywhere on the page. A reader landing here (one click from the nav) had no
 * way to tell a seeded row from a measured one.
 *
 * Both directions matter equally: a seeded model must be flagged, and a real
 * one must never be — mislabelling a genuine measurement "illustrative" is
 * its own dishonesty.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { board, result, task } from "./fixtures";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

const { default: ComparePage } = await import("@/app/(site)/compare/page");

async function renderCompare(response: ReturnType<typeof board>) {
  getLeaderboard.mockResolvedValue(response);
  render(await ComparePage());
}

function rowFor(name: string): HTMLElement {
  const row = Array.from(document.querySelectorAll("table.cg-grid tbody tr")).find((tr) =>
    tr.textContent?.includes(name),
  );
  if (!row) throw new Error(`no grid row found for "${name}"`);
  return row as HTMLElement;
}

/** One seeded model, one real one, both scored on the same outcome. */
function mixedBoard() {
  return board([
    task({
      task_id: "slo2/a",
      slo: "SLO2",
      has_results: true,
      results: [
        result({
          model_key: "luna",
          display_name: "Luna",
          mean_score: 0.9,
          demonstration: true,
        }),
        result({
          model_key: "vega",
          display_name: "Vega",
          mean_score: 0.7,
          demonstration: false,
        }),
      ],
    }),
  ]);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the demonstration-data tell on /compare", () => {
  it("flags a seeded model's row", async () => {
    await renderCompare(mixedBoard());

    const lunaRow = rowFor("Luna");
    expect(
      lunaRow.querySelector(".badge-demo"),
      "a seeded model's row carries no demonstration tell",
    ).not.toBeNull();
    expect(lunaRow.textContent).toMatch(/illustrative/i);
  });

  it("never flags a model that was actually measured", async () => {
    await renderCompare(mixedBoard());

    const vegaRow = rowFor("Vega");
    expect(
      vegaRow.querySelector(".badge-demo"),
      "a real measurement was labelled illustrative",
    ).toBeNull();
    expect(vegaRow.textContent).not.toMatch(/illustrative/i);
  });

  it("shows a page-level notice above the grid when any row is seeded", async () => {
    await renderCompare(mixedBoard());

    const notice = document.querySelector(".notice");
    expect(notice, "no page-level demonstration notice rendered").not.toBeNull();
    expect(notice!.textContent!.toLowerCase()).toMatch(/illustrat/);

    const grid = document.querySelector("table.cg-grid")!;
    expect(
      notice!.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING,
      "the notice must sit above the grid it qualifies, not below it",
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("stays silent — no notice, no badge — when nothing is seeded", async () => {
    await renderCompare(
      board([
        task({
          task_id: "slo2/a",
          slo: "SLO2",
          has_results: true,
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.9 }),
            result({ model_key: "vega", display_name: "Vega", mean_score: 0.7 }),
          ],
        }),
      ]),
    );

    expect(document.querySelector(".notice")).toBeNull();
    expect(document.querySelector(".badge-demo")).toBeNull();
  });
});
