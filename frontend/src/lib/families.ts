/**
 * Collapse model versions into family rows, from registry data.
 *
 * ⚠ THE COLLAPSED ROW IS THE FAMILY'S NEWEST MODEL, NOT A SUMMARY OF THE FAMILY.
 * Newest is the member with the lowest registry `display_order`. Every cell of
 * the collapsed row is that one model's own cell, so it can never print a number
 * no model was measured at: no range, no average, no best-of-family per column.
 * If the newest model has no result for a column, that cell is the ordinary
 * empty one; an older version's score is never substituted. Membership is the
 * registry's `family` field, never a string match on a name.
 */

import type { MatrixModelRow } from "./explore-matrix";

export interface FamilyRow {
  kind: "family";
  /** The registry `family` key. */
  key: string;
  /** The family's newest model: the collapsed row. */
  newest: MatrixModelRow;
  /** Every other member, newest first: the rows the expander reveals. */
  earlier: MatrixModelRow[];
}

export interface SingleRow {
  kind: "single";
  row: MatrixModelRow;
}

export type DisplayRow = FamilyRow | SingleRow;

const orderOf = (row: MatrixModelRow) => row.display_order ?? Number.MAX_SAFE_INTEGER;

/**
 * Group `rows` (already in display order) into family rows and single rows.
 * A family sits where its first member sits; a family of one is just that model.
 */
export function groupFamilies(rows: MatrixModelRow[]): DisplayRow[] {
  const byFamily = new Map<string, MatrixModelRow[]>();
  for (const row of rows) {
    if (!row.family) continue;
    byFamily.set(row.family, [...(byFamily.get(row.family) ?? []), row]);
  }
  const out: DisplayRow[] = [];
  const done = new Set<string>();
  for (const row of rows) {
    const members = row.family ? byFamily.get(row.family)! : [];
    if (!row.family || members.length < 2) {
      out.push({ kind: "single", row });
      continue;
    }
    if (done.has(row.family)) continue;
    done.add(row.family);
    // Stable sort, so members without a `display_order` keep their given order.
    const [newest, ...earlier] = [...members].sort((a, b) => orderOf(a) - orderOf(b));
    out.push({ kind: "family", key: row.family, newest: newest!, earlier });
  }
  return out;
}
