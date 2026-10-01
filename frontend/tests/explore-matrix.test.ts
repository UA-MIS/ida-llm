/**
 * The drill-down as a matrix, and the orientation it commits to.
 *
 * ⚠ THE ORIENTATION IS A CLAIM, WHICH IS WHY IT IS TESTED AND NOT LEFT TO CSS.
 * Models are ROWS and entities are COLUMNS. A vertical list is read as a
 * ranking whether or not one was meant, so the axis running down the page has
 * to be the axis where order MEANS something: model order is a rank, and this
 * file asserts the rank. Entity order is not — majors are the catalog's eleven
 * and classes are a course listing — so this file asserts, separately, that
 * entity order is the catalog's and is never re-sorted by score. Transposing
 * the grid back would be a silent change of meaning: nothing would crash, and
 * the page would start asserting that Accounting outranks Marketing.
 *
 * ⚠ AND THE THREE CLICK TARGETS ARE PART OF THE CONTRACT. A cell is a crossing
 * of two things, so its link carries both; a column header carries only the
 * entity; a row header carries only the model. Collapsing any of the three into
 * another loses a question a reader can currently ask.
 */

import { describe, expect, it } from "vitest";

import { board, CURRICULUM, result, task } from "./fixtures";
import { buildIndex, findMajor } from "@/lib/explore";
import {
  buildAssignmentMatrix,
  buildClassMatrix,
  buildMajorMatrix,
  buildOutcomeMatrix,
  cellHref,
} from "@/lib/explore-matrix";
import { buildClasses, findClass } from "@/lib/explore";
import type { LeaderboardResponse } from "@/lib/types";

const MIS = "management-information-systems";
const GEN = "general-business";

function majorOf(b: LeaderboardResponse, id: string) {
  const tile = findMajor(buildIndex(b), id);
  if (!tile) throw new Error(`fixture has no major ${id}`);
  return tile;
}

/** Two models, both scored on the `slo2` family MIS 200 claims. */
function twoModelBoard(): LeaderboardResponse {
  return board([
    task({
      task_id: "slo2/break-even",
      family: "slo2",
      slo: "SLO2",
      has_results: true,
      best_model_key: "sol",
      results: [
        result({ model_key: "luna", display_name: "Luna", mean_score: 0.4 }),
        result({ model_key: "sol", display_name: "Sol", mean_score: 0.8 }),
      ],
    }),
  ]);
}

// ---------------------------------------------------------------------------

describe("the orientation", () => {
  it("puts models on the row axis and entities on the column axis", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    expect(matrix.models.map((m) => m.model_key).sort()).toEqual(["luna", "sol"]);
    expect(matrix.entities.map((e) => e.key)).toEqual([MIS, GEN]);
  });

  it("gives every model one cell per entity, in entity order", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    for (const model of matrix.models) {
      expect(model.cells).toHaveLength(matrix.entities.length);
      expect(model.cells.map((c) => c.slo)).toEqual(
        matrix.entities.map((e) => `${e.key}:${model.model_key}`),
      );
    }
  });

  it("orders model rows as a ranking — coverage first, then score", () => {
    // The row axis is read as a ranking, so it has to BE one, and it has to be
    // the same rule `/compare` defends: a model measured on one entity has not
    // answered "which should I use", however well it did there.
    const matrix = buildMajorMatrix(twoModelBoard());
    expect(matrix.models.map((m) => m.model_key)).toEqual(["sol", "luna"]);
    expect(matrix.models[0]!.overall.score).toBeCloseTo(0.8);
  });

  it("never leads with a test stub, whatever it scored", () => {
    const b = board([
      task({
        task_id: "slo2/break-even",
        family: "slo2",
        slo: "SLO2",
        has_results: true,
        results: [
          result({ model_key: "mock", display_name: "Mock", recommendable: false, mean_score: 1 }),
          result({ model_key: "luna", display_name: "Luna", mean_score: 0.3 }),
        ],
      }),
    ]);
    const matrix = buildMajorMatrix(b);
    expect(matrix.models.map((m) => m.model_key)).toEqual(["luna", "mock"]);
  });

  it("does not re-sort entity columns by score", () => {
    // GEN scores nothing and MIS scores 0.8. A score-ordered axis would move
    // MIS first — which it already is — so prove it the other way: the columns
    // match the taxonomy's order exactly, whatever the numbers do.
    const matrix = buildMajorMatrix(twoModelBoard());
    expect(matrix.entities.map((e) => e.key)).toEqual(
      CURRICULUM.majors.map((m) => m.id),
    );
  });

  it("keeps classes in the catalog's order on level 2", () => {
    const b = twoModelBoard();
    const matrix = buildClassMatrix(b, majorOf(b, MIS));
    expect(matrix.entities.map((e) => e.eyebrow)).toEqual(["MIS 200", "MIS 221"]);
  });
});

// ---------------------------------------------------------------------------

describe("the three click targets", () => {
  it("sends a column header one level down, across every model", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    expect(matrix.entities[0]!.href).toBe(`/explore/${MIS}`);

    const b = twoModelBoard();
    const classes = buildClassMatrix(b, majorOf(b, MIS));
    expect(classes.entities[0]!.href).toBe(`/explore/${MIS}/mis-200`);

    const tile = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    const outcomes = buildOutcomeMatrix(b, tile, MIS);
    expect(outcomes.entities[0]!.href).toBe(`/explore/${MIS}/mis-200/slo2`);
  });

  it("sends a model row header to that model's own report card", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    expect(matrix.models[0]!.href).toBe("/models/sol");
  });

  it("sends a score cell one level down CARRYING the model it was about", () => {
    // A cell is a crossing. Dropping the model half on arrival would throw away
    // the specific thing the reader just clicked and hand them the full field
    // they had already narrowed.
    const matrix = buildMajorMatrix(twoModelBoard());
    expect(cellHref(matrix.entities[0]!, "sol")).toBe(`/explore/${MIS}?model=sol`);
  });

  it("escapes a model key that would otherwise break the query string", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    expect(cellHref(matrix.entities[0]!, "a b&c")).toBe(
      `/explore/${MIS}?model=a%20b%26c`,
    );
  });
});

// ---------------------------------------------------------------------------

describe("the summaries cannot disagree with the cells they summarise", () => {
  it("computes a column's 'All models' summary from the same entries as its cells", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    const mis = matrix.entities.find((e) => e.key === MIS)!;
    const cells = matrix.models.map(
      (m) => m.cells[matrix.entities.indexOf(mis)]!,
    );
    const scores = cells.filter((c) => c.score !== null).map((c) => c.score!);
    expect(scores).toHaveLength(2);
    // The summary is the sample-weighted mean of the same entries, so it must
    // sit between the two cells rather than being a separate opinion.
    expect(mis.overall.score).toBeGreaterThanOrEqual(Math.min(...scores));
    expect(mis.overall.score).toBeLessThanOrEqual(Math.max(...scores));
    expect(mis.overallCell.status).toBe("measured");
    expect(mis.status).toBe(mis.overallCell.status);
  });

  it("gives each model a trailing summary across the whole level", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    const sol = matrix.models.find((m) => m.model_key === "sol")!;
    expect(sol.overallCell.status).toBe("measured");
    expect(sol.overall.score).toBeCloseTo(0.8);
    // The number the row's position in the sort is built from, shown so the
    // ranking can be checked rather than taken on trust.
    expect(sol.measuredCount).toBe(1);
  });

  it("counts pairings, not tasks, in a summary cell's denominator", () => {
    // `aggregate()` counts a measured (model, task) PAIR, so a one-task class
    // with two models once rendered "2/1" — a fraction above one, in the cell a
    // reader takes as the headline.
    const matrix = buildMajorMatrix(twoModelBoard());
    const mis = matrix.entities.find((e) => e.key === MIS)!;
    expect(mis.overallCell.measuredTasks).toBeLessThanOrEqual(
      mis.overallCell.tasksAvailable,
    );
  });

  it("says 'no model has' in a summary cell, never 'this model has'", () => {
    const gen = buildMajorMatrix(twoModelBoard()).entities.find((e) => e.key === GEN)!;
    expect(gen.overallCell.reason).not.toMatch(/this model/i);
  });
});

// ---------------------------------------------------------------------------

describe("the three empty states survive the flip", () => {
  it("keeps 'nothing ran' and 'cannot be measured' as different squares", () => {
    const withTeamwork = {
      ...CURRICULUM,
      outcomes: [
        ...CURRICULUM.outcomes,
        {
          id: "SLO5",
          title: "Teamwork",
          statement: "Students work effectively on teams.",
          text_benchmarkable: false,
          benchmark_note: "OUT OF SCOPE for a text benchmark.",
        },
      ],
      coverage: [
        { course: "MIS 200", title: "Fundamentals of MIS", outcomes: { SLO2: "A", SLO5: "M+A" } },
        ...CURRICULUM.coverage.filter((c) => c.course !== "MIS 200"),
      ],
    };
    const b = { ...twoModelBoard(), curriculum: withTeamwork };
    const tile = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    const matrix = buildOutcomeMatrix(b, tile, MIS);

    const byKey = new Map(matrix.entities.map((e, i) => [e.key, i]));
    const row = matrix.models[0]!;
    expect(row.cells[byKey.get("SLO2")!]!.status).toBe("measured");
    expect(row.cells[byKey.get("SLO5")!]!.status).toBe("not_benchmarkable");
    // And the out-of-scope column is still DRAWN — dropping it would make
    // MIS 200 look like a one-outcome class.
    expect(matrix.entities.map((e) => e.key)).toContain("SLO5");
  });

  it("never tints a cell that has no score", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    for (const model of matrix.models) {
      for (const cell of model.cells) {
        if (cell.status !== "measured") {
          expect(cell.score).toBeNull();
          expect(cell.step).toBe(0);
        }
      }
    }
  });

  it("gives every cell a reason, measured or not", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    for (const model of matrix.models) {
      for (const cell of model.cells) {
        expect(cell.reason.length).toBeGreaterThan(0);
      }
    }
  });
});

// ---------------------------------------------------------------------------

describe("a class shows only its own results, in the grid too", () => {
  it("leaves a class with no task family empty beside a measured sibling", () => {
    const b = twoModelBoard();
    const matrix = buildClassMatrix(b, majorOf(b, MIS));
    const byKey = new Map(matrix.entities.map((e, i) => [e.key, i]));
    const sol = matrix.models.find((m) => m.model_key === "sol")!;

    expect(sol.cells[byKey.get("mis-200")!]!.status).toBe("measured");
    expect(sol.cells[byKey.get("mis-221")!]!.status).toBe("not_measured");
    expect(sol.cells[byKey.get("mis-221")!]!.score).toBeNull();
  });

  it("leaves a whole major empty when nothing was written about its classes", () => {
    const matrix = buildMajorMatrix(twoModelBoard());
    const gen = matrix.entities.find((e) => e.key === GEN)!;
    expect(gen.status).toBe("not_measured");
    expect(gen.overall.score).toBeNull();
  });
});

// ---------------------------------------------------------------------------

describe("the level's own coverage line", () => {
  it("counts entities, which is what sits under the sentence", () => {
    const b = twoModelBoard();
    const tile = findClass(buildClasses(b, majorOf(b, MIS)), "mis-200")!;
    const matrix = buildOutcomeMatrix(b, tile, MIS);
    expect(matrix.benchmarkable_entities).toBe(
      matrix.entities.filter((e) => e.benchmarkable).length,
    );
    expect(matrix.measured_entities).toBe(
      matrix.entities.filter((e) => e.benchmarkable && e.status === "measured").length,
    );
  });
});

// ---------------------------------------------------------------------------

describe("the honest unavailable states", () => {
  it("says why there is no grid when the deployment has no taxonomy", () => {
    const matrix = buildMajorMatrix(
      board([], { curriculum: { ...CURRICULUM, majors: [], unassigned_core: [] } }),
    );
    expect(matrix.available).toBe(false);
    expect(matrix.unavailable_reason).toMatch(/majors/i);
    expect(matrix.entities).toEqual([]);
  });

  it("says why a class has no outcome breakdown, without blaming the class", () => {
    const b = twoModelBoard();
    const mis221 = findClass(buildClasses(b, majorOf(b, MIS)), "mis-221")!;
    const matrix = buildOutcomeMatrix(b, mis221, MIS);
    expect(matrix.available).toBe(false);
    expect(matrix.unavailable_reason).toMatch(/gap in the map, not in the class/i);
  });
});

// ---------------------------------------------------------------------------

describe("the demonstration split is scoped to the level", () => {
  it("does not caveat a level whose own numbers are all real", () => {
    expect(buildMajorMatrix(twoModelBoard()).demonstration.any).toBe(false);
  });

  it("flags a seeded score on the column that carries it", () => {
    const b = board([
      task({
        task_id: "slo2/break-even",
        family: "slo2",
        slo: "SLO2",
        has_results: true,
        results: [result({ mean_score: 0.72, demonstration: true })],
      }),
    ]);
    const matrix = buildMajorMatrix(b);
    expect(matrix.demonstration.any).toBe(true);
    expect(matrix.entities.find((e) => e.key === MIS)!.seeded).toBe(true);
    expect(matrix.models[0]!.seeded).toBe(true);
  });

  it("does not flag a model as seeded here for something seeded elsewhere", () => {
    // The half that was wrong once already: `isSeeded` reads a model's WHOLE
    // entry set, so a model measured for real on this level came back "seeded"
    // — or worse, the reverse — unless entries are narrowed to the level FIRST.
    const b = board([
      task({
        task_id: "slo2/break-even",
        family: "slo2",
        slo: "SLO2",
        has_results: true,
        results: [result({ mean_score: 0.72, demonstration: false })],
      }),
      task({
        task_id: "other/thing",
        family: "other",
        slo: "SLO4",
        has_results: true,
        results: [result({ mean_score: 0.5, demonstration: true })],
      }),
    ]);
    const matrix = buildMajorMatrix(b);
    expect(matrix.entities.find((e) => e.key === MIS)!.seeded).toBe(false);
    expect(matrix.demonstration.any).toBe(false);
  });
});


describe("assignment breakdown", () => {
  it("groups exam families across SLOs, separates cases, and leaves quizzes unmeasured", () => {
    const b = board([
      task({ family: "mis200-spreadsheet-formulas", task_id: "formulas/one", slo: "SLO2", results: [result({ mean_score: 0.8 })] }),
      task({ family: "mis200-is-concepts", task_id: "concepts/one", slo: "SLO9", results: [result({ mean_score: 0.2 })] }),
      task({ family: "mis200-is-problem-solving", task_id: "cases/one", slo: "SLO1", results: [result({ mean_score: 0.9 })] }),
      task({ family: "unrelated", task_id: "unrelated/one", slo: "SLO2", results: [result({ mean_score: 1 })] }),
    ]);
    const klass = buildClasses(b, majorOf(b, MIS))[0]!;
    const matrix = buildAssignmentMatrix(b, { ...klass, task_families: [
      "mis200-spreadsheet-formulas", "mis200-is-concepts", "mis200-is-problem-solving",
    ] }, MIS);
    expect(matrix.entities.map((e) => e.heading)).toEqual(["Exams", "Quizzes", "Case analysis"]);
    expect(matrix.entities[0]!.overall.score).toBeCloseTo(0.5);
    expect(matrix.entities[1]!.overall.score).toBeNull();
    expect(matrix.entities[2]!.overall.score).toBeCloseTo(0.9);
    expect(matrix.entities[2]!.footnote).toContain("extension");
    expect(matrix.entities[0]!.href).toContain("/exams");
    expect(matrix.models[0]!.overall.score).toBeCloseTo(1.9 / 3);
  });
});
