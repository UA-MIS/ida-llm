/**
 * The drill-down's rules: major → class → outcome → evidence.
 *
 * ⚠ THE TEST THIS FILE EXISTS FOR IS `a class shows only its own results`. Every
 * other assertion here guards a wording or a count; that one guards the claim
 * the whole screen makes. Results are filed by OUTCOME, so a class scored from
 * "the outcomes it teaches" gets a number identical to every other class the map
 * marks against those outcomes — run the MIS 200 exam families and AC 210,
 * ST 260, GBA 300, OM 300 and FI 302 each light up with a score from a course
 * none of them is. A dozen fabricated measurements produced by arithmetic
 * rather than by anybody lying, each individually plausible, on the one product
 * whose pitch is that its numbers are real. It is the failure mode with the
 * highest blast radius in this codebase and the easiest one to reintroduce by
 * "simplifying" a filter.
 */

import { describe, expect, it } from "vitest";

import { board, CURRICULUM, result, task } from "./fixtures";
import {
  buildClasses,
  buildEvidence,
  buildIndex,
  findClass,
  findMajor,
  findOutcome,
  isAssessmentPoint,
  levelLabel,
  NO_TASKS_FOR_CLASS,
  slugify,
  codeForMajor,
} from "@/lib/explore";
import type { LeaderboardResponse, MajorView } from "@/lib/types";

const MIS = "management-information-systems";
const GEN = "general-business";

/** One scored SLO2 task in the `mis200-is-concepts` family — the family MIS 200 claims. */
function measuredBoard(overrides = {}): LeaderboardResponse {
  return board(
    [
      task({
        task_id: "slo2/break-even",
        family: "mis200-is-concepts",
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

function majorOf(b: LeaderboardResponse, id: string) {
  const tile = findMajor(buildIndex(b), id);
  if (!tile) throw new Error(`fixture has no major ${id}`);
  return tile;
}

// ---------------------------------------------------------------------------

describe("slugs", () => {
  it("turns a course code into a URL segment", () => {
    expect(slugify("MIS 200")).toBe("mis-200");
    expect(slugify("Fundamentals of MIS")).toBe("fundamentals-of-mis");
  });

  it("leaves no leading or trailing separator", () => {
    expect(slugify("  MIS 200!  ")).toBe("mis-200");
  });
});

describe("the published map's legend", () => {
  it("spells out every level it publishes", () => {
    expect(levelLabel("I")).toBe("Introduced");
    expect(levelLabel("M+A")).toBe("Mastered · assessment point");
  });

  it("passes an unknown level through rather than inventing a word for it", () => {
    expect(levelLabel("Z")).toBe("Z");
  });

  it("counts only A and M+A as levels the programme reports on", () => {
    expect(isAssessmentPoint("A")).toBe(true);
    expect(isAssessmentPoint("M+A")).toBe(true);
    expect(isAssessmentPoint("M")).toBe(false);
    expect(isAssessmentPoint("R")).toBe(false);
  });
});

// ---------------------------------------------------------------------------

describe("level 1 — the majors", () => {
  it("is one tile per major in the taxonomy, in the file's order", () => {
    const index = buildIndex(measuredBoard());
    expect(index.available).toBe(true);
    expect(index.majors.map((m) => m.slug)).toEqual([MIS, GEN]);
  });

  it("uses the authored id as the URL segment, not a slug of the name", () => {
    // The id is authored precisely so a catalog rename does not break links.
    // Deriving it from the name here would silently undo that.
    const major = majorOf(measuredBoard(), MIS);
    expect(major.slug).toBe(MIS);
    expect(major.name).toBe("Management Information Systems");
  });

  it("says a major is unavailable when the deployment has no taxonomy", () => {
    const index = buildIndex(
      board([], { curriculum: { ...CURRICULUM, majors: [], unassigned_core: [] } }),
    );
    expect(index.available).toBe(false);
    expect(index.unavailable_reason).toMatch(/majors/i);
    expect(index.majors).toEqual([]);
  });

  it("carries the core courses no major owns, rather than dropping them", () => {
    // A course in the core that is reachable from no major is a fact about the
    // college. Omitting it would quietly shorten the curriculum.
    expect(buildIndex(measuredBoard()).unassigned).toEqual([
      {
        course: "LGS 200",
        reason: "No Legal Studies major exists, so no major owns this core course.",
      },
    ]);
  });

  it("scores a major from its own classes' results and nothing else", () => {
    const index = buildIndex(measuredBoard());
    const mis = index.majors.find((m) => m.slug === MIS)!;
    const gen = index.majors.find((m) => m.slug === GEN)!;

    // MIS 200 claims the `mis200-is-concepts` family, so the scored SLO2 task reaches it.
    expect(mis.status).toBe("measured");
    expect(mis.aggregate.score).toBeCloseTo(0.72);

    // GBA 300 teaches SLO2 as well, and claims no family. It must stay empty.
    expect(gen.status).toBe("not_measured");
    expect(gen.aggregate.score).toBeNull();
  });

  it("says how far a major's class list got, rather than letting a short list speak", () => {
    const gen = majorOf(measuredBoard(), GEN);
    expect(gen.class_source).toBe("core-only");
    expect(gen.class_source_label).toMatch(/core/i);
  });

  it("counts the classes that CAN be measured apart from the ones that are", () => {
    const mis = majorOf(measuredBoard(), MIS);
    expect(mis.class_count).toBe(2); // MIS 200 and MIS 221
    expect(mis.measurable_class_count).toBe(1); // only MIS 200 claims a family
    expect(mis.measured_class_count).toBe(1);
  });

  it("explains an unmeasured major in terms of what has been authored, not of the models", () => {
    const gen = majorOf(measuredBoard(), GEN);
    expect(gen.reason).toMatch(/no task in the catalogue is about any of them yet/i);
    expect(gen.reason).not.toMatch(/fail|poor|weak/i);
  });
});

// ---------------------------------------------------------------------------

describe("level 2 — the classes of one major", () => {
  it("is one tile per class, in the catalog's order", () => {
    const classes = buildClasses(measuredBoard(), majorOf(measuredBoard(), MIS));
    expect(classes.map((c) => c.code)).toEqual(["MIS 200", "MIS 221"]);
  });

  it("does not re-sort classes by score", () => {
    // MIS 200 is the measured one and it happens to be first. Prove the order
    // is the catalog's by measuring the LAST class instead and checking the
    // order does not move: a major must never become a ranking of its own
    // classes.
    const b = board([
      task({
        task_id: "mis221/x",
        family: "mis221",
        slo: "SLO2",
        has_results: true,
        results: [result({ mean_score: 0.9 })],
      }),
    ]);
    const flipped = {
      ...CURRICULUM,
      coverage: [
        ...CURRICULUM.coverage,
        { course: "MIS 221", title: "Business Programming I", outcomes: { SLO2: "R" } },
      ],
      majors: CURRICULUM.majors.map((m) =>
        m.id !== MIS
          ? m
          : {
              ...m,
              classes: m.classes.map((c) =>
                c.course === "MIS 221" ? { ...c, task_families: ["mis221"] } : c,
              ),
            },
      ),
    };
    const withFlip = { ...b, curriculum: flipped };
    const classes = buildClasses(withFlip, majorOf(withFlip, MIS));
    expect(classes.map((c) => c.code)).toEqual(["MIS 200", "MIS 221"]);
    expect(classes[1]!.status).toBe("measured");
    expect(classes[0]!.status).toBe("not_measured");
  });

  it("reports a result filed outside the outcomes the map marks, rather than dropping it", () => {
    // A class with real results and no row in the coverage grid has nowhere to
    // put them. Saying nothing would make a scored run vanish from the page
    // that is supposed to account for every one.
    const b = board([
      task({
        task_id: "mis221/x",
        family: "mis221",
        slo: "SLO2",
        has_results: true,
        results: [result({ mean_score: 0.9 })],
      }),
    ]);
    const withFamily = {
      ...b,
      curriculum: {
        ...CURRICULUM,
        majors: CURRICULUM.majors.map((m) =>
          m.id !== MIS
            ? m
            : {
                ...m,
                classes: m.classes.map((c) =>
                  c.course === "MIS 221" ? { ...c, task_families: ["mis221"] } : c,
                ),
              },
        ),
      },
    };
    const mis221 = findClass(
      buildClasses(withFamily, majorOf(withFamily, MIS)),
      "mis-221",
    )!;
    expect(mis221.aggregate.score).toBeNull();
    expect(mis221.reason).toMatch(/filed under an outcome the map does not mark/i);
  });

  it("finds a class by its slug", () => {
    const classes = buildClasses(measuredBoard(), majorOf(measuredBoard(), MIS));
    expect(findClass(classes, "mis-200")?.code).toBe("MIS 200");
    expect(findClass(classes, "nope")).toBeUndefined();
  });

  it("returns nothing for a major the taxonomy does not list", () => {
    const b = measuredBoard();
    expect(
      buildClasses(b, { ...majorOf(b, MIS), slug: "not-a-major" }),
    ).toEqual([]);
  });

  // -- THE ONE THAT MATTERS -------------------------------------------------

  it("shows a class only its OWN results, never a sibling's", () => {
    const classes = buildClasses(measuredBoard(), majorOf(measuredBoard(), MIS));
    const mis200 = findClass(classes, "mis-200")!;
    const mis221 = findClass(classes, "mis-221")!;

    expect(mis200.status).toBe("measured");
    expect(mis200.aggregate.score).toBeCloseTo(0.72);

    // MIS 221 claims no task family. Even if it taught SLO2 it could not
    // borrow MIS 200's number, and here it does not even reach the map.
    expect(mis221.task_families).toEqual([]);
    expect(mis221.aggregate.score).toBeNull();
    expect(mis221.status).toBe("not_measured");
  });

  it("keeps a class that teaches a measured outcome empty when no task is about it", () => {
    // GBA 300 teaches SLO2, which IS measured on this board — by a task about
    // MIS 200. Without family scoping this class would display 0.72 under a
    // heading no model was ever asked about.
    const b = measuredBoard();
    const gba = findClass(buildClasses(b, majorOf(b, GEN)), "gba-300")!;

    expect(gba.outcomes.map((o) => o.slo)).toContain("SLO2");
    expect(gba.aggregate.score).toBeNull();
    expect(gba.status).toBe("not_measured");
    expect(gba.reason).toBe(NO_TASKS_FOR_CLASS);
  });

  it("says so plainly when the curriculum map does not mark a class at all", () => {
    // The commonest state in the product: the catalog lists fourteen MIS
    // classes and the core map marks one. It is not an error and not a class
    // that failed.
    const b = measuredBoard();
    const mis221 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-221")!;

    expect(mis221.in_curriculum_map).toBe(false);
    expect(mis221.outcomes).toEqual([]);
    expect(mis221.reason).toMatch(/curriculum map does not mark this class/i);
    // And it is NOT the "a text benchmark cannot reach this" claim, which is a
    // completely different statement about the outcome itself.
    expect(mis221.status).toBe("not_measured");
  });

  it("marks a class out of scope only when every outcome it teaches is", () => {
    const noText = {
      ...CURRICULUM,
      outcomes: [
        {
          id: "SLO5",
          title: "Teamwork",
          statement: "Students work effectively on teams.",
          text_benchmarkable: false,
          benchmark_note: "OUT OF SCOPE for a text benchmark.",
        },
      ],
      coverage: [{ course: "MIS 200", title: "Fundamentals of MIS", outcomes: { SLO5: "M+A" } }],
    };
    const b = board([], { curriculum: noText, slos: ["SLO5"] });
    const tile = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    expect(tile.status).toBe("not_benchmarkable");
    expect(tile.reason).toMatch(/cannot\s+measure/i);
  });

  it("carries a per-class demonstration split, not the whole board's", () => {
    const b = measuredBoard();
    const mis200 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    expect(mis200.demonstration.any).toBe(false);

    const seeded = board([
      task({
        task_id: "slo2/break-even",
        family: "mis200-is-concepts",
        slo: "SLO2",
        has_results: true,
        results: [result({ mean_score: 0.72, demonstration: true })],
      }),
    ]);
    const tile = findClass(buildClasses(seeded, majorOf(seeded, MIS)), "mis-200")!;
    expect(tile.demonstration.any).toBe(true);
  });
});

// ---------------------------------------------------------------------------

describe("level 3 — the outcomes one class teaches", () => {
  it("gives every marked outcome a tile, in curriculum order", () => {
    const b = measuredBoard();
    const gba = findClass(buildClasses(b, majorOf(b, GEN)), "gba-300")!;
    expect(gba.outcomes.map((o) => o.slo)).toEqual(["SLO2", "SLO4"]);
  });

  it("carries the published level for THIS class", () => {
    const b = measuredBoard();
    const mis200 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    const slo2 = findOutcome(mis200, "SLO2")!;
    expect(slo2.level).toBe("A");
    expect(slo2.assessment_point).toBe(true);
  });

  it("finds an outcome case-insensitively, for a hand-typed URL", () => {
    const b = measuredBoard();
    const mis200 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    expect(findOutcome(mis200, "slo2")?.slo).toBe("SLO2");
    expect(findOutcome(mis200, "SLO2")?.slo).toBe("SLO2");
    expect(findOutcome(mis200, "SLO9")).toBeUndefined();
  });

  it("counts only tasks about THIS class as the denominator of 'nothing ran'", () => {
    const b = measuredBoard();
    const gba = findClass(buildClasses(b, majorOf(b, GEN)), "gba-300")!;
    // Two SLO2 tasks exist on this board; none is about GBA 300.
    expect(findOutcome(gba, "SLO2")!.tasks_available).toBe(0);
    const mis200 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    expect(findOutcome(mis200, "SLO2")!.tasks_available).toBe(1);
  });

  it("says a class has no tasks written about it, rather than blaming the run", () => {
    const b = measuredBoard();
    const gba = findClass(buildClasses(b, majorOf(b, GEN)), "gba-300")!;
    expect(findOutcome(gba, "SLO2")!.reason).toBe(NO_TASKS_FOR_CLASS);
  });

  it("never renders an unmeasured outcome as a number", () => {
    const b = measuredBoard();
    const mis200 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    for (const tile of mis200.outcomes.filter((o) => o.status !== "measured")) {
      expect(tile.aggregate.score).toBeNull();
      expect(tile.reason.length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------

describe("level 4 — the evidence", () => {
  it("lists only the tasks about this class, filed under this outcome", () => {
    const b = measuredBoard();
    const mis200 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    const evidence = buildEvidence(b, mis200, findOutcome(mis200, "SLO2")!);
    expect(evidence.tasks.map((t) => t.task_id)).toEqual(["slo2/break-even"]);
  });

  it("shows no receipts for a class nothing was written about", () => {
    // An evidence page that listed every SLO2 task would show a professor of
    // GBA 300 receipts from a course they do not teach, under a heading that
    // says GBA 300.
    const b = measuredBoard();
    const gba = findClass(buildClasses(b, majorOf(b, GEN)), "gba-300")!;
    const evidence = buildEvidence(b, gba, findOutcome(gba, "SLO2")!);
    expect(evidence.tasks).toEqual([]);
    expect(evidence.ranked).toEqual([]);
    expect(evidence.unranked).toEqual([]);
  });

  it("ranks models by score and keeps unscored ones visible", () => {
    const b = board([
      task({
        task_id: "slo2/break-even",
        family: "mis200-is-concepts",
        slo: "SLO2",
        has_results: true,
        results: [
          result({ model_key: "luna", display_name: "Luna", mean_score: 0.4 }),
          result({ model_key: "sol", display_name: "Sol", mean_score: 0.8 }),
          result({
            model_key: "dim",
            display_name: "Dim",
            mean_score: null,
            scored_count: 0,
          }),
        ],
      }),
    ]);
    const mis200 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    const evidence = buildEvidence(b, mis200, findOutcome(mis200, "SLO2")!);
    expect(evidence.ranked.map((r) => r.model_key)).toEqual(["sol", "luna"]);
    expect(evidence.unranked.map((r) => r.model_key)).toEqual(["dim"]);
  });
});

describe("codeForMajor", () => {
  const base: MajorView = {
    id: "x",
    name: "Business Cyber Security",
    department: "d",
    subject_codes: [],
    catalog: null,
    class_source: "none",
    class_source_label: "",
    classes: [],
  };

  it("prefers the catalogued subject codes", () => {
    expect(codeForMajor({ ...base, subject_codes: ["MIS"], display_code: "ZZ" })).toBe("MIS");
  });

  it("falls back to the informal display_code before the name", () => {
    expect(codeForMajor({ ...base, display_code: "BCS" })).toBe("BCS");
  });

  it("falls back to the name only when there is neither", () => {
    expect(codeForMajor(base)).toBe("Business Cyber Security");
    expect(codeForMajor({ ...base, display_code: null })).toBe("Business Cyber Security");
  });
});
