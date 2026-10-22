/**
 * Collapse model versions into family rows, from registry data.
 *
 * ⚠ NEVER AN AVERAGE. A family is not a model: averaging Opus 4.5 and Opus 5.5
 * would invent a score nothing was ever measured at. A family cell is either the
 * one value every measured member shares, or the honest range `min–max%`.
 *
 * ⚠ THE COLOUR IS THE MINIMUM, so a family never looks better than its weakest
 * version. Members with no result are left out of the range; a family none of
 * whose members has a result shows the ordinary empty cell.
 *
 * ⚠ BOTH ENDS OF THE RANGE GO THROUGH `formatScoreValue`, so a 99.58% member
 * prints as 99%, never 100%. Membership is the registry's `family` field, never
 * a string match on a name.
 */

import { formatScoreValue } from "./format";
import { rampStep, type MatrixCell } from "./matrix";
import type { MatrixModelRow } from "./explore-matrix";

export interface FamilyRow {
  kind: "family";
  /** The registry `family` key. */
  key: string;
  /** "Claude Opus · 6 versions". */
  label: string;
  /** Newest first (registry `display_order`). */
  members: MatrixModelRow[];
  cells: FamilyCell[];
  overall: FamilyCell;
  /** Any member's numbers here were seeded rather than measured. */
  seeded: boolean;
}

export interface SingleRow {
  kind: "single";
  row: MatrixModelRow;
}

export type DisplayRow = FamilyRow | SingleRow;

/** "96–100%", or "100%" when every measured member agrees. */
export function formatScoreRange(low: number, high: number): string {
  const lo = formatScoreValue(low);
  const hi = formatScoreValue(high);
  if (lo === hi) return hi;
  return `${lo.slice(0, -1)}–${hi}`;
}

/** The text a family cell prints, or null when it should be an empty cell. */
export function familyCellText(cells: MatrixCell[]): string | null {
  const scores = cells
    .filter((c) => c.status === "measured" && c.score !== null)
    .map((c) => c.score as number);
  if (scores.length === 0) return null;
  return formatScoreRange(Math.min(...scores), Math.max(...scores));
}

export interface FamilyCell {
  cell: MatrixCell;
  /** Overrides the cell's printed score; absent for an empty cell. */
  text?: string;
}

export function collapseCells(cells: MatrixCell[], familyLabel: string): FamilyCell {
  const measured = cells.filter((c) => c.status === "measured" && c.score !== null);
  if (measured.length === 0) {
    // Every member empty: the same verdict for each (benchmarkability is a
    // property of the column), so the first one is the family's.
    return { cell: cells[0]! };
  }
  const lowest = measured.reduce((a, b) => ((b.score as number) < (a.score as number) ? b : a));
  const text = familyCellText(cells)!;
  const scores = measured.map((c) => c.score as number);
  const same = text === formatScoreValue(Math.max(...scores));
  return {
    text,
    cell: {
      ...lowest,
      step: rampStep(lowest.score as number),
      // No single run is "the" run of a family.
      runId: null,
      reason:
        `${familyLabel}: ${same ? text : `${text} across the ${measured.length} measured versions`}` +
        `${same ? "" : "; the colour follows the lowest"}. Open the row to see each version.`,
    },
  };
}

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
    const name = row.family_display_name ?? row.family;
    const label = `${name} · ${members.length} versions`;
    out.push({
      kind: "family",
      key: row.family,
      label,
      members,
      cells: row.cells.map((_, i) =>
        collapseCells(
          members.map((m) => m.cells[i]!),
          name,
        ),
      ),
      overall: collapseCells(
        members.map((m) => m.overallCell),
        name,
      ),
      seeded: members.some((m) => m.seeded),
    });
  }
  return out;
}
