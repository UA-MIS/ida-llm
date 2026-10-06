/**
 * The drill-down's pages, rendered: classes → categories → evidence.
 *
 * ⚠ WHY THESE ARE NOT COVERED BY `explore.test.ts` / `explore-matrix.test.ts`.
 * Those prove the rules are computed correctly; this proves the PAGE shows them.
 * A grid that classified a pairing as "not measured yet" and then rendered a
 * bare cell would pass every pure test while telling a professor the models
 * scored zero on their class. The honest empty states are the product, so they
 * are asserted where a reader would actually meet them.
 *
 * ⚠ THE TOP LEVEL — the by-major grid — IS THE LANDING NOW, and is asserted in
 * `landing.dom.test.tsx`. This file is the three levels below it.
 *
 * ⚠ THE CLASS PAGE IS A CONTENT-CATEGORY GRID, NOT AN SLO ONE. The class page
 * used to list the outcomes a class teaches; it now lists the content
 * categories that define it (see `lib/categories.ts`). The SLO data is intact
 * internally, but the axis a professor meets on the class page is content.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { board as fixtureBoard, CURRICULUM, result, task } from "./fixtures";
import { expectPeerVoice } from "./voice";

/**
 * The fixture, with every `slo2` family remapped to `mis200-is-concepts` — the
 * real family MIS 200 claims, and the one the "IS concepts & business models"
 * content category maps to. So a default `slo2` task lights up that category.
 */
function board(...args: Parameters<typeof fixtureBoard>) {
  const value = structuredClone(fixtureBoard(...args));
  for (const major of value.curriculum.majors) {
    for (const klass of major.classes) {
      klass.task_families = klass.task_families.map((f) => (f === "slo2" ? "mis200-is-concepts" : f));
    }
  }
  for (const t of value.tasks) {
    if (t.family === "slo2") t.family = "mis200-is-concepts";
  }
  return value;
}

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

const { default: ClassesPage } = await import("@/app/(site)/explore/[major]/page");
const { default: ClassPage } = await import("@/app/(site)/explore/[major]/[course]/page");
const { default: EvidencePage } = await import(
  "@/app/(site)/explore/[major]/[course]/[slo]/page"
);

const MAJOR = "management-information-systems";
const GEN = "general-business";
const CATEGORY = "is-concepts-business-models";

function measuredBoard(overrides = {}) {
  return board(
    [
      task({
        task_id: "mis200-is-concepts/l1",
        family: "slo2", // remapped to mis200-is-concepts by board()
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

async function renderLevel(page: () => Promise<React.ReactElement>, response: unknown) {
  getLeaderboard.mockResolvedValue(response);
  render(await page());
}

function modelRows(): HTMLTableRowElement[] {
  return Array.from(
    document.querySelectorAll<HTMLTableRowElement>("table.cg-grid tbody tr"),
  ).filter((row) => !row.classList.contains("xp-summary"));
}

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

describe("no recommendation escape hatch on any level", () => {
  const levels: [string, () => Promise<React.ReactElement>][] = [
    ["classes", () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) })],
    ["categories", () => ClassPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) })],
    [
      "evidence",
      () => EvidencePage({ params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: CATEGORY }) }),
    ],
  ];

  for (const [name, page] of levels) {
    it(`offers no recommendation link, on the ${name} level`, async () => {
      // The recommendation feature was removed from the site. The old "just
      // tell me what to use" CTA (`a.xp-help-cta` → /recommend) must be gone,
      // and nothing on the level may link /recommend by any other route.
      getLeaderboard.mockResolvedValue(measuredBoard());
      render(await page());
      expect(
        document.querySelector("a.xp-help-cta"),
        `the ${name} level still has the old recommendation CTA`,
      ).toBeNull();
      const recommendLinks = Array.from(
        document.querySelectorAll<HTMLAnchorElement>("a"),
      ).filter((a) => a.getAttribute("href") === "/recommend");
      expect(recommendLinks, `the ${name} level still links /recommend`).toHaveLength(0);
    });

    it(`has no how-to-read panel on the ${name} level`, async () => {
      getLeaderboard.mockResolvedValue(measuredBoard());
      render(await page());
      expect(document.querySelector(".how-to-read")).toBeNull();
      expect(document.body.textContent).not.toMatch(/how to read this/i);
    });
  }
});

// ---------------------------------------------------------------------------

describe("level 2 — the classes of one major", () => {
  it("heads the row axis with the model and the columns with the classes, in catalog order", async () => {
    await renderLevel(() => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }), measuredBoard());
    const grid = document.querySelector("table.cg-grid.xp-matrix");
    expect(grid, "the classes level is not drawn as a matrix").not.toBeNull();
    const eyebrows = Array.from(document.querySelectorAll(".xp-col-eyebrow")).map((n) => n.textContent);
    expect(eyebrows).toEqual(["MIS 200", "MIS 221"]);
  });

  it("leaves a class with no tasks about it empty beside a measured sibling", async () => {
    await renderLevel(() => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }), measuredBoard());
    const row = modelRows()[0]!;
    const cells = Array.from(row.querySelectorAll("td.cg-cell"));
    expect(cells[columnOf("MIS 200")]!.className).toContain("cg-measured");
    expect(cells[columnOf("MIS 221")]!.className).toContain("cg-unmeasured");
    expect(cells[columnOf("MIS 221")]!.querySelector(".cg-score")).toBeNull();
  });

  it("renders the measured score as a whole-number percent", async () => {
    await renderLevel(() => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }), measuredBoard());
    const cell = document.querySelector("td.cg-measured .cg-score")!;
    expect(cell.textContent).toBe("72%");
  });

  it("404s on a major this college does not have", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      ClassesPage({ params: Promise.resolve({ major: "no-such-major" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });

  it("breadcrumbs back to the majors landing at /", async () => {
    await renderLevel(() => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }), measuredBoard());
    const hrefs = Array.from(document.querySelectorAll<HTMLAnchorElement>(".xp-crumbs a")).map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toEqual(["/"]);
  });
});

// ---------------------------------------------------------------------------

describe("level 3 — the content categories that define a class", () => {
  it("shows the class's content categories as the grid columns, not its SLOs", async () => {
    await renderLevel(
      () => ClassPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard(),
    );
    const columns = Array.from(document.querySelectorAll("thead th.xp-col"));
    // The five MIS 200 content categories.
    expect(columns).toHaveLength(5);
    expect(document.body.textContent).toContain("IS concepts & business models");
    expect(document.body.textContent).toContain("Spreadsheet & Excel skills");
    // Not the SLO vocabulary, and not the assignment-type one it briefly had.
    expect(document.body.textContent).toContain("categories that define this class");
    expect(columns[0]!.textContent).not.toContain("Quantitative Literacy");
  });

  it("measures the mapped category and leaves the unmapped ones honestly empty", async () => {
    await renderLevel(
      () => ClassPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard(),
    );
    const row = modelRows()[0]!;
    const cells = Array.from(row.querySelectorAll("td.cg-cell"));
    expect(cells[columnOf("IS concepts")]!.className).toContain("cg-measured");
    expect(cells[columnOf("IS concepts")]!.querySelector(".cg-score")!.textContent).toBe("72%");
    // A category with no family for this class never borrows a sibling's number.
    expect(cells[columnOf("Platform & network")]!.className).toContain("cg-unmeasured");
    expect(cells[columnOf("Platform & network")]!.querySelector(".cg-score")).toBeNull();
  });

  it("keeps the confidence tell beside every score it shows", async () => {
    await renderLevel(
      () => ClassPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard(),
    );
    const measured = Array.from(document.querySelectorAll("td.cg-measured"));
    expect(measured.length).toBeGreaterThan(0);
    for (const cell of measured) {
      expect(
        cell.querySelector(".cg-confidence .confidence-pips"),
        "a score is shown with no tell for how much it can bear",
      ).not.toBeNull();
    }
  });

  it("discloses a seeded score above the grid, same words as every other level", async () => {
    await renderLevel(
      () => ClassPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      board([
        task({
          task_id: "mis200-is-concepts/l1",
          family: "slo2",
          slo: "SLO2",
          has_results: true,
          results: [result({ mean_score: 0.9, scored_count: 10, demonstration: true })],
        }),
      ]),
    );
    const notice = document.querySelector(".notice");
    expect(notice, "a seeded category score rendered no demonstration notice").not.toBeNull();
    expect(notice!.textContent).toMatch(/illustrative/i);
  });

  it("renders no demonstration notice when the class's scores are real", async () => {
    await renderLevel(
      () => ClassPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      measuredBoard(),
    );
    expect(document.querySelector(".notice")).toBeNull();
  });

  it("explains, without blaming the class, when it has no category breakdown", async () => {
    await renderLevel(
      () => ClassPage({ params: Promise.resolve({ major: GEN, course: "gba-300" }) }),
      measuredBoard(),
    );
    // GBA 300 has no taxonomy in lib/categories.ts.
    expect(document.querySelector("table.cg-grid")).toBeNull();
    expect(document.body.textContent).toMatch(/No category breakdown/i);
  });

  it("404s on a class this major does not list", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      ClassPage({ params: Promise.resolve({ major: MAJOR, course: "mis-999" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

// ---------------------------------------------------------------------------

describe("level 4 — the evidence behind one category", () => {
  it("opens the category, shows each model's read and the run behind it", async () => {
    await renderLevel(
      () => EvidencePage({ params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: CATEGORY }) }),
      measuredBoard(),
    );
    expect(document.body.textContent).toContain("IS concepts & business models");
    // The score, as a whole-number percent, somewhere on the page.
    expect(document.body.textContent).toContain("72%");
    // The receipt is reachable.
    expect(document.querySelector('a[href="/runs/run_1"]')).not.toBeNull();
  });

  it("carries the synthetic-extension caveat on the competitive-strategy category", async () => {
    await renderLevel(
      () =>
        EvidencePage({
          params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "competitive-strategy" }),
        }),
      // A board where the problem-solving family scored, so the category renders.
      board([
        task({
          task_id: "mis200-is-problem-solving/l1",
          family: "mis200-is-problem-solving",
          slo: "SLO2",
          has_results: true,
          results: [result({ mean_score: 0.9 })],
        }),
      ], {
        curriculum: {
          ...CURRICULUM,
          majors: CURRICULUM.majors.map((m) =>
            m.id !== MAJOR
              ? m
              : {
                  ...m,
                  classes: m.classes.map((c) =>
                    c.course === "MIS 200"
                      ? { ...c, task_families: ["mis200-is-concepts", "mis200-is-problem-solving"] }
                      : c,
                  ),
                },
          ),
        },
      }),
    );
    expect(document.body.textContent).toMatch(/synthetic extension/i);
    expect(document.body.textContent).toMatch(/not comparable to a student cohort/i);
  });

  it("says 'not measured yet' rather than an empty grid for a category with no task", async () => {
    await renderLevel(
      () =>
        EvidencePage({
          params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "platform-network-economics" }),
        }),
      measuredBoard(),
    );
    expect(document.querySelector("table.cg-grid")).toBeNull();
    expect(document.body.textContent).toMatch(/Not measured yet/i);
  });

  it("carries a breadcrumb back up every level, to the majors landing", async () => {
    await renderLevel(
      () => EvidencePage({ params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: CATEGORY }) }),
      measuredBoard(),
    );
    const hrefs = Array.from(document.querySelectorAll<HTMLAnchorElement>(".xp-crumbs a")).map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toEqual(["/", `/explore/${MAJOR}`, `/explore/${MAJOR}/mis-200`]);
    expect(document.querySelector(".xp-crumbs")!.textContent).toContain("Majors");
  });

  it("404s on a segment that is neither a category nor a marked outcome", async () => {
    getLeaderboard.mockResolvedValue(measuredBoard());
    await expect(
      EvidencePage({ params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: "not-a-thing" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

// ---------------------------------------------------------------------------

describe("the register", () => {
  it("keeps the peer voice on every level", async () => {
    for (const page of [
      () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }),
      () => ClassPage({ params: Promise.resolve({ major: MAJOR, course: "mis-200" }) }),
      () => EvidencePage({ params: Promise.resolve({ major: MAJOR, course: "mis-200", slo: CATEGORY }) }),
    ]) {
      getLeaderboard.mockResolvedValue(measuredBoard());
      render(await page());
      expectPeerVoice(document.body.textContent ?? "", expect);
      cleanup();
    }
  });
});
