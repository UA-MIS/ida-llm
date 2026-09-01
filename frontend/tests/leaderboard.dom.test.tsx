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
import { expectPeerVoice } from "./voice";

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
   * definition in the native `title`, for a sighted mouse user, AND in an
   * `.sr-only` span — QA-24: `title` alone is not exposed to touch screen
   * readers or voice control at all, so it cannot be the only way in.
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
      // And the part that actually reaches every assistive technology.
      const srOnly = term.querySelector(".sr-only");
      expect(
        srOnly,
        `an inline term has no .sr-only definition, so touch screen readers and voice control cannot reach it: ${term.textContent}`,
      ).not.toBeNull();
      expect(srOnly!.textContent!.length).toBeGreaterThan(10);
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

/**
 * QA-24: the "also measured" drawer table (unranked / excluded models) had
 * no `<thead>` at all — nine columns of numbers with zero header
 * association for anyone navigating by table structure rather than sight.
 */
describe("the also-measured table's headers", () => {
  it("has a <thead> with a header for every column, scoped to its column", async () => {
    await renderBoard(
      board([
        task({
          has_results: true,
          best_model_key: "luna",
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.876 }),
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

    const table = document.querySelector("table.leaderboard-muted");
    expect(table, "no also-measured table rendered").not.toBeNull();

    const thead = table!.querySelector("thead");
    expect(thead, "the also-measured table has no <thead>").not.toBeNull();

    const headers = thead!.querySelectorAll("th");
    expect(headers.length).toBeGreaterThan(0);
    for (const header of headers) {
      expect(
        header.getAttribute("scope"),
        `<th> "${header.textContent}" has no scope="col"`,
      ).toBe("col");
    }
    expect(thead!.textContent).toContain("Model");
    expect(thead!.textContent).toContain("Confidence");
  });
});

/**
 * QA-32: a task's `<h3>` used to nest inside its outcome's `<h3>`, giving a
 * child section the same heading level as its parent — a skim by heading
 * level could not tell the two apart.
 */
describe("the drilled-down task's heading level", () => {
  it("nests below the outcome heading instead of matching it", async () => {
    getLeaderboard.mockResolvedValue(twoRankedModels());
    render(
      await LeaderboardPage({
        searchParams: Promise.resolve({ task: "slo2/l3-break-even" }),
      }),
    );

    const outcomeHeading = document.querySelector(".outcome-heading h3");
    expect(outcomeHeading, "no outcome heading rendered").not.toBeNull();

    const taskHeading = document.querySelector(".task-title");
    expect(taskHeading, "no task heading rendered").not.toBeNull();
    expect(taskHeading!.tagName).toBe("H4");
  });
});

/**
 * QA-21: the filter bar is a GET form with three controls (outcome, search,
 * "include unmeasured"). Submitting it replaces the entire query string, so
 * without hidden inputs it silently drops `task`, `use_mode` and `benchmark`
 * — a reader who arrives on a task deep link and touches the filter watches
 * the page quietly expand to the whole catalogue.
 */
describe("the filter bar preserves params it does not own", () => {
  it("carries task, use_mode and benchmark forward as hidden inputs", async () => {
    getLeaderboard.mockResolvedValue(twoRankedModels());
    render(
      await LeaderboardPage({
        searchParams: Promise.resolve({
          task: "slo4/ethics",
          use_mode: "write",
          benchmark: "1",
        }),
      }),
    );

    const form = document.querySelector("form.filter-bar") as HTMLFormElement;
    expect(form, "no filter form rendered").not.toBeNull();
    expect((form.querySelector('input[name="task"]') as HTMLInputElement | null)?.value).toBe(
      "slo4/ethics",
    );
    expect(
      (form.querySelector('input[name="use_mode"]') as HTMLInputElement | null)?.value,
    ).toBe("write");
    expect(
      (form.querySelector('input[name="benchmark"]') as HTMLInputElement | null)?.value,
    ).toBe("1");
  });

  it("omits those hidden inputs entirely when the params are not set", async () => {
    await renderBoard(twoRankedModels());

    const form = document.querySelector("form.filter-bar") as HTMLFormElement;
    expect(form.querySelector('input[name="task"]')).toBeNull();
    expect(form.querySelector('input[name="use_mode"]')).toBeNull();
    expect(form.querySelector('input[name="benchmark"]')).toBeNull();
  });

  it("still lets the outcome/search/unmeasured controls submit normally alongside the hidden ones", async () => {
    getLeaderboard.mockResolvedValue(twoRankedModels());
    render(
      await LeaderboardPage({
        searchParams: Promise.resolve({ task: "slo4/ethics", q: "ethics" }),
      }),
    );

    const form = document.querySelector("form.filter-bar") as HTMLFormElement;
    expect(form.querySelector("select#slo")).not.toBeNull();
    expect((form.querySelector("input#q") as HTMLInputElement).value).toBe("ethics");
    expect((form.querySelector('input[name="task"]') as HTMLInputElement).value).toBe(
      "slo4/ethics",
    );
  });
});

/**
 * D-92: the demonstration-data tell.
 *
 * ⚠ THE PAGE THE BUG REPORT NAMED. `/overview` already disclosed seeded rows;
 * this is the nav target — the page `PlainSummary` renders "Of the 2 AI
 * models measured, Luna comes out ahead: 0.88…" on, with the same seeded
 * numbers and, until this fix, no caveat anywhere on the page. Both
 * directions matter: a seeded model must be flagged, and a real one must
 * never be.
 */
describe("the demonstration-data tell", () => {
  function mixedBoard() {
    return board([
      task({
        has_results: true,
        best_model_key: "vega",
        results: [
          result({ model_key: "luna", display_name: "Luna", mean_score: 0.9, demonstration: true }),
          result({ model_key: "vega", display_name: "Vega", mean_score: 0.86, demonstration: false }),
        ],
      }),
    ]);
  }

  it("flags a seeded model's row in the ranked table", async () => {
    await renderBoard(mixedBoard());

    const rows = document.querySelectorAll("table.leaderboard tbody tr");
    const lunaRow = Array.from(rows).find((tr) => tr.textContent?.includes("Luna"))!;
    expect(
      lunaRow.querySelector(".badge-demo"),
      "a seeded model's row carries no demonstration tell",
    ).not.toBeNull();
  });

  it("never flags a model that was actually measured", async () => {
    await renderBoard(mixedBoard());

    const rows = document.querySelectorAll("table.leaderboard tbody tr");
    const vegaRow = Array.from(rows).find((tr) => tr.textContent?.includes("Vega"))!;
    expect(
      vegaRow.querySelector(".badge-demo"),
      "a real measurement was labelled illustrative",
    ).toBeNull();
  });

  it("shows a page-level notice above the plain-language summary when any row is seeded", async () => {
    await renderBoard(mixedBoard());

    const notice = document.querySelector(".notice");
    expect(notice, "no page-level demonstration notice rendered").not.toBeNull();
    expect(notice!.textContent!.toLowerCase()).toMatch(/illustrat/);

    // ⚠ HIGH ON THE PAGE, NOT BELOW THE CLAIM IT QUALIFIES. `PlainSummary` is
    // where "Luna comes out ahead" gets written in the largest type on the
    // page; a disclosure a reader meets after that sentence has disclosed
    // nothing.
    const summary = document.querySelector(".plain-summary")!;
    expect(
      notice!.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING,
      "the notice must sit above the plain-language summary, not below it",
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("stays silent — no notice, no badge — when nothing is seeded", async () => {
    await renderBoard(twoRankedModels());

    expect(document.querySelector(".notice")).toBeNull();
    expect(document.querySelector(".badge-demo")).toBeNull();
  });
});

/* --------------------------------------------------------- the copy itself */

describe("the leaderboard, written to a peer", () => {
  it("does not narrate itself, plead its case, or date itself", async () => {
    await renderBoard(twoRankedModels());

    // ⚠ SWEEPS THE WHOLE BODY, WHICH INCLUDES THE SHARED COMPONENTS. The
    // orientation panel, the standing trust legend and the glossary all render
    // here, so this is the one place their copy is measured against a real
    // page rather than in isolation.
    expectPeerVoice(document.body.textContent!, expect);
  });

  /**
   * ⚠ THE SAME SEAM PR #67 CLOSED ON `/overview`, ONE COMPONENT OVER. The
   * summary's link read `Open {display_name}&rsquo;s report card` — an
   * apostrophe glued onto an interpolated name. One reflow of that JSX puts the
   * name and the apostrophe on separate lines and JSX inserts a space between
   * them, which is how the overview shipped "Luna (…) 's full report card". The
   * possessive is gone here too, so the seam cannot reopen.
   */
  it("names the model in the summary link with no punctuation seam", async () => {
    await renderBoard(
      board([
        task({
          has_results: true,
          best_model_key: "luna",
          results: [
            result({
              model_key: "luna",
              display_name: "Luna (Llama 3.1 8B)",
              mean_score: 0.86,
            }),
            result({ model_key: "atlas", display_name: "Atlas", mean_score: 0.41 }),
          ],
        }),
      ]),
    );

    const next = document.querySelector(".plain-summary-next")!;
    const link = next.querySelector("a")!;
    expect(link.textContent).toContain("Luna (Llama 3.1 8B)");
    expect(link.textContent, "a space landed before punctuation").not.toMatch(
      /\s+['’,.]/,
    );
    expect(next.textContent, "a space landed before the comma").not.toMatch(/\s+,/);
    expect(next.textContent, "doubled whitespace in the follow-on").not.toMatch(/\s\s/);
  });

  /**
   * The standing legend is a key to the labels a reader actually sees. It used
   * to head its two columns "Verifiable" and "Subjective" — the raw `TaskKind`
   * values that `plainTaskKind` exists to keep off the page, and that appear on
   * no badge anywhere. `honesty.dom.test.tsx` already proves the badges never
   * say "subjective"; this proves the legend explaining them does not either.
   */
  it("keys the legend to the words on the badges, not to the raw task kinds", async () => {
    await renderBoard(twoRankedModels());

    const legend = document.querySelector(".legend")!;
    expect(legend.textContent, "the legend still prints our taxonomy").not.toMatch(
      /subjective/i,
    );
    expect(legend.textContent).toMatch(/Checked by a program/);
    expect(legend.textContent).toMatch(/Marked by another AI/);
  });
});
