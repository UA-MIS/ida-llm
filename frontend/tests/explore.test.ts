/**
 * The drill-down's grouping rules, without rendering anything.
 *
 * ⚠ WHAT THESE TESTS ARE ACTUALLY GUARDING. A drill-down is a shape that makes
 * absence look like data: every level is a grid, every grid is mostly tiles for
 * pairings nobody has run, and a tile with no number is one keystroke away from
 * reading as a zero. The rules pinned here are the ones that keep the four
 * levels honest under that pressure:
 *
 *   - a pairing the curriculum says a text benchmark CANNOT measure is
 *     classified before any score is looked at, so it can never read as a
 *     failure;
 *   - a pairing with no finished run says "not measured yet" and carries the
 *     reason, and never a number;
 *   - the numbers themselves come from the shared `aggregate`, so a course
 *     headline cannot disagree with the leaderboard about the same rows;
 *   - test stubs stay out of every headline number, exactly as they stay off
 *     the leaderboard's podium.
 */

import { describe, expect, it } from "vitest";

import {
  buildCourses,
  buildEvidence,
  buildIndex,
  findCourse,
  findMajor,
  findOutcome,
  isAssessmentPoint,
  levelLabel,
  slugify,
} from "@/lib/explore";
import type { CurriculumView, LeaderboardResponse } from "@/lib/types";

import { board, CURRICULUM, result, task, trust } from "./fixtures";

/** The fixture curriculum plus an outcome a text benchmark cannot reach. */
function curriculumWithTeamwork(): CurriculumView {
  return {
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
      { course: "GBA 146", title: "Professional Development I", outcomes: { SLO5: "I" } },
    ],
  };
}

/** A board where one model has two SLO2 tasks of very different sizes. */
function measuredBoard(overrides: Partial<LeaderboardResponse> = {}) {
  return board(
    [
      task({
        task_id: "slo2/small",
        slo: "SLO2",
        sample_count: 10,
        has_results: true,
        best_model_key: "luna",
        results: [result({ mean_score: 0.9, scored_count: 10, sample_count: 10 })],
      }),
      task({
        task_id: "slo2/large",
        slo: "SLO2",
        sample_count: 30,
        has_results: true,
        best_model_key: "luna",
        results: [result({ mean_score: 0.5, scored_count: 30, sample_count: 30 })],
      }),
    ],
    overrides,
  );
}

describe("slugs", () => {
  it("turns a course code into one URL segment and back again", () => {
    expect(slugify("MIS 200")).toBe("mis-200");
    expect(slugify("BScBA General Business (core)")).toBe("bscba-general-business-core");
  });

  it("finds a course by the slug it just produced", () => {
    const courses = buildCourses(measuredBoard());
    expect(findCourse(courses, slugify("MIS 200"))?.code).toBe("MIS 200");
  });

  it("returns undefined for a course the map does not list", () => {
    // Not an empty tile: "no such course" and "this course teaches nothing" are
    // different answers, and only one of them is ever true.
    expect(findCourse(buildCourses(measuredBoard()), "mis-999")).toBeUndefined();
  });
});

describe("coverage levels", () => {
  it("spells out the published legend", () => {
    expect(levelLabel("I")).toBe("Introduced");
    expect(levelLabel("M+A")).toBe("Mastered · assessment point");
  });

  it("passes an unknown code through rather than inventing a label", () => {
    expect(levelLabel("Z")).toBe("Z");
  });

  it("knows which levels the programme actually reports on", () => {
    expect(isAssessmentPoint("A")).toBe(true);
    expect(isAssessmentPoint("M+A")).toBe(true);
    expect(isAssessmentPoint("M")).toBe(false);
    expect(isAssessmentPoint("R")).toBe(false);
  });
});

describe("level 1 — the programme", () => {
  it("names the programme from the curriculum, never from a constant", () => {
    const index = buildIndex(measuredBoard());
    expect(index.majors).toHaveLength(1);
    expect(index.majors[0]!.name).toBe("BScBA General Business (core)");
    expect(findMajor(index, index.majors[0]!.slug)).toBeDefined();
  });

  it("counts measurable outcomes separately from all outcomes", () => {
    const index = buildIndex(
      measuredBoard({ curriculum: curriculumWithTeamwork() }),
    );
    const major = index.majors[0]!;
    expect(major.outcome_count).toBe(3);
    // SLO5 is not text-benchmarkable, so it is not a gap in our coverage.
    expect(major.benchmarkable_count).toBe(2);
  });

  it("is unavailable, with a reason, when the deployment has no curriculum map", () => {
    const index = buildIndex(
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
    expect(index.available).toBe(false);
    expect(index.majors).toEqual([]);
    expect(index.unavailable_reason).toContain("No curriculum/slo.yaml");
  });

  it("is unavailable when the map loads but publishes no coverage grid", () => {
    // The outcomes are known and the courses are not — a real state, and one
    // that must not render a programme tile leading to an empty course grid.
    const index = buildIndex(
      board([], { curriculum: { ...CURRICULUM, coverage: [] } }),
    );
    expect(index.available).toBe(false);
    expect(index.unavailable_reason).toBeTruthy();
  });
});

describe("level 2 — the courses", () => {
  it("keeps the published map's order rather than ranking the department", () => {
    const courses = buildCourses(measuredBoard({ curriculum: curriculumWithTeamwork() }));
    expect(courses.map((c) => c.code)).toEqual(["MIS 200", "GBA 300", "GBA 146"]);
  });

  it("lists only the outcomes the map marks for a course", () => {
    const courses = buildCourses(measuredBoard({ curriculum: curriculumWithTeamwork() }));
    const mis200 = findCourse(courses, "mis-200")!;
    // An absent cell means "the map does not mark this pair" — not a level of
    // zero, and not a row to draw.
    expect(mis200.outcomes.map((o) => o.slo)).toEqual(["SLO2"]);
  });

  it("orders a course's outcomes by the curriculum, not by the YAML mapping", () => {
    const courses = buildCourses(measuredBoard({ curriculum: curriculumWithTeamwork() }));
    const gba300 = findCourse(courses, "gba-300")!;
    expect(gba300.outcomes.map((o) => o.slo)).toEqual(["SLO2", "SLO4", "SLO5"]);
  });

  it("reads a course whose every outcome is out of scope as out of scope", () => {
    const courses = buildCourses(measuredBoard({ curriculum: curriculumWithTeamwork() }));
    const gba146 = findCourse(courses, "gba-146")!;
    expect(gba146.status).toBe("not_benchmarkable");
    expect(gba146.benchmarkable_count).toBe(0);
    // And never a number: nothing was run, deliberately.
    expect(gba146.aggregate.score).toBeNull();
  });

  it("counts the assessment points, which is where a human number already exists", () => {
    const courses = buildCourses(measuredBoard({ curriculum: curriculumWithTeamwork() }));
    expect(findCourse(courses, "mis-200")!.assessment_count).toBe(1);
    expect(findCourse(courses, "gba-300")!.assessment_count).toBe(2);
  });

  it("discloses when the models measured on its outcomes are seeded, not real", () => {
    // This was the gap: `/explore/[major]/[course]` rendered a course tile's
    // score with no caveat at all, while `/explore`, `/explore/[major]` and
    // the evidence level already disclosed the identical flag.
    const seeded = board([
      task({
        task_id: "slo2/a",
        slo: "SLO2",
        has_results: true,
        results: [result({ mean_score: 0.9, scored_count: 10, demonstration: true })],
      }),
    ]);
    const course = findCourse(buildCourses(seeded), "mis-200")!;
    expect(course.demonstration.any).toBe(true);
    expect(course.demonstration.notice).toMatch(/illustrative/i);
  });

  it("never flags a course whose own outcomes are genuinely measured", () => {
    const course = findCourse(buildCourses(measuredBoard()), "mis-200")!;
    expect(course.demonstration.any).toBe(false);
    expect(course.demonstration.notice).toBe("");
  });

  it("scopes the caveat to the course actually seeded, not the whole board", () => {
    // MIS 200 is measured for real, by Luna; GBA 300 is seeded, by a different
    // model entirely. MIS 200's own page must not inherit a caveat that
    // belongs to a different course's models.
    const mixed = board(
      [
        task({
          task_id: "slo2/real",
          slo: "SLO2",
          has_results: true,
          results: [result({ model_key: "luna", mean_score: 0.8, scored_count: 10, demonstration: false })],
        }),
        task({
          task_id: "slo4/seeded",
          slo: "SLO4",
          has_results: true,
          results: [
            result({ model_key: "nova", display_name: "Nova", mean_score: 0.6, scored_count: 10, demonstration: true }),
          ],
        }),
      ],
      { curriculum: curriculumWithTeamwork() },
    );
    const courses = buildCourses(mixed);
    expect(findCourse(courses, "mis-200")!.demonstration.any).toBe(false);
    expect(findCourse(courses, "gba-300")!.demonstration.any).toBe(true);
  });
});

describe("an outcome tile's own seeded tell", () => {
  it("self-clears the moment a real measurement replaces the seeded one", () => {
    const seeded = board([
      task({
        task_id: "slo2/a",
        slo: "SLO2",
        has_results: true,
        results: [result({ mean_score: 0.9, scored_count: 10, demonstration: true })],
      }),
    ]);
    const seededTile = findOutcome(findCourse(buildCourses(seeded), "mis-200")!, "SLO2")!;
    expect(seededTile.seeded).toBe(true);

    const realTile = findOutcome(findCourse(buildCourses(measuredBoard()), "mis-200")!, "SLO2")!;
    expect(realTile.seeded).toBe(false);
  });

  it("is never true for a tile with no score at all", () => {
    const board_ = board([
      task({ task_id: "slo2/unrun", slo: "SLO2", has_results: false, results: [] }),
    ]);
    const tile = findOutcome(findCourse(buildCourses(board_), "mis-200")!, "SLO2")!;
    expect(tile.status).toBe("not_measured");
    expect(tile.seeded).toBe(false);
  });
});

describe("level 3 — the outcomes, and the three kinds of empty", () => {
  it("weights a course's score by samples, so a small task cannot outvote a large one", () => {
    const mis200 = findCourse(buildCourses(measuredBoard()), "mis-200")!;
    // (0.9 x 10 + 0.5 x 30) / 40 = 0.6. A mean-of-means would be 0.7.
    expect(mis200.aggregate.score).toBeCloseTo(0.6, 10);
    expect(mis200.aggregate.scored_samples).toBe(40);
  });

  it("takes the WEAKEST confidence among the measurements, never an average", () => {
    const board_ = board([
      task({
        task_id: "slo2/a",
        slo: "SLO2",
        has_results: true,
        results: [
          result({
            model_key: "luna",
            mean_score: 0.9,
            scored_count: 10,
            trust: trust({ confidence: "high" }),
          }),
        ],
      }),
      task({
        task_id: "slo2/b",
        slo: "SLO2",
        has_results: true,
        results: [
          result({
            model_key: "luna",
            mean_score: 0.5,
            scored_count: 10,
            trust: trust({ confidence: "low" }),
          }),
        ],
      }),
    ]);
    const tile = findCourse(buildCourses(board_), "mis-200")!.outcomes[0]!;
    expect(tile.aggregate.confidence).toBe("low");
  });

  it("classifies an un-benchmarkable outcome before it looks at any score", () => {
    // A row exists and carries a real number. It must STILL read as out of
    // scope: `curriculum/slo.yaml` calls scoring SLO5 from a single-turn prompt
    // "the most misleading thing in this repository".
    const board_ = board(
      [
        task({
          task_id: "slo5/teamwork",
          slo: "SLO5",
          has_results: true,
          results: [result({ mean_score: 0.95, scored_count: 20 })],
        }),
      ],
      { curriculum: curriculumWithTeamwork() },
    );
    const tile = findOutcome(findCourse(buildCourses(board_), "gba-300")!, "SLO5")!;
    expect(tile.status).toBe("not_benchmarkable");
    expect(tile.benchmarkable).toBe(false);
    // A caption on the tile, and the curriculum's full argument still carried
    // for the level below to print — see the note in `buildOutcomeTile`.
    expect(tile.reason).toBe(
      "A single-turn text benchmark cannot measure this outcome, so nothing was run.",
    );
    expect(tile.note).toContain("OUT OF SCOPE");
  });

  it("says 'not measured' with a reason, and never a number, for an unrun pairing", () => {
    const board_ = board([
      task({ task_id: "slo2/unrun", slo: "SLO2", has_results: false, results: [] }),
    ]);
    const tile = findOutcome(findCourse(buildCourses(board_), "mis-200")!, "SLO2")!;
    expect(tile.status).toBe("not_measured");
    expect(tile.aggregate.score).toBeNull();
    expect(tile.tasks_available).toBe(1);
    expect(tile.reason).toMatch(/1 task measures this outcome; none has a finished, scored run\./);
  });

  it("distinguishes 'no task exists' from 'a task exists and has not run'", () => {
    const board_ = board([], { curriculum: curriculumWithTeamwork() });
    const tile = findOutcome(findCourse(buildCourses(board_), "mis-200")!, "SLO2")!;
    expect(tile.tasks_available).toBe(0);
    expect(tile.reason).toBe("No task in the catalogue measures this outcome yet.");
  });

  it("finds an outcome from a lowercase URL segment", () => {
    const course = findCourse(buildCourses(measuredBoard()), "mis-200")!;
    expect(findOutcome(course, "slo2")?.slo).toBe("SLO2");
    expect(findOutcome(course, "slo9")).toBeUndefined();
  });

  it("keeps a test stub out of the headline number", () => {
    // `isRanked` keeps a deterministic mock off the leaderboard's podium so the
    // winner is never a fixture. A mock folded into a course's headline is the
    // same lie with fewer places to notice it.
    const board_ = board([
      task({
        task_id: "slo2/a",
        slo: "SLO2",
        has_results: true,
        results: [
          result({ model_key: "luna", mean_score: 0.4, scored_count: 10 }),
          result({
            model_key: "stub",
            display_name: "Echo stub",
            recommendable: false,
            mean_score: 1,
            scored_count: 10,
          }),
        ],
      }),
    ]);
    const tile = findOutcome(findCourse(buildCourses(board_), "mis-200")!, "SLO2")!;
    expect(tile.aggregate.score).toBeCloseTo(0.4, 10);
    expect(tile.models_measured).toBe(1);
  });
});

describe("level 4 — the evidence", () => {
  function evidenceBoard() {
    return board([
      task({
        task_id: "slo2/a",
        slo: "SLO2",
        has_results: true,
        best_model_key: "vega",
        results: [
          result({ model_key: "luna", display_name: "Luna", mean_score: 0.4, scored_count: 10 }),
          result({ model_key: "vega", display_name: "Vega", mean_score: 0.8, scored_count: 10 }),
          result({
            model_key: "stub",
            display_name: "Echo stub",
            recommendable: false,
            mean_score: 1,
            scored_count: 10,
          }),
          result({
            model_key: "nova",
            display_name: "Nova",
            mean_score: null,
            scored_count: 0,
            error_count: 4,
          }),
        ],
      }),
      task({ task_id: "slo4/other", slo: "SLO4", has_results: false, results: [] }),
    ]);
  }

  it("ranks the models that have a score, strongest first", () => {
    const courses = buildCourses(evidenceBoard());
    const course = findCourse(courses, "mis-200")!;
    const view = buildEvidence(evidenceBoard(), course, findOutcome(course, "SLO2")!);
    expect(view.ranked.map((r) => r.model_key)).toEqual(["vega", "luna"]);
  });

  it("shows the models that produced nothing, rather than quietly dropping them", () => {
    // A reader who has drilled this far is checking a number, and "one model was
    // run and produced nothing" is part of what the number means.
    const courses = buildCourses(evidenceBoard());
    const course = findCourse(courses, "mis-200")!;
    const view = buildEvidence(evidenceBoard(), course, findOutcome(course, "SLO2")!);
    expect(view.unranked.map((r) => r.model_key).sort()).toEqual(["nova", "stub"]);
    expect(view.unranked.find((r) => r.model_key === "nova")!.aggregate.score).toBeNull();
  });

  it("lists only the tasks filed under the outcome being opened", () => {
    const courses = buildCourses(evidenceBoard());
    const course = findCourse(courses, "mis-200")!;
    const view = buildEvidence(evidenceBoard(), course, findOutcome(course, "SLO2")!);
    expect(view.tasks.map((t) => t.task_id)).toEqual(["slo2/a"]);
  });

  it("discloses seeded rows and never flags a measured one", () => {
    const seeded = board([
      task({
        task_id: "slo2/a",
        slo: "SLO2",
        has_results: true,
        results: [
          result({ model_key: "luna", mean_score: 0.9, scored_count: 10, demonstration: true }),
          result({ model_key: "vega", mean_score: 0.7, scored_count: 10, demonstration: false }),
        ],
      }),
    ]);
    const course = findCourse(buildCourses(seeded), "mis-200")!;
    const view = buildEvidence(seeded, course, findOutcome(course, "SLO2")!);
    expect(view.ranked.find((r) => r.model_key === "luna")!.seeded).toBe(true);
    expect(view.ranked.find((r) => r.model_key === "vega")!.seeded).toBe(false);
    expect(view.demonstration.any).toBe(true);
  });
});
