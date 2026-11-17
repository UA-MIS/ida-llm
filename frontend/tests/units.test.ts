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
import type { UnitView } from "@/lib/types";

import DEMO_SNAPSHOT from "./fixtures/units-taxonomy-demo.snapshot.json";
import SNAPSHOT from "./fixtures/units-taxonomy.snapshot.json";

/**
 * ⚠ THE TAXONOMY IS SERVED NOW, NOT HARDCODED (admin-console design §4.5).
 * These tests used to read the `TAXONOMY` constant in `lib/units.ts`. They now
 * read the frozen snapshot of that constant (`tests/fixtures/*.snapshot.json`,
 * written before it was deleted; the backend's `test_units.py` pins
 * `curriculum/units.yaml` to the same snapshot), shaped exactly as
 * `CurriculumView.units` serves it: absent `source`/`caveat` become `null`.
 * Every assertion below is the one that held against the old constant.
 */
type Snapshot = Record<string, Array<Omit<UnitView, "source" | "caveat"> & { source?: string; caveat?: string }>>;
const served = (snap: Snapshot): Record<string, UnitView[]> =>
  Object.fromEntries(Object.entries(snap).map(([course, units]) => [course, units.map((u) => ({ ...u, source: u.source ?? null, caveat: u.caveat ?? null }))]));
const TAX = { units: served(SNAPSHOT as Snapshot) };
/** What dev serves (`units.dev.yaml`): the real classes plus the demo ones. */
const DEV_TAX = { units: served(DEMO_SNAPSHOT as Snapshot) };

/** The families authored for MIS 200, per `tasks/mis200-*` and `majors.yaml`. */
const MIS200_FAMILIES = [
  "mis200-spreadsheet-formulas",
  "mis200-is-concepts",
  "mis200-competitive-strategy",
  "mis200-platform-network",
  "mis200-levels-of-is-use",
  "mis200-is-problem-solving",
];

/**
 * The five families that map to a UNIT — the exam's content areas. The SLO1
 * extension (`mis200-is-problem-solving`) is a MIS 200 family but deliberately
 * NOT one of these: it lives on the outcome axis, not the content axis. See the
 * header of `@/lib/units` and `tasks/mis200-exam1-mapping.md` §6.
 */
const MIS200_UNIT_FAMILIES = [
  "mis200-spreadsheet-formulas",
  "mis200-is-concepts",
  "mis200-competitive-strategy",
  "mis200-platform-network",
  "mis200-levels-of-is-use",
];

describe("every class's unit taxonomy", () => {
  for (const course of coursesWithUnits(TAX)) {
    describe(course, () => {
      const units = unitsFor(TAX, course);

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
    expect(hasUnits(TAX, CLS)).toBe(true);
    expect(hasUnits(TAX, "MIS 221")).toBe(false);
  });

  it("breaks into five units in course order", () => {
    expect(unitsFor(TAX, CLS).map((u) => u.title)).toEqual([
      "Information systems & business models",
      "Competitive strategy with IS",
      "Spreadsheets & data analysis",
      "Platform & network economics",
      "Levels of IS use in organizations",
    ]);
  });

  it("references only families that were actually authored for the course", () => {
    for (const u of unitsFor(TAX, CLS)) {
      for (const family of u.families) {
        expect(MIS200_FAMILIES, `${u.key} references an unknown family ${family}`).toContain(family);
      }
    }
  });

  it("claims every exam-content family in exactly one unit", () => {
    const covered = unitsFor(TAX, CLS).flatMap((u) => u.families);
    for (const family of MIS200_UNIT_FAMILIES) {
      expect(covered, `no unit claims ${family}`).toContain(family);
    }
  });

  it("leaves the synthetic SLO1 extension OFF the unit axis, on purpose", () => {
    // `mis200-is-problem-solving` is a MIS 200 family (it keeps the SLO1 outcome
    // view non-empty) but is not one of Exam 1's content areas, so no unit
    // claims it — a class family may live in at most one unit, not necessarily
    // in one. See the header of `@/lib/units` and the mapping doc §6.
    const covered = unitsFor(TAX, CLS).flatMap((u) => u.families);
    expect(covered, "the SLO1 extension must not be a unit").not.toContain(
      "mis200-is-problem-solving",
    );
  });

  it("maps Unit 1 to the IS-concepts breadth family", () => {
    expect(findUnit(TAX, CLS, "information-systems-business-models")!.families).toEqual([
      "mis200-is-concepts",
    ]);
  });

  it("maps Unit 2 to the competitive-strategy family, scorable and with no caveat", () => {
    const unit = findUnit(TAX, CLS, "competitive-strategy-with-is")!;
    expect(unit.n).toBe(2);
    expect(unit.families).toEqual(["mis200-competitive-strategy"]);
    // The competitive-strategy family is an honest adaptation of the exam's own
    // competitive-strategy section, so — unlike the SLO1 extension it replaces —
    // it needs no synthetic-extension caveat.
    expect(unit.caveat).toBeNull();
    expect(unit.source, "a scorable unit names its source").toBeTruthy();
  });

  it("maps Unit 3 to the spreadsheet family", () => {
    expect(findUnit(TAX, CLS, "spreadsheets-data-analysis")!.families).toEqual([
      "mis200-spreadsheet-formulas",
    ]);
  });

  it("maps Unit 4 to platform economics and Unit 5 to levels of IS use", () => {
    expect(findUnit(TAX, CLS, "platform-network-economics")!.families).toEqual([
      "mis200-platform-network",
    ]);
    expect(findUnit(TAX, CLS, "levels-of-is-use")!.families).toEqual([
      "mis200-levels-of-is-use",
    ]);
  });

  it("resolves a title case-insensitively and falls back to the raw key", () => {
    expect(unitTitle(TAX, CLS, "spreadsheets-data-analysis")).toBe("Spreadsheets & data analysis");
    expect(unitTitle(TAX, CLS, "SPREADSHEETS-DATA-ANALYSIS")).toBe("Spreadsheets & data analysis");
    expect(unitTitle(TAX, CLS, "nonsense")).toBe("nonsense");
  });
});

describe("OM 300 specifically", () => {
  const CLS = "OM 300";

  it("is a class with a taxonomy of four units, one per exam, in course order", () => {
    expect(hasUnits(TAX, CLS)).toBe(true);
    expect(unitsFor(TAX, CLS).map((u) => u.title)).toEqual([
      "Strategy, productivity & forecasting",
      "Project management & quality control",
      "Inventory & lean operations",
      "Cumulative final",
    ]);
  });

  it("maps each unit to exactly its own exam's family", () => {
    expect(unitsFor(TAX, CLS).map((u) => u.families)).toEqual([
      ["om300-exam1-ops-forecasting"],
      ["om300-exam2-project-quality-spc"],
      ["om300-exam3-inventory-eoq-lean"],
      ["om300-exam4-ops-analytics"],
    ]);
  });

  it("titles Unit 4 as the cumulative final, with no synthetic-extension caveat", () => {
    const unit = findUnit(TAX, CLS, "cumulative-final")!;
    expect(unit.n).toBe(4);
    expect(unit.caveat).toBeNull();
  });

  it("shares no family with MIS 200", () => {
    const mine = new Set(unitsFor(TAX, CLS).flatMap((u) => u.families));
    for (const family of unitsFor(TAX, "MIS 200").flatMap((u) => u.families)) {
      expect(mine.has(family)).toBe(false);
    }
  });
});

describe("the served taxonomy", () => {
  it("treats a response with no units, or a class with no key, as having no units yet", () => {
    expect(unitsFor(undefined, "MIS 200")).toEqual([]);
    expect(unitsFor({} as { units: Record<string, UnitView[]> }, "MIS 200")).toEqual([]);
    expect(hasUnits(TAX, "MIS 221")).toBe(false);
    expect(unitTitle(null, "MIS 200", "intro")).toBe("intro");
    expect(coursesWithUnits(undefined)).toEqual([]);
  });

  it("dev's set adds demo classes but serves MIS 200 and OM 300 exactly as the real set does", () => {
    expect(unitsFor(DEV_TAX, "MIS 200")).toEqual(unitsFor(TAX, "MIS 200"));
    expect(unitsFor(DEV_TAX, "OM 300")).toEqual(unitsFor(TAX, "OM 300"));
    expect(coursesWithUnits(DEV_TAX).length).toBeGreaterThan(coursesWithUnits(TAX).length);
  });

  it("keeps the partition across the dev set too: one family, one unit", () => {
    const owner = new Map<string, string>();
    for (const course of coursesWithUnits(DEV_TAX)) {
      for (const u of unitsFor(DEV_TAX, course)) {
        for (const f of u.families) {
          expect(owner.get(f), `${f} is in two units`).toBeUndefined();
          owner.set(f, `${course}/${u.key}`);
        }
      }
    }
  });
});
