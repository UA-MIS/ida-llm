/**
 * One level of the drill-down, drawn as the comparison matrix.
 *
 * ⚠ MODELS DOWN THE LEFT, ENTITIES ACROSS THE TOP — the same orientation as
 * `/compare`, and the flip is an argument rather than a layout. A vertical list
 * reads as a ranking whether or not one was meant, so the axis running down the
 * page must be the axis where order means something. Model order does: these
 * rows are sorted and the best model is at the top because it is best. Entity
 * order does not: majors are the catalog's eleven, classes are a course
 * listing, and standing them in a column would quietly claim that Accounting
 * outranks Marketing or that MIS 200 matters more than MIS 466.
 *
 * ⚠ THE SAME GRID AS `/compare` — not a lookalike. The cells, the heat ramp,
 * the confidence pips and the two empty glyphs come from
 * `components/score-grid.tsx`, which `/compare` renders too, and the cells are
 * classified by `classifyCell` in lib/matrix.ts, which `/compare` also uses.
 * Nothing here re-implements a rule; if the two pages ever disagree about what
 * a square means it will be because somebody changed the shared function, which
 * is the point.
 *
 * ⚠ THREE CLICK TARGETS, AND EVERY ONE OF THEM ANSWERS A DIFFERENT QUESTION.
 * A dense grid where only one thing is clickable teaches a reader to stop
 * looking, and the previous cut had exactly that problem — the row header
 * drilled and nothing else did.
 *
 *   a column header   the entity, across every model. The drill.
 *   a row header      the model, across everything. Its report card.
 *   a score cell      the crossing. Drills into the entity carrying the model,
 *                     so the next level opens focused on the number you clicked
 *                     instead of dropping you back into the full field.
 *
 * ⚠ THE PER-ENTITY REASON IS A SCREEN-READER LINE, NOT A VISIBLE LIST ANYMORE.
 * When entities were rows, a row header was seventeen rems wide and could carry
 * its own sentence. A column header cannot: it is a few characters across, and
 * the honest reasons this flow depends on ("nothing has been run for that
 * pairing, which is not a zero") do not fit visibly there. There used to be a
 * list of those sentences beneath the grid, but for a sighted reader it only
 * restated the cells above it and the key line below it — redundant clutter,
 * almost all of it empty-column filler — so it was removed. The reason still
 * rides each column as an `sr-only` span inside its header (see `ColumnHeader`),
 * so assistive tech still hears it, and the single key line under the grid still
 * explains the "–"/"◇" glyphs for everyone.
 */

import Link from "next/link";

import { RampLegend, ScoreCell } from "@/components/score-grid";
import { DemonstrationBadge } from "@/components/trust-badges";
import { NOT_MEASURED, NOT_TEXT_MEASURABLE } from "@/lib/explore";
import { cellHref, type ExploreMatrix, type MatrixEntityColumn } from "@/lib/explore-matrix";

/** The label the trailing summary row carries, in the header and in its cells. */
const ALL_MODELS = "All models";

function ColumnHeader({
  entity,
  badge,
}: {
  entity: MatrixEntityColumn;
  badge?: React.ReactNode;
}) {
  return (
    <th
      scope="col"
      className={`xp-col xp-col-${entity.status}${entity.benchmarkable ? "" : " cg-col-out"}`}
    >
      <Link
        href={entity.href}
        className="xp-col-link"
        // The full name/title, when the visible label is a shorter code for
        // it — cheap to carry and useful on hover.
        title={entity.columnLabel === entity.heading ? undefined : entity.heading}
      >
        {/* Suppressed when it would just repeat the label — a class column's
            eyebrow IS its code, and "MIS 200 / MIS 200" is a stutter, not a
            hierarchy. */}
        {entity.eyebrow && entity.eyebrow !== entity.columnLabel ? (
          <span className="xp-col-eyebrow">{entity.eyebrow}</span>
        ) : null}
        <span className="xp-col-heading">{entity.columnLabel}</span>
        {/* The full name under the short code — the major's name, the class's
            title, the unit's title. Shown now (the mockup's design), where it was
            once aria-only, because the grid is a handful of columns wide, not
            fourteen, and the name is what a reader scans for. */}
        {entity.heading && entity.heading !== entity.columnLabel ? (
          <span className="xp-col-name">{entity.heading}</span>
        ) : null}
        {/* ⚠ WHAT THIS UNIT COVERS — the class page's whole point. A unit column
            says what its tests are about, measured or not, so an unmeasured unit
            is still a legible part of the course rather than an empty square. */}
        {entity.covers && entity.covers.length > 0 ? (
          <span className="xp-col-covers">{entity.covers.join(" · ")}</span>
        ) : null}
        <span className="xp-col-go" aria-hidden="true">
          →
        </span>
      </Link>
      {(badge ?? entity.seeded) ? (
        <span className="xp-col-badges">
          {badge}
          {/* Per column, so it self-clears the moment a real measurement
              replaces the seeded one for THIS entity — see `entriesAreSeeded`. */}
          {entity.seeded ? <DemonstrationBadge /> : null}
        </span>
      ) : null}
      {/* The honest reason this column does or does not carry a number —
          "nothing has been run for that pairing, which is not a zero". It does
          not fit visibly in a column header, so it rides here for a screen
          reader walking the header row. The single key line under the grid
          carries the glyph legend for sighted readers. */}
      <span className="sr-only">{entity.reason}</span>
    </th>
  );
}

export function ExploreMatrixGrid({
  matrix,
  /** What one column IS, for the corner cell — "Major", "Class", "Outcome". */
  columnKind,
  /** The trailing column's header — "All majors", "All classes", "All outcomes". */
  overallLabel,
  /** Optional extra badge per column, keyed by entity — level labels on level 3. */
  badgeFor,
  /** The model a cell click carried down from the level above, if any. */
  focusModel,
}: {
  matrix: ExploreMatrix;
  columnKind: string;
  overallLabel: string;
  badgeFor?: (entity: MatrixEntityColumn) => React.ReactNode;
  focusModel?: string | null;
}) {
  return (
    <>
      <RampLegend />

      <div className="table-scroll">
        <table className="cg-grid xp-matrix">
          <caption className="sr-only">
            {`Every model against every ${columnKind.toLowerCase()} on this level. `}
            {`Models are rows, strongest first; ${columnKind.toLowerCase()}s are columns, `}
            {"in the order the catalogue publishes them."}
          </caption>
          <thead>
            <tr>
              <th scope="col" className="cg-corner">
                Model
              </th>
              {matrix.entities.map((entity) => (
                <ColumnHeader key={entity.key} entity={entity} badge={badgeFor?.(entity)} />
              ))}
              <th scope="col" className="cg-col-overall">
                {overallLabel}
              </th>
            </tr>
          </thead>

          <tbody>
            {matrix.models.map((model) => (
              <tr
                key={model.model_key}
                className={
                  [
                    model.recommendable ? "" : "row-muted",
                    // ⚠ MARKED, NEVER MOVED. The focused model keeps its place
                    // in the ranking: promoting the row a reader clicked would
                    // make the order say "this is the best model" when all it
                    // means is "this is the one you came from".
                    model.model_key === focusModel ? "xp-model-focused" : "",
                  ]
                    .filter(Boolean)
                    .join(" ") || undefined
                }
              >
                <th scope="row" className="cg-model xp-model">
                  {/* ⚠ THE ROW HEADER IS THE MODEL'S OWN PAGE. It is the third
                      click target and the one a reader reaches for after they
                      have found a model they like: not "how does it do here",
                      which the row already says, but "how does it do
                      everywhere, and what does it cost". */}
                  <Link href={model.href} className="xp-model-link">
                    {model.display_name}
                  </Link>
                  {model.seeded ? (
                    <span className="cg-model-sub">
                      <DemonstrationBadge />
                    </span>
                  ) : null}
                  {!model.recommendable ? (
                    <span
                      className="cg-model-sub muted"
                      title="A deterministic test stub. Shown because it is a real row, never ranked."
                    >
                      test stub
                    </span>
                  ) : null}
                </th>

                {model.cells.map((cell, index) => {
                  const entity = matrix.entities[index]!;
                  return (
                    <ScoreCell
                      key={entity.key}
                      cell={cell}
                      rowLabel={model.display_name}
                      columnLabel={entity.heading}
                      href={cellHref(entity, model.model_key)}
                    />
                  );
                })}

                {/* This model across the whole level — the number its position
                    in the sort is built from, shown so the ranking can be
                    checked rather than taken on trust. */}
                <ScoreCell
                  cell={model.overallCell}
                  rowLabel={model.display_name}
                  columnLabel={overallLabel}
                />
              </tr>
            ))}

            {/* ⚠ THE SUMMARY IS A ROW IN THE SAME TABLE AS ITS EVIDENCE. The
                old tile grid put an entity's overall number on a card and its
                per-model detail on another page, where the two could drift
                without anybody noticing. Here "All models" is the last row of
                the grid it summarises, built by the same function over the
                union of the same entries — so a summary that disagreed with
                the cells above it would have to disagree with itself. */}
            <tr className="xp-summary">
              <th scope="row" className="cg-model xp-model">
                {ALL_MODELS}
              </th>
              {matrix.entities.map((entity) => (
                <ScoreCell
                  key={entity.key}
                  cell={entity.overallCell}
                  rowLabel={ALL_MODELS}
                  columnLabel={entity.heading}
                  href={entity.href}
                />
              ))}
              <td className="cg-cell cg-unmeasured" aria-hidden="true">
                {/* The crossing of "every model" with "every column" is not a
                    number anyone should read: it would average across majors
                    that share nothing. Left deliberately blank rather than
                    filled with an arithmetic mean of unrelated things. */}
              </td>
            </tr>
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
        it, so nothing was run on purpose. A score opens the level below it,
        carrying the model; a column header opens it for every model; a model
        opens its own report card.
      </p>
    </>
  );
}
