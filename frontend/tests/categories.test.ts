/**
 * The per-class content-category taxonomy's invariants.
 *
 * ⚠ THE ONE THAT MATTERS IS THE PARTITION. Results are a (model, task) mean per
 * family. If one family fed two categories, the SAME number would print under
 * both headings — the "one exam's score under a dozen courses" fabrication
 * `lib/explore.ts` exists to prevent, one level down. So every family a class
 * lists lands in exactly one of its categories; this file fails if two
 * categories ever claim the same one.
 *
 * The subset-of-the-class's-own-families invariant (a category cannot surface a
 * family the class does not claim) is enforced at runtime by `buildCategoryMatrix`
 * and pinned in `explore-matrix.test.ts`; it is not re-checked here because it is
 * about the join with `majors.yaml`, which this module deliberately does not hold.
 */

import { describe, expect, it } from "vitest";

import {
  categoriesFor,
  categoryTitle,
  coursesWithCategories,
  findCategory,
  hasCategories,
} from "@/lib/categories";

/** The families authored for MIS 200, per `tasks/mis200-*` and `majors.yaml`. */
const MIS200_FAMILIES = [
  "mis200-spreadsheet-formulas",
  "mis200-is-concepts",
  "mis200-is-problem-solving",
];

describe("every class's category taxonomy", () => {
  for (const course of coursesWithCategories()) {
    describe(course, () => {
      const categories = categoriesFor(course);

      it("has at least one category", () => {
        expect(categories.length).toBeGreaterThan(0);
      });

      it("gives every category a unique key, a title and a blurb", () => {
        const keys = categories.map((c) => c.key);
        expect(new Set(keys).size, "duplicate category key").toBe(keys.length);
        for (const c of categories) {
          expect(c.key, "empty key").not.toBe("");
          expect(c.title.length, `empty title on ${c.key}`).toBeGreaterThan(0);
          expect(c.blurb.length, `empty blurb on ${c.key}`).toBeGreaterThan(0);
        }
      });

      it("maps each family to EXACTLY ONE category — a partition, never a duplicate", () => {
        const seen = new Map<string, string>();
        for (const c of categories) {
          for (const family of c.families) {
            const prior = seen.get(family);
            expect(
              prior,
              `family ${family} is claimed by both ${prior} and ${c.key} — that would print one score twice`,
            ).toBeUndefined();
            seen.set(family, c.key);
          }
        }
      });
    });
  }
});

describe("MIS 200 specifically", () => {
  const CAT = "MIS 200";

  it("is a class with a taxonomy", () => {
    expect(hasCategories(CAT)).toBe(true);
    expect(hasCategories("MIS 221")).toBe(false);
  });

  it("references only families that were actually authored for the course", () => {
    for (const c of categoriesFor(CAT)) {
      for (const family of c.families) {
        expect(MIS200_FAMILIES, `${c.key} references an unknown family ${family}`).toContain(family);
      }
    }
  });

  it("covers all three authored families across its categories", () => {
    const covered = categoriesFor(CAT).flatMap((c) => c.families);
    for (const family of MIS200_FAMILIES) {
      expect(covered, `no category claims ${family}`).toContain(family);
    }
  });

  it("files the synthetic SLO1 extension under competitive-strategy, with its caveat", () => {
    const cat = findCategory(CAT, "competitive-strategy")!;
    expect(cat.families).toEqual(["mis200-is-problem-solving"]);
    expect(cat.caveat, "the synthetic-extension caveat is missing").toMatch(/synthetic extension/i);
  });

  it("leaves platform-economics and levels-of-IS-use honestly empty", () => {
    expect(findCategory(CAT, "platform-network-economics")!.families).toEqual([]);
    expect(findCategory(CAT, "levels-of-is-use")!.families).toEqual([]);
  });

  it("resolves a title case-insensitively and falls back to the raw key", () => {
    expect(categoryTitle(CAT, "spreadsheet-excel")).toBe("Spreadsheet & Excel skills");
    expect(categoryTitle(CAT, "SPREADSHEET-EXCEL")).toBe("Spreadsheet & Excel skills");
    expect(categoryTitle(CAT, "nonsense")).toBe("nonsense");
  });
});
