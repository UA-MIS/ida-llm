/**
 * The comparison grid — every model against every outcome, at a glance.
 *
 * ⚠ ITS OWN PAGE, NOT A TOGGLE ON THE LEADERBOARD, and the reason is that it
 * answers a different question. The leaderboard answers "which model is best",
 * and its filter bar, its catalogue and its ranking all serve that. This answers
 * "which model is best at WHAT" — a question a table sorted by one number cannot
 * show at all. Bolting it on as a view switch would have put two questions under
 * one filter bar, where every control means something different depending on a
 * mode the reader has to remember they set.
 *
 * ⚠ WHAT THE COLOUR MEANS, AND WHAT IT DELIBERATELY DOES NOT. One hue, five
 * steps, stronger for higher — magnitude, never verdict. It is NOT a red-to-green
 * heatmap, because the sheet's own rule says so and is right: these are means
 * over small samples, and a ramp from bad-red to good-green turns a 0.55 into a
 * judgement the evidence does not support. The confidence tell in each cell is
 * what says how much to trust it, and that is a separate axis from how large it is.
 *
 * Colour is also never the only encoding: every cell carries its number, so the
 * grid is readable with no colour perception at all.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { GlossaryPanel, Term } from "@/components/glossary";
import { HowToRead, ReadStep } from "@/components/how-to-read";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { ConfidenceTell } from "@/components/trust-badges";
import { getLeaderboard } from "@/lib/api";
import { formatScore } from "@/lib/format";
import { buildMatrix, bestInColumn, RAMP_STEPS, type MatrixCell, type Matrix } from "@/lib/matrix";
import { COMPARE_TERMS } from "@/lib/glossary";
import { confidenceLabel } from "@/lib/rollup";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Compare models by outcome — Capstone-IDA",
  description:
    "Every model against every published learning outcome, in one grid, with the evidence behind each cell.",
};

/** The ramp legend. Also the only place the step boundaries are stated. */
function Legend() {
  return (
    <div className="cg-legend">
      <span className="cg-legend-label">Score</span>
      <span className="cg-legend-ramp" aria-hidden="true">
        {Array.from({ length: RAMP_STEPS }, (_, i) => (
          <span key={i} className={`cg-swatch cg-step-${i + 1}`} />
        ))}
      </span>
      <span className="muted cg-legend-ends">
        <span>0.0</span>
        <span>1.0</span>
      </span>
      <span className="muted cg-legend-note">
        Stronger colour means a higher score, not a better model — how much to
        trust a number is the confidence pips, which are a separate thing.
      </span>
    </div>
  );
}

function Cell({ cell, modelName, columnHeading }: { cell: MatrixCell; modelName: string; columnHeading: string }) {
  const label = `${modelName} on ${columnHeading}: ${cell.reason}`;

  if (cell.status === "measured") {
    return (
      <td className={`cg-cell cg-measured cg-step-${cell.step}`} title={label}>
        {cell.runId ? (
          <Link href={`/runs/${encodeURIComponent(cell.runId)}`} className="cg-score">
            {formatScore(cell.score)}
          </Link>
        ) : (
          <span className="cg-score">{formatScore(cell.score)}</span>
        )}
        <span className="cg-sub">
          {cell.measuredTasks}/{cell.tasksAvailable}
        </span>
        <span className="sr-only">{label}</span>
      </td>
    );
  }

  /* ⚠ AN EMPTY CELL IS STILL A STATEMENT, so it is drawn as one. A blank square
     in a grid reads as zero to almost everyone; a dash with a reason behind it
     does not. The two empty kinds get different glyphs because they are
     different claims — see lib/matrix.ts. */
  const notBenchmarkable = cell.status === "not_benchmarkable";
  return (
    <td
      className={`cg-cell ${notBenchmarkable ? "cg-out-of-scope" : "cg-unmeasured"}`}
      title={label}
    >
      <span aria-hidden="true">{notBenchmarkable ? "◇" : "–"}</span>
      <span className="sr-only">{label}</span>
    </td>
  );
}

function Grid({ matrix }: { matrix: Matrix }) {
  const rows = [...matrix.ranked, ...matrix.unranked];

  return (
    <div className="table-scroll">
      <table className="cg-grid">
        <thead>
          <tr>
            <th scope="col" className="cg-corner">
              Model
            </th>
            {matrix.columns.map((column) => (
              <th
                key={column.id}
                scope="col"
                className={column.benchmarkable ? undefined : "cg-col-out"}
                title={column.note}
              >
                <span className="cg-col-id">{column.id}</span>
                <span className="cg-col-title">{column.title}</span>
                {!column.benchmarkable ? (
                  <span className="cg-col-flag">not text-measurable</span>
                ) : null}
              </th>
            ))}
            <th scope="col" className="cg-col-overall">
              Overall
            </th>
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr key={row.model.model_key} className={row.model.recommendable ? undefined : "row-muted"}>
              <th scope="row" className="cg-model">
                <Link href={`/models/${encodeURIComponent(row.model.model_key)}`}>
                  {row.model.display_name}
                </Link>
                <span className="cg-model-sub muted">
                  {row.measuredCount} of {matrix.benchmarkableCount} measurable outcomes
                  {!row.model.recommendable ? " · test stub" : ""}
                </span>
              </th>
              {row.cells.map((cell, index) => (
                <Cell
                  key={cell.slo}
                  cell={cell}
                  modelName={row.model.display_name}
                  columnHeading={matrix.columns[index]!.heading}
                />
              ))}
              <td className="cg-cell cg-overall">
                {row.model.overall.score === null ? (
                  <span className="muted">–</span>
                ) : (
                  <>
                    <span className="cg-score">{formatScore(row.model.overall.score)}</span>
                    <ConfidenceTell
                      confidence={row.model.overall.confidence}
                      label={confidenceLabel(row.model.overall.confidence)}
                      reason={`The weakest confidence among this model's ${row.model.overall.measured_tasks} measurements.`}
                    />
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>

        {/* Reading a column is the point of the grid, so the strongest model in
            each one is named rather than left to the reader's eye. A column with
            nothing measured says so instead of naming a winner by default. */}
        <tfoot>
          <tr>
            <th scope="row" className="cg-model cg-foot-label">
              Strongest measured
            </th>
            {matrix.columns.map((column, index) => {
              const best = bestInColumn(matrix, index);
              return (
                <td key={column.id} className="cg-cell cg-foot">
                  {best ? (
                    <>
                      <span className="cg-foot-name">{best.row.model.display_name}</span>
                      <span className="cg-sub">{formatScore(best.cell.score)}</span>
                    </>
                  ) : (
                    <span className="muted">–</span>
                  )}
                </td>
              );
            })}
            <td className="cg-cell cg-foot" />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export default async function ComparePage() {
  // ⚠ THE MORE VISIBLE CASE OF THE TWO. This page is in the nav, so it is one
  // click from the front door for a reader who has just decided to trust this —
  // and an unguarded fetch here turns a routine API blip into a stack trace
  // shown to exactly that person. See `components/service-unavailable.tsx`.
  //
  // ⚠ NOT THE SAME AS THE `!matrix.available` BRANCH BELOW, AND THE TWO MUST
  // NOT CONVERGE. That one says "there are no outcomes to compare", which is a
  // true statement about the benchmark. This one says "we cannot see the
  // benchmark", which is a statement about us. Rendering the fault as the
  // finding would quietly tell a professor the grid is emptier than it is.
  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable
        what="the comparison grid"
        retryHref="/compare"
        cause={cause}
      />
    );
  }

  const matrix = buildMatrix(board);

  if (!matrix.available) {
    return (
      <div className="empty">
        <h2>No outcomes to compare</h2>
        <p className="muted">{matrix.unavailableReason}</p>
        <p className="muted">
          The <Link href="/leaderboard">leaderboard</Link> still works — it groups
          by task rather than by outcome.
        </p>
      </div>
    );
  }

  const measuredCells = matrix.ranked.reduce(
    (n, row) => n + row.cells.filter((cell) => cell.status === "measured").length,
    0,
  );
  const possibleCells = matrix.ranked.length * matrix.benchmarkableCount;

  return (
    <>
      <section className="hero">
        <p className="subtitle">
          Every model against every outcome your programme publishes. Read a row
          for one model&rsquo;s profile, a column to see who is strongest at one
          thing.
        </p>
      </section>

      {/* ⚠ ORIENTATION BEFORE A GRID, NOT AFTER IT. A matrix is the densest
          thing on this site and it is now one click from the front door. A
          reader who does not know which axis is which, or that a blank cell is
          not a nought, cannot get anything out of it — and a grid of mostly
          empty squares read as zeros is actively worse than no page at all. */}
      <HowToRead title="A grid of models against your outcomes. Here is how to read it.">
        <ReadStep n={1} heading="Rows are models, columns are your outcomes">
          Read across a row for one <Term id="model">model</Term>&rsquo;s
          profile — what it is good and bad at. Read down a column to see which
          model is strongest at one particular{" "}
          <Term id="learning-outcome">learning outcome</Term>.
        </ReadStep>
        <ReadStep n={2} heading="Stronger colour means a higher score, not a better model">
          There is no red-to-green scale here on purpose. Colour says how large a{" "}
          <Term id="score">score</Term> is; the dots beside it say how much to
          trust it, which is a separate question.
        </ReadStep>
        <ReadStep n={3} heading="An empty cell is never a zero">
          A dash means <Term id="not-measured">nothing has been run</Term> for
          that pairing yet. A diamond means the outcome{" "}
          <Term id="not-benchmarkable">cannot be measured this way</Term> at all
          — we show it rather than quietly dropping it.
        </ReadStep>
        <ReadStep n={4} heading="Every score opens">
          Click any number to see the full record behind it. If a cell looks
          wrong to you, that is where to check.
        </ReadStep>
      </HowToRead>

      <GlossaryPanel terms={COMPARE_TERMS} />

      <section className="panel panel-lead">
        <div className="panel-head">
          <h2>Models × outcomes</h2>
          <p className="muted panel-note">
            {/* Coverage stated up front, because a grid of mostly-empty cells
                should be introduced honestly rather than discovered. */}
            {measuredCells} of {possibleCells} measurable pairings have a score so
            far. Empty cells are <strong>not zeros</strong> — a dash means nothing
            has run yet, and a diamond means the curriculum says a text benchmark
            cannot measure that outcome at all.
          </p>
        </div>

        <Legend />
        <Grid matrix={matrix} />

        <p className="muted results-meta">
          Each score links to the run behind it.{" "}
          {matrix.unfiledTaskCount > 0 ? (
            <>
              {matrix.unfiledTaskCount} task
              {matrix.unfiledTaskCount === 1 ? " is" : "s are"} not filed under any
              outcome and so cannot appear in this grid; they are on the{" "}
              <Link href="/leaderboard">leaderboard</Link>.{" "}
            </>
          ) : null}
          Looking for one model in depth? Its report card is one click from its
          name.
        </p>
      </section>
    </>
  );
}
