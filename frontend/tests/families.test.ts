/**
 * A collapsed family is its NEWEST model (lowest `display_order`), unchanged:
 * its own cells, never a range, an average, or the best member per column.
 */

import { describe, expect, it } from "vitest";

import { board, result, task } from "./fixtures";
import { buildMajorMatrix } from "@/lib/explore-matrix";
import { groupFamilies } from "@/lib/families";

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

describe("groupFamilies", () => {
  it("groups by the registry family field and leaves unfamilied models single", () => {
    const rows = buildMajorMatrix(familyBoard([1, 1, 0.96])).models;
    const grouped = groupFamilies(rows);
    expect(grouped.map((g) => g.kind)).toEqual(["family", "single"]);
    const fam = grouped[0]!;
    if (fam.kind !== "family") throw new Error("expected a family");
    expect(fam.newest.model_key).toBe("opus-0");
    // The flagship is not repeated among the expanded rows.
    expect(fam.earlier.map((m) => m.model_key)).toEqual(["opus-1", "opus-2"]);
  });

  it("uses the newest by display_order even when an older version scores higher", () => {
    const b = board([
      task({
        task_id: "slo2/break-even",
        family: "mis200-is-concepts",
        slo: "SLO2",
        has_results: true,
        best_model_key: "h45",
        results: [
          member("h45", "Claude Haiku 4.5", 30, 0.98),
          member("h55", "Claude Haiku 5.5", 10, 0.96),
        ],
      }),
    ]);
    const fam = groupFamilies(buildMajorMatrix(b).models)[0]!;
    if (fam.kind !== "family") throw new Error("expected a family");
    expect(fam.newest.display_name).toBe("Claude Haiku 5.5");
    expect(fam.newest.overallCell.score).toBeCloseTo(0.96);
    expect(fam.earlier.map((m) => m.display_name)).toEqual(["Claude Haiku 4.5"]);
  });

  it("shows the empty cell, not an older score, when the newest has no result", () => {
    const fam = groupFamilies(buildMajorMatrix(familyBoard([null, 0.9, 0.8])).models)[0]!;
    if (fam.kind !== "family") throw new Error("expected a family");
    expect(fam.newest.model_key).toBe("opus-0");
    expect(fam.newest.cells.every((c) => c.status !== "measured" && c.score === null)).toBe(true);
    expect(fam.newest.overallCell.score).toBeNull();
  });

  it("every cell of the collapsed row comes from the one newest model", () => {
    const fam = groupFamilies(buildMajorMatrix(familyBoard([0.7, 1, 1])).models)[0]!;
    if (fam.kind !== "family") throw new Error("expected a family");
    const measured = [...fam.newest.cells, fam.newest.overallCell].filter(
      (c) => c.status === "measured",
    );
    expect(measured.length).toBeGreaterThan(0);
    for (const c of measured) expect(c.score).toBeCloseTo(0.7);
  });

  it("treats a family of one as a plain model row", () => {
    const rows = buildMajorMatrix(familyBoard([0.9])).models;
    expect(groupFamilies(rows).map((g) => g.kind)).toEqual(["single", "single"]);
  });
});
