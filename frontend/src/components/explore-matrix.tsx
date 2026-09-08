/**
 * One level of the drill-down, drawn as the comparison matrix.
 *
 * ⚠ THE SAME GRID AS `/compare`, TRANSPOSED — not a lookalike. The cells, the
 * heat ramp, the confidence pips and the two empty glyphs come from
 * `components/score-grid.tsx`, which `/compare` renders too, and the cells
 * themselves are classified by `classifyCell` in lib/matrix.ts, which
 * `/compare` also uses. Nothing here re-implements a rule; if the two pages
 * ever disagree about what a square means it will be because somebody changed
 * the shared function, which is the point.
 *
 * ⚠ THE ROW HEADER IS THE DRILL, AND IT IS THE ONLY DRILL. A reader on this
 * page arrived to open something — a programme, a course, an outcome — so the
 * thing you open is the row, and every row header is a link with a visible
 * affordance. Individual cells link to their RUN instead (the receipt), which
 * is the same behaviour they have on `/compare`; a cell that drilled sideways
 * into a different level would make the two grids mean different things.
 *
 * ⚠ THE TRAILING COLUMN IS THE HEADLINE, IN THE SAME ROW AS ITS EVIDENCE. The
 * old tile grid put a course's overall number on a card and its per-model
 * detail on another page, where the two could drift without anybody noticing.
 * Here "All models" is the last cell of the row it summarises, built by the
 * same function over the union of the same entries — so a headline that
 * disagreed with the cells beside it would have to disagree with itself.
 */

import Link from "next/link";

import { RampLegend, ScoreCell } from "@/components/score-grid";
import { DemonstrationBadge } from "@/components/trust-badges";
import { NOT_MEASURED, NOT_TEXT_MEASURABLE } from "@/lib/explore";
import type { ExploreMatrix, MatrixEntityRow } from "@/lib/explore-matrix";

/** The label the trailing column carries, in the header and in every cell's voice. */
const ALL_MODELS = "All models";

function RowHeader({ row, badge }: { row: MatrixEntityRow; badge?: React.ReactNode }) {
  return (
    <th scope="row" className={`cg-model xp-row xp-row-${row.status}`}>
      <Link href={row.href} className="xp-row-link">
        <span className="xp-row-eyebrow">{row.eyebrow}</span>
        <span className="xp-row-heading">{row.heading}</span>
        <span className="xp-row-go" aria-hidden="true">
          →
        </span>
      </Link>

      {/* ⚠ THE REASON IS NOT A TOOLTIP. A row with no number still says
          something, and in a dense grid the sentence that says WHY is the
          difference between "not measured yet" and a reader's assumption of
          zero. It is on the page, at every width. */}
      <span className="cg-model-sub muted xp-row-reason">{row.reason}</span>
      <span className="cg-model-sub muted xp-row-foot">{row.footnote}</span>

      {(badge ?? row.seeded) ? (
        <span className="cg-model-sub xp-row-badges">
          {badge}
          {/* Per row, so it self-clears the moment a real measurement replaces
              the seeded one for THIS row — see `entriesAreSeeded`. */}
          {row.seeded ? <DemonstrationBadge /> : null}
        </span>
      ) : null}
    </th>
  );
}

export function ExploreMatrixGrid({
  matrix,
  /** What one row IS, for the column header — "Programme", "Course", "Outcome". */
  rowKind,
  /** Optional extra badge per row, keyed by `row.key` — level labels on level 3. */
  badgeFor,
}: {
  matrix: ExploreMatrix;
  rowKind: string;
  badgeFor?: (row: MatrixEntityRow) => React.ReactNode;
}) {
  return (
    <>
      <RampLegend />

      <div className="table-scroll">
        <table className="cg-grid xp-matrix">
          <thead>
            <tr>
              <th scope="col" className="cg-corner">
                {rowKind}
              </th>
              {matrix.columns.map((column) => (
                <th
                  key={column.model_key}
                  scope="col"
                  className={column.recommendable ? undefined : "cg-col-out"}
                  title={
                    column.recommendable
                      ? undefined
                      : "A deterministic test stub. Shown because it is a real row, never ranked."
                  }
                >
                  <span className="cg-col-id">
                    <Link href={`/models/${encodeURIComponent(column.model_key)}`}>
                      {column.display_name}
                    </Link>
                  </span>
                  {/* ⚠ THE DISCLOSURE SITS ON THE AXIS IT QUALIFIES. A seeded
                      model's whole COLUMN is illustrative here, the way a
                      seeded model's whole ROW is on `/compare` — same flag,
                      same words, drawn where the reader meets the numbers. */}
                  {column.seeded ? (
                    <span className="cg-col-flag xp-col-demo">
                      <DemonstrationBadge />
                    </span>
                  ) : null}
                  {!column.recommendable ? (
                    <span className="cg-col-flag">test stub</span>
                  ) : null}
                </th>
              ))}
              <th scope="col" className="cg-col-overall">
                {ALL_MODELS}
              </th>
            </tr>
          </thead>

          <tbody>
            {matrix.rows.map((row) => (
              <tr key={row.key} className={row.benchmarkable ? undefined : "row-muted"}>
                <RowHeader row={row} badge={badgeFor?.(row)} />
                {row.cells.map((cell, index) => (
                  <ScoreCell
                    key={cell.slo}
                    cell={cell}
                    rowLabel={row.heading}
                    columnLabel={matrix.columns[index]!.display_name}
                  />
                ))}
                {/* The headline, as a cell, in the row it summarises. */}
                <ScoreCell
                  cell={row.overallCell}
                  rowLabel={row.heading}
                  columnLabel={ALL_MODELS}
                />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ⚠ THE KEY IS ON THE PAGE, NOT ONLY IN A TOOLTIP. Two glyphs carry two
          different claims, and a reader who cannot hover — or who simply does
          not — must still be able to tell them apart. One line, under the grid
          it explains, in the same words `lib/explore.ts` uses everywhere else. */}
      <p className="muted xp-matrix-key">
        <span className="xp-key-mark" aria-hidden="true">
          –
        </span>{" "}
        {NOT_MEASURED} — nothing has been run for that pairing, which is not a
        zero.{" "}
        <span className="xp-key-mark" aria-hidden="true">
          ◇
        </span>{" "}
        {NOT_TEXT_MEASURABLE} — the curriculum says a text benchmark cannot reach
        it, so nothing was run on purpose. Every score links to the run behind it.
      </p>
    </>
  );
}
