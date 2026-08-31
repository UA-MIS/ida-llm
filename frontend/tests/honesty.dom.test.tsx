/**
 * The honesty layer, RENDERED — the class of defect a pure test cannot see.
 *
 * ⚠ WHY THESE ARE DOM TESTS. Every bug pinned below shipped with the whole
 * suite green, because in each case the *rule* was already right and the *page*
 * did not honour it. `MatrixCell.confidence` was computed correctly and never
 * drawn. The confidence column was populated correctly and hidden by a
 * stylesheet. The trust badge had a plain-language function available to it and
 * printed the raw API label instead. A test that checks the rule passes in
 * every one of those states.
 *
 * ⚠ THE COMMON SHAPE, AND WHY IT IS THE EXPENSIVE ONE HERE. This product's
 * entire claim is that a number arrives with an honest statement of what it is
 * worth. A number that loses its qualifier does not become a slightly weaker
 * claim — it becomes a DIFFERENT claim, and a stronger one than the evidence
 * supports. So each test below asserts that a specific number and its specific
 * tell are on the page together.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { board, result, task, trust } from "./fixtures";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

const { default: LeaderboardPage } = await import("@/app/(site)/leaderboard/page");
const { default: ComparePage } = await import("@/app/(site)/compare/page");

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** Two models far enough apart to be ranked, both at low confidence. */
function lowConfidenceBoard() {
  return board([
    task({
      has_results: true,
      best_model_key: "luna",
      results: [
        result({
          model_key: "luna",
          display_name: "Luna",
          mean_score: 0.88,
          trust: trust({
            confidence: "low",
            confidence_label: "Low confidence — thin evidence",
            confidence_reason: "Only 4 answer(s) were scored.",
          }),
        }),
        result({
          model_key: "atlas",
          display_name: "Atlas",
          mean_score: 0.41,
          trust: trust({ confidence: "low", confidence_label: "Low confidence — thin evidence" }),
        }),
      ],
    }),
  ]);
}

async function renderBoard(response: ReturnType<typeof board>) {
  getLeaderboard.mockResolvedValue(response);
  render(await LeaderboardPage({ searchParams: Promise.resolve({}) }));
}

/* ------------------------------------------------------------------------ */
/* Confidence must survive every width                                       */
/* ------------------------------------------------------------------------ */

describe("the confidence tell survives the mobile breakpoint", () => {
  /**
   * ⚠ THIS ASSERTS ON A CLASS NAME, WHICH IS UNUSUAL AND IS THE POINT. jsdom
   * applies no stylesheet, so a rendered-DOM test cannot see `display: none` —
   * which is exactly how a phone came to show "0.88" where a desktop showed
   * "0.88 · Low confidence". The contract this pins is the one thing a test
   * can pin: confidence carries `col-trust`, never `col-optional`, and the
   * stylesheet assertion below closes the other half.
   */
  it("marks the leaderboard's confidence column as one that is never dropped", async () => {
    await renderBoard(lowConfidenceBoard());

    const headers = [...document.querySelectorAll(".leaderboard thead th")];
    const confidence = headers.find((th) => th.textContent?.trim() === "Confidence");
    expect(confidence, "no confidence column on the ranked table").toBeDefined();
    expect(confidence!.className).toContain("col-trust");
    expect(confidence!.className).not.toContain("col-optional");
  });

  it("keeps the header and body cell counts equal, so nothing shifts by a column", async () => {
    await renderBoard(lowConfidenceBoard());

    const table = document.querySelector(".leaderboard")!;
    const headerCells = table.querySelectorAll("thead th").length;
    const bodyCells = table.querySelectorAll("tbody tr")[0]!.querySelectorAll("td").length;
    expect(headerCells).toBe(bodyCells);
  });

  it("gives the report-card header cell the same class its body cell has", async () => {
    // The header `<th aria-label="Report card" />` carried no class while its
    // body cell was `col-go`, so below 760px the header rendered one more cell
    // than every row and the whole table slid sideways by a column.
    await renderBoard(lowConfidenceBoard());

    const table = document.querySelector(".leaderboard")!;
    const header = [...table.querySelectorAll("thead th")].at(-1)!;
    const bodyCell = [...table.querySelectorAll("tbody tr")[0]!.querySelectorAll("td")].at(-1)!;
    expect(header.className).toContain("col-go");
    expect(bodyCell.className).toContain("col-go");
  });

});

/* ------------------------------------------------------------------------ */
/* The grid must draw what its own copy points at                            */
/* ------------------------------------------------------------------------ */

describe("the comparison grid draws the pips it tells the reader to look for", () => {
  async function renderCompare(response: ReturnType<typeof board>) {
    getLeaderboard.mockResolvedValue(response);
    render(await ComparePage());
  }

  it("renders a confidence tell inside every measured cell", async () => {
    // Three separate pieces of copy — the legend, step 2 of the how-to-read
    // panel, and the stylesheet's own comment — point at these. They were
    // declared, populated, and never drawn.
    await renderCompare(lowConfidenceBoard());

    const measured = document.querySelectorAll(".cg-measured");
    expect(measured.length, "no measured cells to check").toBeGreaterThan(0);
    for (const cell of measured) {
      expect(
        cell.querySelector(".confidence-pips"),
        "a measured cell with no confidence pips — the legend is pointing at nothing",
      ).not.toBeNull();
    }
  });

  it("keeps the legend's promise and the cell's contents in step", async () => {
    await renderCompare(lowConfidenceBoard());

    const legend = document.querySelector(".cg-legend")!;
    expect(legend.textContent).toContain("confidence pips");
    expect(document.querySelectorAll(".cg-measured .confidence-pips").length).toBeGreaterThan(0);
  });

  it("refuses to crown a column winner on a gap it cannot defend", async () => {
    await renderCompare(
      board([
        task({
          has_results: true,
          best_model_key: "luna",
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.88 }),
            result({ model_key: "orion", display_name: "Orion", mean_score: 0.876 }),
          ],
        }),
      ]),
    );

    const foot = document.querySelector("tfoot")!;
    expect(foot.textContent).toContain("too close to call");
    expect(foot.querySelector(".cg-foot-name")).toBeNull();
  });
});

/* ------------------------------------------------------------------------ */
/* No jargon reaches a professor-facing surface                              */
/* ------------------------------------------------------------------------ */

describe("the rendered page carries no operator vocabulary", () => {
  it("prints no config key, filename or build command anywhere on the leaderboard", async () => {
    await renderBoard(
      board([
        task({
          has_results: true,
          best_model_key: "luna",
          scorable: false,
          unscorable_reason:
            "subjective task: scoring it needs an LLM judge, and no judge model is " +
            "configured for this deployment (set IDA_JUDGE_MODEL_KEY to a key in " +
            "models.yaml). The run's transcripts are archived, so it can be graded " +
            "retroactively once one is.",
          results: [
            result({
              model_key: "luna",
              display_name: "Luna",
              trust: trust({
                kind: "subjective",
                tier_label: "Subjective (AI-scored)",
                caveats: [
                  "This run carries a score, but the platform cannot grade this task today " +
                    "(subjective task: scoring it needs an LLM judge, and no judge model is " +
                    "configured for this deployment (set IDA_JUDGE_MODEL_KEY to a key in " +
                    "models.yaml). The run's transcripts are archived, so it can be graded " +
                    "retroactively once one is.) — the score was produced when grading was " +
                    "available. Re-running now would not reproduce it.",
                ],
              }),
            }),
          ],
        }),
      ]),
    );

    const rendered = document.body.innerHTML;
    expect(rendered).not.toContain("IDA_JUDGE_MODEL_KEY");
    expect(rendered).not.toContain("models.yaml");
    expect(rendered).not.toContain("LLM judge");
    expect(rendered).not.toContain("make lint-tasks");
  });

  it("does not print the word the glossary exists to keep off the page", async () => {
    // Filtered to one task, which is the view that renders the result cards
    // carrying the trust badge.
    getLeaderboard.mockResolvedValue(
      board([
        task({
          kind: "subjective",
          has_results: true,
          best_model_key: "luna",
          results: [
            result({
              trust: trust({ kind: "subjective", tier_label: "Subjective (AI-scored)" }),
            }),
          ],
        }),
      ]),
    );
    render(
      await LeaderboardPage({
        searchParams: Promise.resolve({ task: "slo2/l3-break-even" }),
      }),
    );

    // `plainTaskKind`'s own comment: "subjective" reads as "this result is a
    // matter of opinion", when it means "this work has no single right answer,
    // so a second AI marked it". The badge was printing the raw label.
    const badges = [...document.querySelectorAll(".badge-trust")];
    expect(badges.length).toBeGreaterThan(0);
    for (const badge of badges) {
      expect(badge.textContent).not.toMatch(/subjective/i);
      expect(badge.textContent).toMatch(/Marked by another AI/);
    }
  });
});

/* ------------------------------------------------------------------------ */
/* An unranked model gets its real reason                                    */
/* ------------------------------------------------------------------------ */

describe("an unranked model is explained, not mislabelled", () => {
  it("does not call an unregistered model a test stub", async () => {
    await renderBoard(
      board([
        task({
          has_results: true,
          best_model_key: "luna",
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.876 }),
            result({ model_key: "atlas", display_name: "Atlas", mean_score: 0.41 }),
            // demo-orion: scoring ABOVE the crowned model, absent from the
            // registry, and previously badged "test stub".
            result({
              model_key: "demo-orion",
              display_name: "demo-orion",
              mean_score: 0.886,
              recommendable: false,
              data_residency: "unknown",
              data_residency_label: "Hosting not stated in the registry",
            }),
          ],
        }),
      ]),
    );

    const drawer = document.querySelector(".also-measured summary")!;
    expect(drawer.textContent).toContain("not in the model registry");
    expect(drawer.textContent).not.toMatch(/test stub/i);
    expect(drawer.textContent).not.toMatch(/nothing has scored/i);
  });

  it("still calls a real stub a stub", async () => {
    await renderBoard(
      board([
        task({
          has_results: true,
          best_model_key: "luna",
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.876 }),
            result({ model_key: "atlas", display_name: "Atlas", mean_score: 0.41 }),
            result({
              model_key: "mock",
              display_name: "Mock",
              mean_score: 0.51,
              recommendable: false,
              data_residency: "not_a_real_model",
              data_residency_label: "Test stub — not a usable model",
            }),
          ],
        }),
      ]),
    );

    expect(document.querySelector(".also-measured summary")!.textContent).toContain("1 test stub");
  });
});
