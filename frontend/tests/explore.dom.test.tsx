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
      const grid = document.querySelector(".xp-grid, table.leaderboard, .empty");
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
    const link = document.querySelector<HTMLAnchorElement>(".xp-tile-link");
    expect(link!.getAttribute("href")).toBe(`/explore/${MAJOR}`);
    expect(document.body.textContent).toContain("BScBA General Business (core)");
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
  it("draws one tile per course, in the published map's order", async () => {
    await renderLevel(
      () => CoursesPage({ params: Promise.resolve({ major: MAJOR }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const headings = Array.from(document.querySelectorAll(".xp-tile-eyebrow")).map(
      (n) => n.textContent,
    );
    expect(headings).toEqual(["MIS 200", "GBA 300"]);
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
    const tiles = Array.from(document.querySelectorAll(".xp-tile"));
    expect(tiles).toHaveLength(3);
    const teamwork = tiles.find((t) => t.textContent?.includes("Teamwork"))!;
    expect(teamwork.className).toContain("xp-tile-not_benchmarkable");
    expect(teamwork.textContent).toContain("Not text-measurable");
  });

  it("says 'not measured yet' rather than drawing a blank or a zero", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "gba-300" }) }),
      measuredBoard({ curriculum: WITH_TEAMWORK }),
    );
    const tiles = Array.from(document.querySelectorAll(".xp-tile"));
    const ethics = tiles.find((t) => t.textContent?.includes("Ethical Reasoning"))!;
    expect(ethics.className).toContain("xp-tile-not_measured");
    expect(ethics.textContent).toContain("Not measured yet");
    expect(ethics.querySelector(".xp-tile-score"), "an unrun pairing shows a score").toBeNull();
  });

  it("keeps the confidence tell beside every score it does show", async () => {
    await renderLevel(
      () => OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard(),
    );
    const tile = document.querySelector(".xp-tile-measured")!;
    expect(tile.querySelector(".xp-tile-score")!.textContent).toBe("0.72");
    expect(
      tile.querySelector(".xp-tile-confidence .confidence-pips"),
      "a score is shown with no tell for how much it can bear",
    ).not.toBeNull();
  });

  it("404s on a course the map does not list", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: "mis-999" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
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
