/**
 * The per-class UNIT taxonomy's invariants.
 *
 * ⚠ THE ONE THAT MATTERS IS THE PARTITION. Results are a (model, task) mean per
 * family. If one family fed two units, the SAME number would print under both
 * headings — the "one exam's score under a dozen courses" fabrication
 * `lib/explore.ts` exists to prevent, one level down. So every family a class
 * lists lands in exactly one of its units; this file fails if two units ever
 * claim the same one.
 *
 * The subset-of-the-class's-own-families invariant (a unit cannot surface a
 * family the class does not claim) is enforced at runtime by `buildUnitMatrix`
 * and pinned in `explore-matrix.test.ts`; it is not re-checked here because it is
 * about the join with `majors.yaml`, which this module deliberately does not hold.
 */

import { describe, expect, it } from "vitest";

import {
  coursesWithUnits,
  findUnit,
  hasUnits,
  unitTitle,
  unitsFor,
} from "@/lib/units";

/** The families authored for MIS 200, per `tasks/mis200-*` and `majors.yaml`. */
const MIS200_FAMILIES = [
  "mis200-spreadsheet-formulas",
  "mis200-is-concepts",
  "mis200-is-problem-solving",
];

describe("every class's unit taxonomy", () => {
  for (const course of coursesWithUnits()) {
    describe(course, () => {
      const units = unitsFor(course);

      it("has at least one unit", () => {
        expect(units.length).toBeGreaterThan(0);
      });

      it("gives every unit a unique key, a title, a blurb and at least one topic it covers", () => {
        const keys = units.map((u) => u.key);
        expect(new Set(keys).size, "duplicate unit key").toBe(keys.length);
        for (const u of units) {
          expect(u.key, "empty key").not.toBe("");
          expect(u.title.length, `empty title on ${u.key}`).toBeGreaterThan(0);
          expect(u.blurb.length, `empty blurb on ${u.key}`).toBeGreaterThan(0);
          expect(u.covers.length, `no covers on ${u.key}`).toBeGreaterThan(0);
          for (const topic of u.covers) {
            expect(topic.length, `empty topic on ${u.key}`).toBeGreaterThan(0);
          }
        }
      });

      it("numbers the units 1..n in presentation order, with no gaps or repeats", () => {
        expect(units.map((u) => u.n)).toEqual(units.map((_, i) => i + 1));
      });

      it("gives a unit a source when, and only when, it has a family behind it", () => {
        // A `source` is the quiz/exercise set a score came from. A unit with no
        // family has no score and so must have no source — the honesty rule that
        // keeps "not measured yet" from quietly acquiring a provenance line.
        for (const u of units) {
          if (u.families.length === 0) {
            expect(u.source, `${u.key} is empty but names a source`).toBeUndefined();
          } else {
            expect(u.source, `${u.key} has families but no source`).toBeTruthy();
          }
        }
      });

      it("maps each family to EXACTLY ONE unit — a partition, never a duplicate", () => {
        const seen = new Map<string, string>();
        for (const u of units) {
          for (const family of u.families) {
            const prior = seen.get(family);
            expect(
              prior,
              `family ${family} is claimed by both ${prior} and ${u.key} — that would print one score twice`,
            ).toBeUndefined();
            seen.set(family, u.key);
          }
        }
      });
    });
  }
});

describe("MIS 200 specifically", () => {
  const CLS = "MIS 200";

  it("is a class with a taxonomy", () => {
    expect(hasUnits(CLS)).toBe(true);
    expect(hasUnits("MIS 221")).toBe(false);
  });

  it("breaks into five units in course order", () => {
    expect(unitsFor(CLS).map((u) => u.title)).toEqual([
      "Information systems & business models",
      "Competitive strategy with IS",
      "Spreadsheets & data analysis",
      "Platform & network economics",
      "Levels of IS use in organizations",
    ]);
  });

  it("references only families that were actually authored for the course", () => {
    for (const u of unitsFor(CLS)) {
      for (const family of u.families) {
        expect(MIS200_FAMILIES, `${u.key} references an unknown family ${family}`).toContain(family);
      }
    }
  });

  it("covers all three authored families across its units", () => {
    const covered = unitsFor(CLS).flatMap((u) => u.families);
    for (const family of MIS200_FAMILIES) {
      expect(covered, `no unit claims ${family}`).toContain(family);
    }
  });

  it("maps Unit 1 to the IS-concepts family", () => {
    expect(findUnit(CLS, "information-systems-business-models")!.families).toEqual([
      "mis200-is-concepts",
    ]);
  });

  it("files the synthetic SLO1 extension under Unit 2 (competitive strategy), with its caveat", () => {
    const unit = findUnit(CLS, "competitive-strategy-with-is")!;
    expect(unit.n).toBe(2);
    expect(unit.families).toEqual(["mis200-is-problem-solving"]);
    expect(unit.caveat, "the synthetic-extension caveat is missing").toMatch(/synthetic extension/i);
  });

  it("maps Unit 3 to the spreadsheet family", () => {
    expect(findUnit(CLS, "spreadsheets-data-analysis")!.families).toEqual([
      "mis200-spreadsheet-formulas",
    ]);
  });

  it("leaves Unit 4 (platform economics) and Unit 5 (levels of IS use) honestly empty", () => {
    expect(findUnit(CLS, "platform-network-economics")!.families).toEqual([]);
    expect(findUnit(CLS, "levels-of-is-use")!.families).toEqual([]);
  });

  it("resolves a title case-insensitively and falls back to the raw key", () => {
    expect(unitTitle(CLS, "spreadsheets-data-analysis")).toBe("Spreadsheets & data analysis");
    expect(unitTitle(CLS, "SPREADSHEETS-DATA-ANALYSIS")).toBe("Spreadsheets & data analysis");
    expect(unitTitle(CLS, "nonsense")).toBe("nonsense");
  });
});
