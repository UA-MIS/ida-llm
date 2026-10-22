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

  it("shows acronyms only in the majors row — no full-name subtext", async () => {
    await renderLanding();
    expect(document.querySelectorAll("thead .xp-col-heading").length).toBeGreaterThan(0);
    expect(document.querySelector("thead .xp-col-name"), "a full name sits under an acronym").toBeNull();
    expect(document.querySelector("thead .xp-col-eyebrow"), "an eyebrow sits over an acronym").toBeNull();
    expect(document.querySelector("table.xp-matrix-acronyms")).not.toBeNull();
    // Still reachable by assistive tech and on hover.
    expect(document.querySelector("thead .xp-col-link .sr-only")!.textContent).toMatch(/\w/);
  });

  it("renders a measured score as a whole-number percent", async () => {
    await renderLanding();
    const score = document.querySelector("td.cg-measured .cg-score");
    expect(score, "no measured cell on the landing grid").not.toBeNull();
    expect(score!.textContent).toBe("72%");
  });
});

describe("the single measured-class tally", () => {
  // ⚠ ONCE, AT THE TOP — NOT PER MAJOR. The human asked for the measured-class
  // count as a single page summary rather than a number repeated on every major
  // column, so it lives in the subtitle and nowhere else.
  it("states how many classes are measured, in the subtitle", async () => {
    await renderLanding();
    const subtitle = document.querySelector(".hero .subtitle");
    expect(subtitle, "no hero subtitle").not.toBeNull();
    // One MIS 200 class is measured in the fixture board; the rest are not.
    expect(subtitle!.textContent).toMatch(/1 of \d+ class/i);
    expect(subtitle!.textContent).toMatch(/measured so far/i);
  });

  it("no longer carries a separate general-classes menu", async () => {
    await renderLanding();
    // The mockup's screen 01 is the by-major grid alone; the core-class menu is gone.
    expect(document.querySelector(".core-grid")).toBeNull();
  });
});

describe("the standing exits", () => {
  it("has no recommend button — the feature was removed whole", async () => {
    await renderLanding();
    const hrefs = Array.from(document.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    // The recommendation feature was removed whole — no /recommend exit.
    expect(hrefs).not.toContain("/recommend");
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

  it("offers no recommendation action — that feature was removed", async () => {
    await renderLanding();
    // The "Help me choose a model" CTA and every link to /recommend are gone.
    expect(screen.queryByText(/Help me choose/i)).toBeNull();
    const recommendLinks = Array.from(
      document.querySelectorAll<HTMLAnchorElement>("a"),
    ).filter((a) => a.getAttribute("href") === "/recommend");
    expect(recommendLinks).toHaveLength(0);
  });
});
