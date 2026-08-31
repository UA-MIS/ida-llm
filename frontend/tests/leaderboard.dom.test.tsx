/**
 * The legibility layer, rendered.
 *
 * ⚠ WHAT THIS TESTS THAT `findings.test.ts` AND `glossary.test.ts` CANNOT.
 * Those two prove the RULES are right — that a tie is never called, that a stub
 * is never crowned, that no definition is written in jargon. This file proves
 * the PAGE actually puts them in front of a reader, in the right order.
 *
 * That distinction is the whole reason `landing.dom.test.tsx` exists, and it
 * applies twice as hard here. Every failure below leaves a page that builds,
 * lints, type-checks and renders perfectly — and quietly fails the one visitor
 * the layer was built for:
 *
 *   1. The summary computed but rendered below the table, so the reader meets
 *      seventy decimals before the sentence explaining them.
 *   2. The caveats tucked into a `<details>` "to tidy up", which publishes the
 *      claim without its qualifiers.
 *   3. The glossary present but empty, or its "?" buttons rendered with no
 *      definition attached — an affordance that promises help and gives none.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LEADERBOARD_TERMS, lookup } from "@/lib/glossary";

import { board, result, task } from "./fixtures";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

const { default: LeaderboardPage } = await import("@/app/(site)/leaderboard/page");

/** The page takes `searchParams` as a promise; no filters is the default view. */
async function renderBoard(response: ReturnType<typeof board>) {
  getLeaderboard.mockResolvedValue(response);
  render(await LeaderboardPage({ searchParams: Promise.resolve({}) }));
}

/** Two real models, comfortably apart, on one measured task. */
function twoRankedModels() {
  return board([
    task({
      has_results: true,
      best_model_key: "luna",
      results: [
        result({ model_key: "luna", display_name: "Luna", mean_score: 0.86 }),
        result({ model_key: "atlas", display_name: "Atlas", mean_score: 0.41 }),
      ],
    }),
    task({ task_id: "slo4/ethics", slo: "SLO4", title: "Ethical reasoning" }),
  ]);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the plain-language summary", () => {
  it("puts a human sentence on the page before any table", async () => {
    await renderBoard(twoRankedModels());

    const summary = document.querySelector(".plain-summary");
    expect(summary, "no plain-language summary rendered").not.toBeNull();
    expect(summary!.textContent).toContain("Luna");
    expect(summary!.textContent).toContain("0.86");
  });

  /**
   * ⚠ THE ORDERING ASSERTION, AND IT IS THE POINT OF THE WHOLE BRANCH. "Short,
   * then visual, then the full detail" is a claim about DOCUMENT ORDER. A
   * summary rendered after the ranked table is a summary nobody reads.
   */
  it("renders that sentence above the ranked table, not below it", async () => {
    await renderBoard(twoRankedModels());

    const summary = document.querySelector(".plain-summary");
    const table = document.querySelector("table.leaderboard");
    expect(summary).not.toBeNull();
    expect(table).not.toBeNull();

    // DOCUMENT_POSITION_FOLLOWING === 4: the table comes after the summary.
    expect(summary!.compareDocumentPosition(table!) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  /**
   * The headline travels — quoted in a meeting, pasted into an email. If the
   * caveats are one click away, the claim gets published without them.
   */
  it("shows the caveats alongside the claim, never behind a toggle", async () => {
    await renderBoard(twoRankedModels());

    const caveats = document.querySelector(".plain-summary-caveats");
    expect(caveats, "the caveats are not rendered at all").not.toBeNull();
    expect(caveats!.querySelectorAll("li").length).toBeGreaterThan(0);
    expect(
      caveats!.closest("details"),
      "the caveats have been hidden inside a collapsible section",
    ).toBeNull();
  });

  it("draws the visual comparison between the sentence and the table", async () => {
    await renderBoard(twoRankedModels());

    const podium = document.querySelector(".podium");
    expect(podium, "no visual comparison rendered").not.toBeNull();
    // Both ranked models get a bar; the bar is what makes the gap legible.
    expect(podium!.querySelectorAll(".podium-row")).toHaveLength(2);
    expect(podium!.querySelectorAll(".scorebar-fill").length).toBe(2);
  });

  /**
   * ⚠ THE SENTENCE THIS PROJECT MUST NEVER PUBLISH. A stub returns a fixed
   * answer and therefore scores brilliantly. "Mock comes out ahead overall" is
   * one missing `filter` away at all times, and it would appear in the largest
   * type on the page.
   */
  it("never crowns a test stub, in words or in a bar", async () => {
    await renderBoard(
      board([
        task({
          has_results: true,
          best_model_key: null,
          results: [
            result({
              model_key: "mock",
              display_name: "Mock",
              recommendable: false,
              mean_score: 0.99,
            }),
          ],
        }),
      ]),
    );

    const summary = document.querySelector(".plain-summary");
    expect(summary).not.toBeNull();
    expect(summary!.textContent).not.toContain("Mock");
    expect(summary!.textContent).not.toMatch(/0\.99/);
    expect(document.querySelector(".podium")).toBeNull();
  });

  it("refuses to separate two models that are level", async () => {
    await renderBoard(
      board([
        task({
          has_results: true,
          best_model_key: "luna",
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.74 }),
            result({ model_key: "atlas", display_name: "Atlas", mean_score: 0.72 }),
          ],
        }),
      ]),
    );

    const summary = document.querySelector(".plain-summary");
    expect(summary!.textContent).toMatch(/close enough|about level/i);
    expect(summary!.textContent).not.toMatch(/comes out ahead/i);
  });
});

describe("the orientation panel", () => {
  it("is on the page and open, because the reader it is for does not know to open it", async () => {
    await renderBoard(twoRankedModels());

    const panel = document.querySelector<HTMLDetailsElement>(".how-to-read");
    expect(panel, "no 'how to read this' panel").not.toBeNull();
    expect(panel!.open, "the orientation panel ships collapsed").toBe(true);
  });

  it("orients the reader before it asks them to read a number", async () => {
    await renderBoard(twoRankedModels());

    const panel = document.querySelector(".how-to-read")!;
    // The three things a cold reader most needs: the scale, that a gap is not a
    // zero, and that every number opens onto its evidence.
    expect(panel.textContent).toMatch(/0\.00 to 1\.00/);
    expect(panel.textContent).toMatch(/not measured yet/i);
    expect(panel.textContent).toMatch(/proof|record/i);
  });
});

describe("the glossary", () => {
  it("renders a definition for every word the page claims to explain", async () => {
    await renderBoard(twoRankedModels());

    const panel = document.querySelector(".glossary");
    expect(panel, "no glossary panel rendered").not.toBeNull();

    const definitions = within(panel as HTMLElement).getAllByRole("definition");
    expect(definitions).toHaveLength(LEADERBOARD_TERMS.length);

    for (const id of LEADERBOARD_TERMS) {
      const entry = lookup(id)!;
      expect(
        panel!.textContent,
        `the glossary panel is missing "${entry.term}"`,
      ).toContain(entry.term);
    }
  });

  /**
   * ⚠ A DEAD "?" IS WORSE THAN NO "?". It promises help to the exact reader who
   * needed it and then does nothing. Every inline term must carry its full
   * definition in the native `title`, because that is the floor that works
   * everywhere — including inside a scrolling table, where the drawn card is
   * clipped by `overflow-x`.
   */
  it("gives every inline '?' a real definition to open", async () => {
    await renderBoard(twoRankedModels());

    const terms = document.querySelectorAll("button.term");
    expect(terms.length, "no inline glossary terms on the page").toBeGreaterThan(0);

    for (const term of terms) {
      const title = term.getAttribute("title") ?? "";
      expect(title.length, `an inline term renders with no definition: ${term.textContent}`)
        .toBeGreaterThan(20);
      // The card is the enhancement; it must still be there for a mouse.
      expect(term.querySelector(".term-card")).not.toBeNull();
    }
  });

  /**
   * The glossary is a reading aid, not a nav item. If it grabs focus order or
   * gets announced as a heading it competes with the content it explains.
   */
  it("stays collapsed so it cannot bury the results", async () => {
    await renderBoard(twoRankedModels());

    const panel = document.querySelector<HTMLDetailsElement>(".glossary");
    expect(panel!.open).toBe(false);
  });
});

describe("what the legibility layer must not have changed", () => {
  it("still ranks the models in the table below", async () => {
    await renderBoard(twoRankedModels());

    const table = document.querySelector("table.leaderboard")!;
    const rows = table.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0]!.textContent).toContain("Luna");
    expect(rows[1]!.textContent).toContain("Atlas");
  });

  it("still shows the honest empty state when nothing has been measured", async () => {
    await renderBoard(board([task(), task()]));

    expect(await screen.findByText(/No benchmark results yet/i)).toBeTruthy();
    // No summary is rendered here, because there is nothing to summarise — and
    // the empty state already says so at length.
    expect(document.querySelector(".plain-summary")).toBeNull();
  });

  it("still carries the standing trust legend", async () => {
    await renderBoard(twoRankedModels());
    expect(document.querySelector(".legend")).not.toBeNull();
  });
});
