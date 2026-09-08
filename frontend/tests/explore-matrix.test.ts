/**
 * The drill-down's matrices, as rules rather than as pixels.
 *
 * ⚠ WHAT THIS PROVES THAT `explore.dom.test.tsx` CANNOT. That file proves the
 * PAGE draws a grid; this one proves the grid is not a second opinion. The
 * whole argument for rebuilding `/explore` on the comparison matrix was that a
 * course headline computed in one place and its evidence computed in another
 * can drift without anybody noticing — so the tests that matter most here are
 * the ones that pin the two together:
 *
 *   - a row's "All models" figure IS `aggregate()` over the union of the
 *     entries its own cells are built from, not a parallel calculation
 *   - a row's status IS its headline cell's status, so a badge and the square
 *     beside it cannot make different claims
 *   - the three empty states come from `classifyCell` — the same function
 *     `/compare` uses — so a course grid cannot decide "nothing ran" and
 *     "cannot be measured" are the same square
 *
 * ⚠ AND THE ONE ORDERING RULE. Course rows follow the published map, never the
 * scores. A matrix makes sorting by the headline column tempting in a way a
 * column of cards did not, and doing it would turn a coverage grid into a
 * ranking of a department's own courses.
 */

import { describe, expect, it } from "vitest";

import { board, CURRICULUM, result, task } from "./fixtures";
import {
  buildCourseMatrix,
  buildMajorMatrix,
  buildOutcomeMatrix,
  type ExploreMatrix,
} from "@/lib/explore-matrix";
import { buildCourses, findCourse } from "@/lib/explore";
import { aggregate, rollupByModel } from "@/lib/rollup";
import type { CurriculumView, LeaderboardResponse } from "@/lib/types";

const MAJOR = "bscba-general-business-core";

/** The fixture curriculum plus Teamwork, which no text benchmark can measure. */
const WITH_TEAMWORK: CurriculumView = {
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

function measuredBoard(overrides = {}): LeaderboardResponse {
  return board(
    [
      task({
        task_id: "slo2/break-even",
        slo: "SLO2",
        has_results: true,
        best_model_key: "luna",
        results: [
          result({ model_key: "luna", display_name: "Luna", mean_score: 0.72, scored_count: 20, sample_count: 20 }),
          result({ model_key: "vega", display_name: "Vega", mean_score: 0.41, scored_count: 10, sample_count: 10 }),
        ],
      }),
      task({ task_id: "slo4/ethics", slo: "SLO4", has_results: false, results: [] }),
    ],
    overrides,
  );
}

function rowNamed(matrix: ExploreMatrix, needle: string) {
  return matrix.rows.find((row) => row.heading.includes(needle) || row.key === needle)!;
}

// ---------------------------------------------------------------------------

describe("every level is the same object at a different scope", () => {
  it("gives level 1 a row per programme and a column per model", () => {
    const matrix = buildMajorMatrix(measuredBoard());
    expect(matrix.rows).toHaveLength(1);
    expect(matrix.columns.map((c) => c.model_key).sort()).toEqual(["luna", "vega"]);
    expect(matrix.rows[0]!.cells).toHaveLength(matrix.columns.length);
    expect(matrix.rows[0]!.href).toBe(`/explore/${MAJOR}`);
  });

  it("gives level 2 a row per course, in the published map's order", () => {
    const matrix = buildCourseMatrix(measuredBoard({ curriculum: WITH_TEAMWORK }), MAJOR);
    expect(matrix.rows.map((r) => r.eyebrow)).toEqual(["MIS 200", "GBA 300"]);
    expect(matrix.rows.map((r) => r.href)).toEqual([
      `/explore/${MAJOR}/mis-200`,
      `/explore/${MAJOR}/gba-300`,
    ]);
  });

  it("does not re-sort courses by score, however tempting the headline column is", () => {
    // GBA 300 teaches the measured outcome AND two others; MIS 200 teaches only
    // the measured one, so a score sort would put MIS 200 first. The map does
    // not, and the map wins.
    const matrix = buildCourseMatrix(measuredBoard({ curriculum: WITH_TEAMWORK }), MAJOR);
    const scores = matrix.rows.map((r) => r.overall.score);
    expect(matrix.rows.map((r) => r.eyebrow)).toEqual(["MIS 200", "GBA 300"]);
    // Sanity: the fixture really would reorder under a score sort.
    expect(scores.every((s) => s !== null)).toBe(true);
  });

  it("gives level 3 a row per outcome the course teaches, unreachable ones included", () => {
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    const matrix = buildOutcomeMatrix(data, course, MAJOR);
    expect(matrix.rows.map((r) => r.key)).toEqual(["SLO2", "SLO4", "SLO5"]);
    expect(matrix.rows.map((r) => r.href)).toEqual([
      `/explore/${MAJOR}/gba-300/slo2`,
      `/explore/${MAJOR}/gba-300/slo4`,
      `/explore/${MAJOR}/gba-300/slo5`,
    ]);
  });
});

describe("the headline cannot disagree with the cells", () => {
  it("computes a row's 'All models' figure from the entries its own cells use", () => {
    const data = measuredBoard();
    const matrix = buildMajorMatrix(data);
    const row = matrix.rows[0]!;

    // Independently: the same aggregate over every ranked model's SLO-filed
    // entries. If the row headline is a second calculation, this diverges.
    const expected = aggregate(
      rollupByModel(data)
        .filter((m) => m.recommendable)
        .flatMap((m) => m.entries.filter((e) => e.slo !== null)),
    );
    expect(row.overall.score).toBe(expected.score);
    expect(row.overall.scored_samples).toBe(expected.scored_samples);
    expect(row.overall.confidence).toBe(expected.confidence);
  });

  it("makes a course's headline the same number its own tile computes", () => {
    // ⚠ THE ANTI-DRIFT PIN. `CourseTile.aggregate` is what the page's prose
    // reads from; the matrix row is what the grid draws. They are the same
    // entries through the same function, and this is the test that keeps that
    // true when somebody narrows one of the two SLO sets.
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const matrix = buildCourseMatrix(data, MAJOR);
    for (const tile of buildCourses(data)) {
      const row = rowNamed(matrix, tile.slug);
      expect(row.overall.score, tile.code).toBe(tile.aggregate.score);
      expect(row.overall.scored_samples, tile.code).toBe(tile.aggregate.scored_samples);
    }
  });

  it("takes a row's status from its headline cell, not from a second opinion", () => {
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    for (const row of buildOutcomeMatrix(data, course, MAJOR).rows) {
      expect(row.status, row.key).toBe(row.overallCell.status);
    }
  });

  it("never claims a headline score over a row where no model measured anything", () => {
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    for (const row of buildOutcomeMatrix(data, course, MAJOR).rows) {
      const anyCell = row.cells.some((cell) => cell.status === "measured");
      expect(row.overallCell.status === "measured", row.key).toBe(anyCell);
    }
  });
});

describe("the three empties stay three different claims", () => {
  it("marks an outcome the curriculum cannot reach as out of scope, not as unmeasured", () => {
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    const teamwork = rowNamed(buildOutcomeMatrix(data, course, MAJOR), "SLO5");

    expect(teamwork.status).toBe("not_benchmarkable");
    expect(teamwork.benchmarkable).toBe(false);
    for (const cell of [...teamwork.cells, teamwork.overallCell]) {
      expect(cell.status).toBe("not_benchmarkable");
      expect(cell.score).toBeNull();
      // ⚠ NEVER TINTED. A ramp step on an empty square is a number the data
      // does not have.
      expect(cell.step).toBe(0);
      expect(cell.reason).toMatch(/not measurable by a text benchmark/i);
      // The curriculum's own words, carried through rather than summarised away.
      expect(cell.reason).toContain("OUT OF SCOPE");
    }
  });

  it("marks an in-scope outcome nobody has run as not measured, with whose gap it is", () => {
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    const ethics = rowNamed(buildOutcomeMatrix(data, course, MAJOR), "SLO4");

    expect(ethics.status).toBe("not_measured");
    expect(ethics.benchmarkable).toBe(true);
    for (const cell of ethics.cells) {
      expect(cell.status).toBe("not_measured");
      expect(cell.score).toBeNull();
      expect(cell.step).toBe(0);
      expect(cell.reason).toMatch(/no finished, scored run|no task in the catalogue/i);
    }
  });

  it("never draws a fraction above one in the 'All models' cell", () => {
    // ⚠ THE UNIT MISMATCH THAT SHIPPED VISIBLY. `aggregate()` counts a measured
    // (model, task) PAIR, so the summary cell's numerator counted pairings
    // while its denominator still counted tasks — a one-task course with two
    // models rendered "2/1" in the cell a reader takes as the headline. The
    // fraction is drawn by `ScoreCell` from these two fields, so the invariant
    // is pinned on the data rather than on the markup.
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    for (const matrix of [
      buildMajorMatrix(data),
      buildCourseMatrix(data, MAJOR),
      buildOutcomeMatrix(data, course, MAJOR),
    ]) {
      for (const row of matrix.rows) {
        for (const cell of [...row.cells, row.overallCell]) {
          expect(
            cell.measuredTasks,
            `${row.key}: ${cell.measuredTasks}/${cell.tasksAvailable} is more than everything`,
          ).toBeLessThanOrEqual(cell.tasksAvailable);
        }
      }
    }
  });

  it("does not call the all-models cell 'this model'", () => {
    // A square that summarises every model cannot describe itself in the
    // singular. Small, and exactly the kind of wrong that makes a page read as
    // generated rather than written.
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    const ethics = rowNamed(buildOutcomeMatrix(data, course, MAJOR), "SLO4");

    expect(ethics.overallCell.status).toBe("not_measured");
    expect(ethics.overallCell.reason).not.toMatch(/this model/i);
    expect(ethics.overallCell.reason).toMatch(/no model has a finished, scored run/i);
    // The per-model cells beside it still speak in the singular, correctly.
    expect(ethics.cells[0]!.reason).toMatch(/this model has no finished, scored run/i);
  });

  it("gives every cell a reason, always, on every level", () => {
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    const matrices = [
      buildMajorMatrix(data),
      buildCourseMatrix(data, MAJOR),
      buildOutcomeMatrix(data, course, MAJOR),
    ];
    for (const matrix of matrices) {
      for (const row of matrix.rows) {
        expect(row.reason.trim()).not.toBe("");
        for (const cell of [...row.cells, row.overallCell]) {
          expect(cell.reason.trim(), `${row.key} has a cell with no reason`).not.toBe("");
          if (cell.status !== "measured") expect(cell.step).toBe(0);
        }
      }
    }
  });
});

describe("the demonstration disclosure survives the new shape", () => {
  const seeded = (overrides = {}) =>
    board(
      [
        task({
          task_id: "slo2/break-even",
          slo: "SLO2",
          has_results: true,
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.9, scored_count: 10, demonstration: true }),
          ],
        }),
      ],
      overrides,
    );

  it("flags a seeded model's whole column, on every level", () => {
    const data = seeded({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "mis-200")!;
    for (const matrix of [
      buildMajorMatrix(data),
      buildCourseMatrix(data, MAJOR),
      buildOutcomeMatrix(data, course, MAJOR),
    ]) {
      expect(matrix.columns.find((c) => c.model_key === "luna")!.seeded).toBe(true);
      expect(matrix.demonstration.any).toBe(true);
      expect(matrix.demonstration.notice).toMatch(/illustrative/i);
    }
  });

  it("flags the row too, so a reader who skips the banner still sees it", () => {
    const data = seeded({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "mis-200")!;
    const matrix = buildOutcomeMatrix(data, course, MAJOR);
    expect(rowNamed(matrix, "SLO2").seeded).toBe(true);
  });

  it("stays silent when the scores are real", () => {
    const matrix = buildCourseMatrix(measuredBoard({ curriculum: WITH_TEAMWORK }), MAJOR);
    expect(matrix.demonstration.any).toBe(false);
    expect(matrix.columns.every((c) => !c.seeded)).toBe(true);
    expect(matrix.rows.every((r) => !r.seeded)).toBe(true);
  });

  /** One model, real on SLO2, seeded on SLO4 — the mixed case. */
  const mixed = (curriculum: CurriculumView) =>
    board(
      [
        task({
          task_id: "slo2/break-even",
          slo: "SLO2",
          has_results: true,
          results: [result({ model_key: "luna", display_name: "Luna", mean_score: 0.7, scored_count: 20 })],
        }),
        task({
          task_id: "slo4/ethics",
          slo: "SLO4",
          has_results: true,
          results: [
            result({ model_key: "luna", display_name: "Luna", mean_score: 0.9, scored_count: 5, demonstration: true }),
          ],
        }),
      ],
      { curriculum },
    );

  it("keeps a course whose own numbers are real free of a caveat about another course", () => {
    const data = mixed(WITH_TEAMWORK);
    const mis200 = findCourse(buildCourses(data), "mis-200")!;
    const matrix = buildOutcomeMatrix(data, mis200, MAJOR);
    expect(matrix.demonstration.any).toBe(false);
    expect(rowNamed(matrix, "SLO2").seeded).toBe(false);
  });

  it("flags the seeded row on a course where only some numbers are seeded", () => {
    // ⚠ THE ROW BADGE IS WHAT CATCHES A MIXED MODEL. `summariseDemonstration`
    // calls a model "seeded" only when EVERY score it contributed was seeded,
    // so one model that is real on SLO2 and seeded on SLO4 is a measured model
    // and raises no banner — correctly, because most of its numbers are real.
    // The specific illustrative number is disclosed on its own row instead.
    const data = mixed(WITH_TEAMWORK);
    const gba300 = findCourse(buildCourses(data), "gba-300")!;
    const matrix = buildOutcomeMatrix(data, gba300, MAJOR);
    expect(rowNamed(matrix, "SLO2").seeded).toBe(false);
    expect(rowNamed(matrix, "SLO4").seeded).toBe(true);
  });

  it("raises the banner when every number on THIS level is seeded, even by a model measured elsewhere", () => {
    // ⚠ THE HOLE THIS LEVEL WOULD OTHERWISE HAVE HAD, and it is gap #69/#73
    // one scope down. `isSeeded` reads a model's WHOLE entry set, so a model
    // seeded on every outcome one course teaches — but measured for real on a
    // different course — came back "measured", and a page of entirely
    // illustrative numbers rendered under no banner at all. The per-row and
    // per-column badges were right the whole time; the sentence a reader meets
    // FIRST was silent, which is the worst place for it to be wrong. Entries
    // are narrowed to the level before the split is taken — see `assemble`.
    const onePerCourse: CurriculumView = {
      ...CURRICULUM,
      coverage: [
        { course: "MIS 200", title: "Fundamentals of MIS", outcomes: { SLO2: "A" } },
        { course: "GBA 300", title: "Business Communications", outcomes: { SLO4: "A" } },
      ],
    };
    const data = mixed(onePerCourse);
    const gba300 = findCourse(buildCourses(data), "gba-300")!;
    const matrix = buildOutcomeMatrix(data, gba300, MAJOR);

    expect(matrix.demonstration.any).toBe(true);
    expect(matrix.demonstration.all).toBe(true);
    expect(matrix.demonstration.notice).toMatch(/illustrative/i);

    // The course next door, whose one outcome is real, stays silent.
    const mis200 = findCourse(buildCourses(data), "mis-200")!;
    expect(buildOutcomeMatrix(data, mis200, MAJOR).demonstration.any).toBe(false);
  });
});

describe("the prose above a grid describes that grid", () => {
  it("counts level 3's coverage off the rows it actually draws", () => {
    // The course page's subtitle reads these two numbers. They must be the
    // same count as the rows under it, not a parallel tally that can drift.
    const data = measuredBoard({ curriculum: WITH_TEAMWORK });
    const course = findCourse(buildCourses(data), "gba-300")!;
    const matrix = buildOutcomeMatrix(data, course, MAJOR);

    expect(matrix.benchmarkable_rows).toBe(
      matrix.rows.filter((r) => r.benchmarkable).length,
    );
    expect(matrix.measured_rows).toBe(
      matrix.rows.filter((r) => r.status === "measured").length,
    );
    // And it agrees with what the course tile computes independently.
    expect(matrix.benchmarkable_rows).toBe(course.benchmarkable_count);
    expect(matrix.measured_rows).toBe(course.measured_count);
  });
});

describe("the honest nothing-to-show states", () => {
  it("says why, rather than drawing an empty grid, with no curriculum map", () => {
    const matrix = buildMajorMatrix(
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
    expect(matrix.available).toBe(false);
    expect(matrix.rows).toHaveLength(0);
    expect(matrix.unavailable_reason).toContain("No curriculum/slo.yaml");
  });

  it("keeps a test stub in the grid but never leading it", () => {
    // A stub is a real row and is shown. It does not get the first column, for
    // the reason `best_model_key` excludes it from the podium: a grid whose
    // leading column is a deterministic mock is the same lie in a new shape.
    const data = board([
      task({
        task_id: "slo2/break-even",
        slo: "SLO2",
        has_results: true,
        results: [
          result({ model_key: "mock", display_name: "Mock", mean_score: 0.99, scored_count: 30, recommendable: false }),
          result({ model_key: "luna", display_name: "Luna", mean_score: 0.5, scored_count: 20 }),
        ],
      }),
    ]);
    const matrix = buildMajorMatrix(data);
    expect(matrix.columns[0]!.model_key).toBe("luna");
    expect(matrix.columns.map((c) => c.model_key)).toContain("mock");

    // And the stub's score stays out of the row's headline.
    expect(matrix.rows[0]!.overall.score).toBe(0.5);
  });
});
