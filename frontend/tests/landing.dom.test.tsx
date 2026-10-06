/**
 * The single-page landing, rendered.
 *
 * ⚠ THE LANDING IS THE PRODUCT NOW, NOT A PITCH FOR IT. It is the by-major grid
 * a professor drills, a "general classes" menu into the shared core, and one
 * standing button to a recommendation. So these tests assert the grid, the core
 * menu, the exits, and — the expensive one — that an all-seeded board still
 * discloses itself here, on the one page a professor is guaranteed to see.
 *
 * ⚠ THE TOP-LEVEL MATRIX ITSELF is exercised in `explore-matrix.test.ts`; this
 * file only proves the landing PAGE wires it up, discloses seeded data above it,
 * and degrades calmly when the API is down.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { board, result, task } from "./fixtures";
import { expectPeerVoice } from "./voice";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

const { default: LandingPage } = await import("@/app/(site)/page");

const MAJOR = "management-information-systems";

/** One measured MIS 200 score — the default task's family is mis200-is-concepts. */
function measuredBoard() {
  return board([
    task({
      has_results: true,
      best_model_key: "luna",
      results: [result({ mean_score: 0.72, scored_count: 20, sample_count: 20 })],
    }),
  ]);
}

async function renderLanding(response: unknown = measuredBoard()) {
  getLeaderboard.mockResolvedValue(response);
  render(await LandingPage());
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the by-major grid", () => {
  it("is drawn as the comparison matrix, with the majors as columns", async () => {
    await renderLanding();
    expect(document.querySelector("table.cg-grid.xp-matrix"), "the landing is not a grid").not.toBeNull();
    const headings = Array.from(document.querySelectorAll(".xp-col-heading")).map((n) => n.textContent);
    expect(headings).toContain("MIS");
    expect(headings).toContain("GBA");
  });

  it("renders a measured score as a whole-number percent", async () => {
    await renderLanding();
    const score = document.querySelector("td.cg-measured .cg-score");
    expect(score, "no measured cell on the landing grid").not.toBeNull();
    expect(score!.textContent).toBe("72%");
  });
});

describe("the general-classes menu", () => {
  it("lists the shared-core classes, each linking to its class page", async () => {
    await renderLanding();
    const grid = document.querySelector(".core-grid");
    expect(grid, "no general-classes grid").not.toBeNull();
    const hrefs = Array.from(grid!.querySelectorAll<HTMLAnchorElement>("a.core-tile")).map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toContain(`/explore/${MAJOR}/mis-200`);
    expect(hrefs).toContain("/explore/general-business/gba-300");
  });

  it("shows the one measured core class's score, and 'not measured yet' for the rest", async () => {
    await renderLanding();
    const tiles = Array.from(document.querySelectorAll(".core-tile"));
    const mis200 = tiles.find((t) => t.textContent?.includes("MIS 200"))!;
    const gba300 = tiles.find((t) => t.textContent?.includes("GBA 300"))!;
    expect(mis200.textContent).toContain("72%");
    expect(gba300.textContent).toMatch(/Not measured yet/i);
  });
});

describe("the standing exits", () => {
  it("points the recommend button at /recommend and the method link at /methodology", async () => {
    await renderLanding();
    const hrefs = Array.from(document.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("/recommend");
    expect(hrefs).toContain("/methodology");
  });
});

describe("the landing's honesty", () => {
  it("discloses an all-seeded board above the grid", async () => {
    await renderLanding(
      board([
        task({
          has_results: true,
          results: [result({ mean_score: 0.9, scored_count: 10, demonstration: true })],
        }),
      ]),
    );
    const notice = document.querySelector(".notice");
    expect(notice, "a fully seeded board rendered no demonstration notice").not.toBeNull();
    expect(notice!.textContent).toMatch(/illustrative/i);
  });

  it("shows no demonstration notice when the numbers are real", async () => {
    await renderLanding();
    expect(document.querySelector(".notice")).toBeNull();
  });
});

describe("the landing's resilience", () => {
  it("shows the calm fallback, not a crash, when the API is down", async () => {
    getLeaderboard.mockRejectedValue(new Error("connect ECONNREFUSED"));
    await expect(LandingPage()).resolves.toBeTruthy();
    render(await LandingPage());
    expect(document.querySelector(".unavailable")).not.toBeNull();
    expect(document.querySelector("table.cg-grid")).toBeNull();
  });
});

describe("the landing, written to a peer", () => {
  it("does not narrate itself, plead its case, or date itself", async () => {
    await renderLanding();
    expectPeerVoice(document.body.textContent!, expect);
  });

  it("names its primary action as a recommendation, not a wall of data", async () => {
    await renderLanding();
    expect(screen.getByText(/Help me choose a model/i)).toBeTruthy();
  });
});
