/**
 * Model versions collapse into family rows, from registry data.
 *
 * ⚠ THE RULES ARE HONESTY RULES: never an average, the colour follows the
 * weakest member, absent members are excluded, and the ceiling is never rounded
 * up at either end of a range.
 */

import { describe, expect, it } from "vitest";

import { board, result, task } from "./fixtures";
import { buildMajorMatrix } from "@/lib/explore-matrix";
import { collapseCells, formatScoreRange, groupFamilies } from "@/lib/families";
import { rampStep, type MatrixCell } from "@/lib/matrix";

const member = (key: string, name: string, order: number, score: number | null) =>
  result({
    model_key: key,
    display_name: name,
    family: "claude-opus",
    family_display_name: "Claude Opus",
    display_order: order,
    mean_score: score,
    scored_count: score === null ? 0 : 10,
  });

function familyBoard(scores: (number | null)[]) {
  return board([
    task({
      task_id: "slo2/break-even",
      family: "mis200-is-concepts",
      slo: "SLO2",
      has_results: true,
      best_model_key: "luna",
      results: [
        ...scores.map((s, i) => member(`opus-${i}`, `Claude Opus 5.${i}`, 20 + i, s)),
        result({ model_key: "luna", display_name: "Luna", mean_score: 0.5, display_order: 50 }),
      ],
    }),
  ]);
}

const cell = (score: number | null): MatrixCell => ({
  slo: "x",
  status: score === null ? "not_measured" : "measured",
  score,
  step: score === null ? 0 : rampStep(score),
  confidence: "high",
  measuredTasks: 1,
  tasksAvailable: 1,
  scoredSamples: 10,
  runId: "run-1",
  reason: "",
});

describe("formatScoreRange", () => {
  it("shows one value when the ends agree", () => {
    expect(formatScoreRange(1, 1)).toBe("100%");
  });
  it("shows min–max with one percent sign", () => {
    expect(formatScoreRange(0.96, 1)).toBe("96–100%");
  });
  it("never rounds 99.58% up, at either end", () => {
    expect(formatScoreRange(0.9958, 1)).toBe("99–100%");
    expect(formatScoreRange(0.9958, 0.9962)).toBe("99%");
  });
});

describe("collapseCells", () => {
  it("never averages: mixed scores give the range, coloured by the minimum", () => {
    const fc = collapseCells([cell(1), cell(0.96), cell(1)], "Claude Opus");
    expect(fc.text).toBe("96–100%");
    expect(fc.cell.score).toBe(0.96);
    expect(fc.cell.step).toBe(rampStep(0.96));
    expect(fc.cell.runId).toBeNull();
  });
  it("shows a single value when every measured member agrees", () => {
    expect(collapseCells([cell(0.8), cell(0.8)], "F").text).toBe("80%");
  });
  it("excludes members with no result", () => {
    const fc = collapseCells([cell(null), cell(0.9), cell(0.5)], "F");
    expect(fc.text).toBe("50–90%");
  });
  it("is the empty cell when no member has a result", () => {
    const fc = collapseCells([cell(null), cell(null)], "F");
    expect(fc.text).toBeUndefined();
    expect(fc.cell.status).toBe("not_measured");
  });
});

describe("groupFamilies", () => {
  it("groups by the registry family field, newest first, and leaves unfamilied models single", () => {
    const rows = buildMajorMatrix(familyBoard([1, 1, 0.96])).models;
    const grouped = groupFamilies(rows);
    expect(grouped.map((g) => g.kind)).toEqual(["family", "single"]);
    const fam = grouped[0]!;
    if (fam.kind !== "family") throw new Error("expected a family");
    expect(fam.label).toBe("Claude Opus · 3 versions");
    expect(fam.members.map((m) => m.model_key)).toEqual(["opus-0", "opus-1", "opus-2"]);
    expect(fam.overall.text).toBe("96–100%");
  });

  it("treats a family of one as a plain model row", () => {
    const rows = buildMajorMatrix(familyBoard([0.9])).models;
    expect(groupFamilies(rows).map((g) => g.kind)).toEqual(["single", "single"]);
  });
});
