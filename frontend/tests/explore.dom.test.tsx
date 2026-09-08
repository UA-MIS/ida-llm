/**
 * The four levels of `/explore`, rendered.
 *
 * ⚠ WHY THESE ARE NOT COVERED BY `explore.test.ts`. That file proves the rules
 * are computed correctly; this one proves the PAGE shows them. A drill-down that
 * classified a pairing as "not measured yet" and then rendered a bare cell would
 * pass every pure test in this directory while telling a professor the models
 * scored zero on their class. The honest empty states are the product, so they
 * are asserted where a reader would actually meet them.
 *
 * ⚠ THE ORIENTATION IS ASSERTED HERE, IN THE DOM, BECAUSE THAT IS WHERE IT IS A
 * CLAIM. Models are ROWS and entities are COLUMNS. A vertical list reads as a
 * ranking whether or not one was meant, so the axis running down the page has to
 * be the one where order means something. Transposing the grid back would break
 * nothing, fail nothing, and quietly start asserting that Accounting outranks
 * Marketing and that MIS 200 matters more than MIS 466.
 *
 * ⚠ THE THREE GRID LEVELS ARE THE COMPARISON MATRIX, AND THESE TESTS ASSERT
 * THAT SHAPE. Each of levels 1-3 renders `table.cg-grid` — literally the table
 * `/compare` renders, from the same components. A test that only checked "some
 * score appears somewhere" would pass against a wall of cards again, which is
 * the thing the client rejected; so the assertions below are about cells,
 * columns and rows.
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
const { default: ClassesPage } = await import("@/app/(site)/explore/[major]/page");
const { default: OutcomesPage } = await import("@/app/(site)/explore/[major]/[course]/page");
const { default: EvidencePage } = await import(
  "@/app/(site)/explore/[major]/[course]/[slo]/page"
);

const MAJOR = "management-information-systems";
const GEN = "general-business";

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
    { course: "MIS 200", title: "Fundamentals of MIS", outcomes: { SLO2: "A", SLO4: "R" } },
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
        family: "slo2",
        slo: "SLO2",
        has_results: true,
        best_model_key: "luna",
        results: [result({ mean_score: 0.72, scored_count: 20, sample_count: 20 })],
      }),
      task({ task_id: "slo4/ethics", family: "slo4", slo: "SLO4", has_results: false, results: [] }),
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

/** The grid's data rows — the models — without the "All models" summary. */
function modelRows(): HTMLTableRowElement[] {
  return Array.from(
    document.querySelectorAll<HTMLTableRowElement>("table.cg-grid tbody tr"),
  ).filter((row) => !row.classList.contains("xp-summary"));
}

function summaryRow(): HTMLTableRowElement {
  return document.querySelector<HTMLTableRowElement>("table.cg-grid tbody tr.xp-summary")!;
}

/** Column index of the entity whose header contains `text`. */
function columnOf(text: string): number {
  const headers = Array.from(document.querySelectorAll("table.cg-grid thead th.xp-col"));
  const index = headers.findIndex((th) => th.textContent?.includes(text));
  if (index < 0) throw new Error(`no column headed ${text}`);
  return index;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------

describe("the escape hatch is on every level", () => {
  const levels: [string, () => Promise<React.ReactElement>][] = [
    ["majors", () => ExplorePage()],
    ["classes", () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) })],
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
      // past the whole matrix to find the escape hatch has already met the
      // matrix.
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

    it(`has no how-to-read panel on the ${name} level`, async () => {
      // The client's point: a screen you must explain has failed. The
      // explanation is one collapsed line beside the button that skips it.
      getLeaderboard.mockResolvedValue(measuredBoard());
      render(await page());
      expect(document.querySelector(".how-to-read")).toBeNull();
      expect(document.body.textContent).not.toMatch(/how to read this/i);
    });
  }
});

// ---------------------------------------------------------------------------

describe("the orientation, in the DOM", () => {
  it("heads the row axis with the model and the column axis with the entity", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    const grid = document.querySelector("table.cg-grid.xp-matrix");
    expect(grid, "the majors level is not drawn as a matrix").not.toBeNull();

    const headers = Array.from(grid!.querySelectorAll("thead th")).map((th) =>
      th.textContent?.trim(),
    );
    // The corner names what a ROW is; the columns are the entities.
    expect(headers[0]).toBe("Model");
    expect(headers.some((h) => h?.includes("Management Information Systems"))).toBe(true);
    expect(headers.some((h) => h?.includes("General Business"))).toBe(true);
    expect(headers.at(-1)).toBe("All majors");
  });

  it("makes each model a row, with one cell per entity plus its own summary", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    const rows = modelRows();
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.querySelector("th.xp-model")).not.toBeNull();
      // Two majors in the fixture, plus the trailing across-the-level cell.
      expect(row.querySelectorAll("td.cg-cell")).toHaveLength(3);
    }
  });

  it("puts the 'All models' summary in the same table, as the last row", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    const summary = summaryRow();
    expect(summary, "no All-models summary row").not.toBeNull();
    expect(summary.querySelector("th")!.textContent).toBe("All models");
    expect(summary).toBe(
      document.querySelector("table.cg-grid tbody tr:last-child"),
    );
  });

  it("orders the model rows as a ranking, best first", async () => {
    await renderLevel(
      () => ExplorePage(),
      board([
        task({
          task_id: "slo2/a",
          family: "slo2",
          slo: "SLO2",
          has_results: true,
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.3 }),
            result({ model_key: "sol", display_name: "Sol", mean_score: 0.9 }),
          ],
        }),
      ]),
    );
    expect(
      modelRows().map((r) => r.querySelector("th")!.textContent?.trim()),
    ).toEqual(["Sol", "Luna"]);
  });

  it("keeps the entity columns in the catalog's order, never the score's", async () => {
    await renderLevel(
      () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const eyebrows = Array.from(document.querySelectorAll(".xp-col-eyebrow")).map(
      (n) => n.textContent,
    );
    expect(eyebrows).toEqual(["MIS 200", "MIS 221"]);
  });
});

// ---------------------------------------------------------------------------

describe("the three click targets", () => {
  it("opens a column header into the level below", async () => {
    await renderLevel(
      () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const hrefs = Array.from(
      document.querySelectorAll<HTMLAnchorElement>(".xp-col-link"),
    ).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual([`/explore/${MAJOR}/mis-200`, `/explore/${MAJOR}/mis-221`]);
  });

  it("opens a model row header into that model's report card", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    const link = modelRows()[0]!.querySelector<HTMLAnchorElement>("a.xp-model-link");
    expect(link, "the model row header is not a link").not.toBeNull();
    expect(link!.getAttribute("href")).toBe("/models/luna");
  });

  it("opens a score cell into the level below, carrying the model", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    const cell = document.querySelector("td.cg-measured")!;
    const link = cell.querySelector<HTMLAnchorElement>("a.cg-score");
    expect(link, "a measured cell is not clickable").not.toBeNull();
    expect(link!.getAttribute("href")).toBe(`/explore/${MAJOR}?model=luna`);
  });

  it("keeps the run receipt reachable from the evidence page", async () => {
    // The cell gave up its run link to carry the drill. The receipt is still
    // one level down, where the whole page is receipts.
    await renderLevel(
      () =>
        EvidencePage({
          params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo2" }),
        }),
      measuredBoard(),
    );
    expect(
      document
        .querySelector<HTMLAnchorElement>("table.leaderboard .col-go a")!
        .getAttribute("href"),
    ).toBe("/runs/run_1");
  });

  it("marks the model a cell click carried down, without reordering the grid", async () => {
    await renderLevel(
      () =>
        ClassesPage({
          params: Promise.resolve({ major: MAJOR }),
          searchParams: Promise.resolve({ model: "luna" }),
        }),
      measuredBoard(),
    );
    expect(document.querySelector(".xp-focus")!.textContent).toContain("Luna");
    const focused = document.querySelectorAll("tr.xp-model-focused");
    expect(focused).toHaveLength(1);
    expect(focused[0]!.querySelector("th")!.textContent).toContain("Luna");
    // A way back to the full field, one click away.
    expect(
      document
        .querySelector<HTMLAnchorElement>(".xp-focus a")!
        .getAttribute("href"),
    ).toBe(`/explore/${MAJOR}`);
  });

  it("ignores a ?model= that names nothing on this level", async () => {
    // A focus note for a model the grid does not contain would be a caption
    // describing a different page.
    await renderLevel(
      () =>
        ClassesPage({
          params: Promise.resolve({ major: MAJOR }),
          searchParams: Promise.resolve({ model: "nobody" }),
        }),
      measuredBoard(),
    );
    expect(document.querySelector(".xp-focus")).toBeNull();
    expect(document.querySelector("tr.xp-model-focused")).toBeNull();
  });
});

// ---------------------------------------------------------------------------

describe("level 1 — the majors", () => {
  it("names every major the college offers and links into its classes", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    const hrefs = Array.from(
      document.querySelectorAll<HTMLAnchorElement>(".xp-col-link"),
    ).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual([`/explore/${MAJOR}`, `/explore/${GEN}`]);
    expect(document.body.textContent).toContain("Management Information Systems");
  });

  it("shows the core courses no major owns rather than dropping them", async () => {
    await renderLevel(() => ExplorePage(), measuredBoard());
    expect(document.body.textContent).toContain("LGS 200");
    expect(document.body.textContent).toMatch(/no major owns this core course/i);
  });

  it("says so, with the reason, when the deployment has no taxonomy", async () => {
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
          majors: [],
          unassigned_core: [],
        },
      }),
    );
    expect(document.querySelector("table.cg-grid")).toBeNull();
    expect(document.body.textContent).toMatch(/no majors taxonomy/i);
  });

  it("discloses seeded rows above the grid they qualify", async () => {
    await renderLevel(
      () => ExplorePage(),
      board([
        task({
          task_id: "slo2/a",
          family: "slo2",
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

// ---------------------------------------------------------------------------

describe("level 2 — the classes", () => {
  it("says how far the class list got rather than letting a short list speak", async () => {
    await renderLevel(
      () => ClassesPage({ params: Promise.resolve({ major: GEN }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    expect(document.body.textContent).toContain("General Business");
    expect(document.body.textContent).toContain("Management");
  });

  it("leaves a class with no tasks about it empty beside a measured sibling", async () => {
    await renderLevel(
      () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }),
      measuredBoard(),
    );
    const row = modelRows()[0]!;
    const cells = Array.from(row.querySelectorAll("td.cg-cell"));
    expect(cells[columnOf("MIS 200")]!.className).toContain("cg-measured");
    expect(cells[columnOf("MIS 221")]!.className).toContain("cg-unmeasured");
    expect(cells[columnOf("MIS 221")]!.querySelector(".cg-score")).toBeNull();
  });

  it("404s on a major this college does not have", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      ClassesPage({ params: Promise.resolve({ major: "no-such-major" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------

describe("level 3 — the outcomes one class teaches", () => {
  it("shows the published level on every outcome it draws", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    expect(document.body.textContent).toContain("Assessment point");
  });

  it("shows an un-benchmarkable outcome rather than dropping it", async () => {
    // A class page that listed only the measurable outcomes would make GBA 300
    // look like a two-outcome class, which is a claim about the curriculum.
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: GEN, course: "gba-300" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const columns = Array.from(document.querySelectorAll("thead th.xp-col"));
    expect(columns).toHaveLength(3);

    const index = columnOf("Teamwork");
    expect(columns[index]!.className).toContain("xp-col-not_benchmarkable");

    // ⚠ EVERY CELL IN THE COLUMN, THE SUMMARY INCLUDED. A grid where the
    // per-model cells said "out of scope" and the summary said "not measured"
    // would be making two different claims about one column — and the summary
    // is the one a reader takes away.
    const inColumn = [...modelRows(), summaryRow()].map(
      (row) => Array.from(row.querySelectorAll("td.cg-cell"))[index]!,
    );
    expect(inColumn.length).toBeGreaterThan(1);
    for (const cell of inColumn) {
      expect(cell.className, "an out-of-scope column drew a measurable cell").toContain(
        "cg-out-of-scope",
      );
      expect(cell.textContent).toMatch(/not measurable by a text benchmark/i);
      expect(cell.querySelector(".cg-score")).toBeNull();
    }
  });

  it("says 'not measured yet' rather than drawing a blank or a zero", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: GEN, course: "gba-300" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const index = columnOf("Ethical Reasoning");
    const columns = Array.from(document.querySelectorAll("thead th.xp-col"));
    expect(columns[index]!.className).toContain("xp-col-not_measured");

    // ⚠ AN EMPTY CELL IS NEVER A BLANK. A dash with a reason behind it does not
    // read as a zero; an empty square does, to almost everybody.
    for (const row of [...modelRows(), summaryRow()]) {
      const cell = Array.from(row.querySelectorAll("td.cg-cell"))[index]!;
      expect(cell.className).toContain("cg-unmeasured");
      // Per-model cells say "this model has no…"; the summary row says "no
      // model has a…" — different squares, different claims, neither a blank.
      expect(cell.textContent).toMatch(
        /(this model has no|no model has a) finished, scored run|no task/i,
      );
    }
    // And the page says, in words, what the two glyphs mean.
    expect(document.querySelector(".xp-matrix-key")!.textContent).toContain(
      "Not measured yet",
    );
  });

  it("puts every column's reason on the page, not only in a tooltip", async () => {
    // ⚠ WHAT THE FLIP COULD HAVE COST. A column header cannot hold a sentence,
    // and truncating the honest reasons into a `title` attribute would have
    // made an empty square say nothing to anyone who does not hover.
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: GEN, course: "gba-300" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const notes = document.querySelectorAll(".xp-col-notes .xp-note");
    expect(notes).toHaveLength(document.querySelectorAll("thead th.xp-col").length);
    for (const note of notes) {
      expect(note.querySelector("dd")!.textContent!.length).toBeGreaterThan(20);
    }
    expect(document.querySelector(".xp-col-notes")!.textContent).toMatch(
      /cannot measure this outcome/i,
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

  it("puts each column's summary in the same table, built from the same cells", async () => {
    // ⚠ THE DISAGREEMENT THE MATRIX MAKES IMPOSSIBLE. A tile grid computed a
    // class's headline on a card and its per-model detail on another page;
    // nothing structural stopped the two drifting. Here the "All models" figure
    // is the last cell of the column it summarises, so a summary claiming a
    // score under a column of dashes would have to contradict its neighbours.
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const rows = modelRows();
    const summary = Array.from(summaryRow().querySelectorAll("td.cg-cell"));
    const columnCount = document.querySelectorAll("thead th.xp-col").length;
    expect(columnCount).toBeGreaterThan(1);

    for (let i = 0; i < columnCount; i += 1) {
      const anyModelMeasured = rows.some((row) =>
        Array.from(row.querySelectorAll("td.cg-cell"))[i]!.className.includes("cg-measured"),
      );
      expect(
        summary[i]!.className.includes("cg-measured"),
        `column ${i}: summary and cells disagree`,
      ).toBe(anyModelMeasured);
    }
  });

  it("says why, without blaming the class, when the map does not mark it", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-221" }) }),
      measuredBoard(),
    );
    expect(document.querySelector("table.cg-grid")).toBeNull();
    expect(document.body.textContent).toMatch(/gap in the map, not in the class/i);
  });

  it("404s on a class this major does not list", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-999" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  // ⚠ THE GAP THIS FILE EXISTS TO CLOSE. `/explore`, `/explore/[major]` and the
  // evidence level all disclosed a seeded score; this page once rendered the
  // identical flag as a flat, uncaveated finding. Both directions pinned here.
  it("discloses a seeded score above the grid, same words as every other level", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      board([
        task({
          task_id: "slo2/break-even",
          family: "slo2",
          slo: "SLO2",
          has_results: true,
          results: [result({ mean_score: 0.9, scored_count: 10, demonstration: true })],
        }),
      ]),
    );
    const notice = document.querySelector(".notice");
    expect(notice, "a seeded class score rendered no demonstration notice").not.toBeNull();
    expect(notice!.textContent).toMatch(/illustrative/i);

    // Self-clears per column too — the badge sits beside the level badge in the
    // column header, not just in a page-wide banner a reader can miss.
    expect(
      document.querySelector("thead .badge-demo"),
      "no per-column seeded badge on the measured outcome",
    ).not.toBeNull();

    // And on the row axis it also qualifies: a seeded model's whole ROW is
    // illustrative here, the way it is on `/compare`.
    expect(
      modelRows()[0]!.querySelector(".badge-demo"),
      "no seeded badge on the model row it belongs to",
    ).not.toBeNull();
  });

  it("renders no demonstration notice or badge when the class's scores are real", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard(),
    );
    expect(document.querySelector(".notice")).toBeNull();
    expect(document.querySelector(".badge-demo")).toBeNull();
  });
});

// ---------------------------------------------------------------------------

describe("level 4 — the evidence", () => {
  it("shows each model's read with its receipt", async () => {
    await renderLevel(
      () =>
        EvidencePage({
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
      () =>
        EvidencePage({
          params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo2" }),
        }),
      measuredBoard(),
    );
    expect(document.body.textContent).toContain("Straightforwardly checkable");
  });

  it("marks the model a cell click carried down", async () => {
    await renderLevel(
      () =>
        EvidencePage({
          params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo2" }),
          searchParams: Promise.resolve({ model: "luna" }),
        }),
      measuredBoard(),
    );
    expect(document.querySelector(".xp-focus")!.textContent).toContain("Luna");
    expect(document.querySelector("tr.xp-model-focused")!.textContent).toContain("Luna");
  });

  it("says nothing was run, and why, for an outcome out of scope", async () => {
    await renderLevel(
      () =>
        EvidencePage({
          params: Promise.resolve({ major: GEN, course: "gba-300", slo: "slo5" }),
        }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    expect(document.querySelector("table.leaderboard")).toBeNull();
    expect(document.body.textContent).toContain("deliberately");
    expect(document.body.textContent).toContain("OUT OF SCOPE");
  });

  it("says 'not measured yet' rather than showing an empty table", async () => {
    await renderLevel(
      () =>
        EvidencePage({
          params: Promise.resolve({ major: GEN, course: "gba-300", slo: "slo4" }),
        }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    expect(document.querySelector("table.leaderboard")).toBeNull();
    expect(document.body.textContent).toContain("Not measured yet");
    // ⚠ AND IT SAYS WHOSE GAP IT IS. "No model scored" and "we have not run
    // this" are different claims and only the second one is true here.
    expect(document.body.textContent).toContain("a gap in what we have run");
  });

  it("shows no receipts from a class this page is not about", async () => {
    // The SLO2 task on this board is about MIS 200. An evidence page for
    // GBA 300 that listed it would show a professor receipts from a course they
    // do not teach, under a heading that says GBA 300.
    await renderLevel(
      () =>
        EvidencePage({
          params: Promise.resolve({ major: GEN, course: "gba-300", slo: "slo2" }),
        }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    expect(document.body.textContent).not.toContain("Break-even volume");
    expect(document.querySelector("table.leaderboard")).toBeNull();
  });

  it("carries a breadcrumb back up every level", async () => {
    await renderLevel(
      () =>
        EvidencePage({
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
    expect(document.querySelector(".xp-crumbs")!.textContent).toContain("Majors");
  });

  it("404s on a pairing the map never marked", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "slo9" }),
      }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

// ---------------------------------------------------------------------------

describe("the register", () => {
  it("keeps the peer voice on every level", async () => {
    // The client's verdict was that a screen you have to explain has failed.
    // These four pages are the response to it, so the tics that sweep names —
    // meta-narration, defensiveness, a claim with a shelf life — are exactly
    // what they must not reintroduce.
    for (const page of [
      () => ExplorePage(),
      () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }),
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
