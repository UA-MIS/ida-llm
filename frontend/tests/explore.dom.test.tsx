/**
 * The four levels of `/explore`, rendered.
 *
 * ⚠ WHY THESE ARE NOT COVERED BY `explore.test.ts`. That file proves the rules
 * are computed correctly; this one proves the PAGE shows them. A drill-down that
 * classified a pairing as "not measured yet" and then rendered a bare tile would
 * pass every pure test in this directory while telling a professor the models
 * scored zero on their course. The honest empty states are the product, so they
 * are asserted where a reader would actually meet them.
 *
 * ⚠ THE THREE GRID LEVELS ARE THE COMPARISON MATRIX, AND THESE TESTS ASSERT
 * THAT SHAPE. Each of levels 1-3 renders `table.cg-grid` — literally the table
 * `/compare` renders, from the same components — with entities down the rows
 * and models across the columns. A test that only checked "some score appears
 * somewhere" would pass against a wall of cards again, which is the thing the
 * client rejected; so the assertions below are about cells, columns and rows.
 *
 * ⚠ THE PERSISTENT ESCAPE HATCH IS TESTED AT EVERY LEVEL, INDIVIDUALLY. The
 * client asked for it on every screen and never buried, which is exactly the
 * kind of requirement that survives review, ships on three of four pages, and
 * is discovered by the person it was built for. Four assertions, one per level,
 * rather than one assertion on a shared component.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { board, CURRICULUM, result, task } from "./fixtures";
import { expectPeerVoice } from "./voice";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

const notFound = vi.hoisted(() =>
  vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
);
vi.mock("next/navigation", () => ({ notFound }));

const { default: ExplorePage } = await import("@/app/(site)/explore/page");
const { default: CoursesPage } = await import("@/app/(site)/explore/[major]/page");
const { default: OutcomesPage } = await import("@/app/(site)/explore/[major]/[course]/page");
const { default: EvidencePage } = await import(
  "@/app/(site)/explore/[major]/[course]/[slo]/page"
);

const MAJOR = "bscba-general-business-core";

/** The fixture curriculum plus Teamwork, which no text benchmark can measure. */
const WITH_TEAMWORK = {
  ...CURRICULUM,
  outcomes: [
    ...CURRICULUM.outcomes,
    {
      id: "SLO5",
      title: "Teamwork",
      statement: "Students demonstrate ability to work effectively on teams.",
      text_benchmarkable: false,
      benchmark_note: "OUT OF SCOPE for a text benchmark, and deliberately not faked.",
    },
  ],
  coverage: [
    { course: "MIS 200", title: "Fundamentals of MIS", outcomes: { SLO2: "A" } },
    {
      course: "GBA 300",
      title: "Business Communications",
      outcomes: { SLO2: "R", SLO4: "A", SLO5: "M+A" },
    },
  ],
};

function measuredBoard(overrides = {}) {
  return board(
    [
      task({
        task_id: "slo2/break-even",
        slo: "SLO2",
        has_results: true,
        best_model_key: "luna",
        results: [result({ mean_score: 0.72, scored_count: 20, sample_count: 20 })],
      }),
      task({ task_id: "slo4/ethics", slo: "SLO4", has_results: false, results: [] }),
    ],
    overrides,
  );
}

/**
 * ⚠ A THUNK, NOT A PROMISE. Taking `ExplorePage()` as an argument would invoke
 * the page BEFORE the line that sets the mock, so every level would render
 * against whichever board the previous test happened to leave behind —
 * `vi.clearAllMocks()` clears calls, not implementations. Two assertions passed
 * for that reason before this was a thunk, which is the worst possible way for
 * a fixture to be wrong.
 */
async function renderLevel(
  page: () => Promise<React.ReactElement>,
  response: unknown,
) {
  getLeaderboard.mockResolvedValue(response);
  render(await page());
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------

describe("the escape hatch is on every level", () => {
  const levels: [string, () => Promise<React.ReactElement>][] = [
    ["programmes", () => ExplorePage()],
    ["courses", () => CoursesPage({ params: Promise.resolve({ major: MAJOR }) })],
    [
      "outcomes",
      () =>
        OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
    ],
    [
      "evidence",
      () =>
        EvidencePage({
          params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo2" }),
        }),
    ],
  ];

  for (const [name, page] of levels) {
    it(`offers a recommendation instead, on the ${name} level`, async () => {
      getLeaderboard.mockResolvedValue(measuredBoard());
      render(await page());

      const cta = document.querySelector<HTMLAnchorElement>("a.xp-help-cta");
      expect(cta, `the ${name} level has no way out to a recommendation`).not.toBeNull();
      expect(cta!.getAttribute("href")).toBe("/recommend");
      // Above the grid it belongs to, not below it: a reader who has to scroll
      // past the wall of tiles to find the escape hatch has already met the
      // wall of tiles.
      // `table.cg-grid` is the drill-down's grid now (levels 1-3), `table.
      // leaderboard` is level 4's evidence table, `.empty` is the honest
      // nothing-to-show state. A stale selector here would silently stop
      // checking the position and the test would still pass — which is how a
      // requirement ships on three levels out of four.
      const grid = document.querySelector("table.cg-grid, table.leaderboard, .empty");
      if (grid) {
        expect(
          cta!.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING,
          `the escape hatch sits below the content on the ${name} level`,
        ).toBeTruthy();
      }
    });

    it(`offers a plain explanation on the ${name} level`, async () => {
      getLeaderboard.mockResolvedValue(measuredBoard());
      render(await page());
      const more = document.querySelector(".xp-help-body");
      expect(more?.textContent?.length ?? 0).toBeGreaterThan(40);
    });
  }
});

describe("level 1 — the programmes", () => {
  it("names the programme and links into its courses", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    const link = document.querySelector<HTMLAnchorElement>(".xp-row-link");
    expect(link!.getAttribute("href")).toBe(`/explore/${MAJOR}`);
    expect(document.body.textContent).toContain("BScBA General Business (core)");
  });

  it("draws the comparison matrix, not a wall of cards", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    // The same table `/compare` renders, from the same components — see
    // `components/score-grid.tsx`. A restyled tile grid would not have it.
    const grid = document.querySelector("table.cg-grid.xp-matrix");
    expect(grid, "the programme level is not drawn as a matrix").not.toBeNull();

    // One column per model, plus the row's own "All models" headline.
    const headers = Array.from(grid!.querySelectorAll("thead th")).map((th) =>
      th.textContent?.trim(),
    );
    expect(headers[0]).toBe("Programme");
    expect(headers.some((h) => h?.includes("Luna"))).toBe(true);
    expect(headers.at(-1)).toBe("All models");

    // Every model column carries a real cell on the one programme row.
    const row = grid!.querySelector("tbody tr")!;
    expect(row.querySelectorAll("td.cg-cell")).toHaveLength(headers.length - 1);
  });

  it("says so, with the reason, when the deployment has no curriculum map", async () => {
    await renderLevel(
      () => ExplorePage(),
      board([], {
        curriculum: {
          available: false,
          unavailable_reason: "No curriculum/slo.yaml in this deployment.",
          program: null,
          source: null,
          outcomes: [],
          use_modes: [],
          coverage: [],
        },
      }),
    );
    expect(document.querySelector(".xp-tile")).toBeNull();
    expect(document.body.textContent).toContain("No curriculum/slo.yaml");
  });

  it("discloses seeded rows above the grid they qualify", async () => {
    await renderLevel(
      () => ExplorePage(),
      board([
        task({
          task_id: "slo2/a",
          slo: "SLO2",
          has_results: true,
          results: [result({ mean_score: 0.9, scored_count: 10, demonstration: true })],
        }),
      ]),
    );
    const notice = document.querySelector(".notice");
    expect(notice, "a fully seeded board renders no demonstration notice").not.toBeNull();
    expect(notice!.textContent).toMatch(/illustrative/i);
  });
});

describe("level 2 — the courses", () => {
  it("draws one matrix row per course, in the published map's order", async () => {
    await renderLevel(
      () => CoursesPage({ params: Promise.resolve({ major: MAJOR }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const headings = Array.from(document.querySelectorAll(".xp-row-eyebrow")).map(
      (n) => n.textContent,
    );
    // ⚠ MAP ORDER, NEVER SCORE ORDER. A matrix makes sorting by the headline
    // column tempting, and doing it would turn a coverage grid into a ranking
    // of a department's own courses — a claim about them, not about us.
    expect(headings).toEqual(["MIS 200", "GBA 300"]);
  });

  it("opens each course row into that course's outcomes", async () => {
    await renderLevel(
      () => CoursesPage({ params: Promise.resolve({ major: MAJOR }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const hrefs = Array.from(
      document.querySelectorAll<HTMLAnchorElement>(".xp-row-link"),
    ).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual([
      `/explore/${MAJOR}/mis-200`,
      `/explore/${MAJOR}/gba-300`,
    ]);
  });

  it("404s on a programme this platform does not have", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      CoursesPage({ params: Promise.resolve({ major: "no-such-programme" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });
});

describe("level 3 — the outcomes one course teaches", () => {
  it("shows the published level on every outcome it draws", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    expect(document.body.textContent).toContain("Assessment point");
  });

  it("shows an un-benchmarkable outcome rather than dropping it", async () => {
    // A course page that listed only the measurable outcomes would make GBA 300
    // look like a two-outcome course, which is a claim about the curriculum.
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "gba-300" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const rows = Array.from(document.querySelectorAll("table.cg-grid tbody tr"));
    expect(rows).toHaveLength(3);

    const teamwork = rows.find((r) => r.textContent?.includes("Teamwork"))!;
    expect(teamwork.querySelector(".xp-row")!.className).toContain(
      "xp-row-not_benchmarkable",
    );
    // ⚠ EVERY CELL ON THE ROW, THE HEADLINE INCLUDED. A grid where the
    // per-model cells said "out of scope" and the summary column said "not
    // measured" would be making two different claims about one row — and the
    // summary is the one a reader takes away.
    const cells = teamwork.querySelectorAll("td.cg-cell");
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell.className, "an out-of-scope row drew a measurable cell").toContain(
        "cg-out-of-scope",
      );
      expect(cell.textContent).toMatch(/not measurable by a text benchmark/i);
    }
    expect(teamwork.querySelector(".cg-score"), "a score on an unreachable outcome").toBeNull();
  });

  it("says 'not measured yet' rather than drawing a blank or a zero", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "gba-300" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const rows = Array.from(document.querySelectorAll("table.cg-grid tbody tr"));
    const ethics = rows.find((r) => r.textContent?.includes("Ethical Reasoning"))!;
    expect(ethics.querySelector(".xp-row")!.className).toContain("xp-row-not_measured");
    expect(ethics.querySelector(".cg-score"), "an unrun pairing shows a score").toBeNull();

    // ⚠ AN EMPTY CELL IS NEVER A BLANK. A dash with a reason behind it does not
    // read as a zero; an empty square does, to almost everybody.
    for (const cell of ethics.querySelectorAll("td.cg-cell")) {
      expect(cell.className).toContain("cg-unmeasured");
      // Per-model cells say "this model has no…"; the trailing All-models cell
      // says "no model has a…" — different squares, different claims, and
      // neither of them a blank.
      expect(cell.textContent).toMatch(
        /(this model has no|no model has a) finished, scored run|no task in the catalogue/i,
      );
    }
    // And the page says, in words, what the two glyphs mean.
    expect(document.querySelector(".xp-matrix-key")!.textContent).toContain(
      "Not measured yet",
    );
  });

  it("keeps the confidence tell beside every score it does show", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard(),
    );
    const measured = Array.from(document.querySelectorAll("td.cg-measured"));
    expect(measured.length).toBeGreaterThan(0);
    for (const cell of measured) {
      expect(cell.querySelector(".cg-score")!.textContent).toBe("0.72");
      // ⚠ NEVER OPTIONAL, NEVER DROPPED AT A BREAKPOINT: the number and how
      // much weight it can bear travel together or not at all.
      expect(
        cell.querySelector(".cg-confidence .confidence-pips"),
        "a score is shown with no tell for how much it can bear",
      ).not.toBeNull();
    }
  });

  it("puts the row's headline in the row, built from the same cells", async () => {
    // ⚠ THE DISAGREEMENT THIS REBUILD MAKES IMPOSSIBLE. The old tile grid
    // computed a course's headline on a card and its per-model detail on
    // another page; nothing structural stopped the two drifting. Here the
    // "All models" figure is the last cell of the row it summarises, so a
    // headline that claimed a score over a row of dashes would have to
    // contradict its own neighbours.
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "gba-300" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    for (const row of document.querySelectorAll("table.cg-grid tbody tr")) {
      const cells = Array.from(row.querySelectorAll("td.cg-cell"));
      const headline = cells.at(-1)!;
      const anyModelMeasured = cells
        .slice(0, -1)
        .some((c) => c.className.includes("cg-measured"));
      expect(
        headline.className.includes("cg-measured"),
        `${row.textContent?.slice(0, 40)}: headline and cells disagree`,
      ).toBe(anyModelMeasured);
    }
  });

  it("404s on a course the map does not list", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-999" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  // ⚠ THE GAP THIS FILE EXISTS TO CLOSE. `/explore`, `/explore/[major]` and the
  // evidence level all disclosed a seeded score; this page rendered the
  // identical flag as a flat, uncaveated finding. Both directions pinned here,
  // same as `explore.test.ts` pins the rule that feeds it.
  it("discloses a seeded score above the grid, same words as every other level", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      board([
        task({
          task_id: "slo2/break-even",
          slo: "SLO2",
          has_results: true,
          results: [result({ mean_score: 0.9, scored_count: 10, demonstration: true })],
        }),
      ]),
    );
    const notice = document.querySelector(".notice");
    expect(notice, "a seeded course score rendered no demonstration notice").not.toBeNull();
    expect(notice!.textContent).toMatch(/illustrative/i);

    // Self-clears per row too — the badge sits beside the level badge in the
    // row header, not just in a page-wide banner a reader can miss.
    const row = Array.from(document.querySelectorAll("table.cg-grid tbody tr")).find(
      (r) => r.querySelector("td.cg-measured"),
    )!;
    expect(
      row.querySelector(".badge-demo"),
      "no per-row seeded badge on the measured outcome",
    ).not.toBeNull();

    // And on the axis it actually qualifies: a seeded model's whole COLUMN is
    // illustrative, the way a seeded model's whole row is on `/compare`.
    expect(
      document.querySelector("thead .badge-demo"),
      "no seeded badge on the model column it belongs to",
    ).not.toBeNull();
  });

  it("renders no demonstration notice or badge when the course's scores are real", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard(),
    );
    expect(document.querySelector(".notice")).toBeNull();
    expect(document.querySelector(".badge-demo")).toBeNull();
  });
});

describe("level 4 — the evidence", () => {
  it("shows each model's read with its receipt", async () => {
    await renderLevel(
      () => EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo2" }),
      }),
      measuredBoard(),
    );
    const row = document.querySelector("table.leaderboard tbody tr")!;
    expect(row.textContent).toContain("Luna");
    expect(row.querySelector(".col-score")!.textContent).toBe("0.72");
    expect(row.querySelector(".col-trust .confidence-pips")).not.toBeNull();
    expect(row.querySelector<HTMLAnchorElement>(".col-go a")!.getAttribute("href")).toBe(
      "/runs/run_1",
    );
  });

  it("quotes the curriculum on how the outcome is scored", async () => {
    await renderLevel(
      () => EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo2" }),
      }),
      measuredBoard(),
    );
    expect(document.body.textContent).toContain("Straightforwardly checkable");
  });

  it("says nothing was run, and why, for an outcome out of scope", async () => {
    await renderLevel(
      () => EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: "gba-300", slo: "slo5" }),
      }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    expect(document.querySelector("table.leaderboard")).toBeNull();
    expect(document.body.textContent).toContain("deliberately");
    expect(document.body.textContent).toContain("OUT OF SCOPE");
  });

  it("says 'not measured yet' rather than showing an empty table", async () => {
    await renderLevel(
      () => EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: "gba-300", slo: "slo4" }),
      }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    expect(document.querySelector("table.leaderboard")).toBeNull();
    expect(document.body.textContent).toContain("Not measured yet");
    // ⚠ AND IT SAYS WHOSE GAP IT IS. "No model scored" and "we have not run
    // this" are different claims and only the second one is true here.
    expect(document.body.textContent).toContain("a gap in what we have run");
  });

  it("carries a breadcrumb back up every level", async () => {
    await renderLevel(
      () => EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo2" }),
      }),
      measuredBoard(),
    );
    const hrefs = Array.from(
      document.querySelectorAll<HTMLAnchorElement>(".xp-crumbs a"),
    ).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/explore", `/explore/${MAJOR}`, `/explore/${MAJOR}/mis-200`]);
    // The last crumb is where you are, and is not a link.
    expect(document.querySelector('.xp-crumbs [aria-current="page"]')!.textContent).toBe(
      "SLO2",
    );
  });

  it("404s on a pairing the map never marked", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo4" }),
      }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("the register", () => {
  it("keeps the peer voice on every level", async () => {
    // The client's verdict was that a screen you have to explain has failed.
    // These four pages are the response to it, so the tics that sweep names —
    // meta-narration, defensiveness, a claim with a shelf life — are exactly
    // what they must not reintroduce.
    for (const page of [
      () => ExplorePage(),
      () => CoursesPage({ params: Promise.resolve({ major: MAJOR }) }),
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      () =>
        EvidencePage({
          params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo2" }),
        }),
    ]) {
      getLeaderboard.mockResolvedValue(measuredBoard());
      render(await page());
      expectPeerVoice(document.body.textContent ?? "", expect);
      cleanup();
    }
  });
});
