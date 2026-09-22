/**
 * The grid primitives every matrix on this site is drawn from.
 *
 * ⚠ EXTRACTED, NOT REWRITTEN. These three pieces — the ramp legend, the cell,
 * and the ramp itself — were written inline in `/compare` and were the reason
 * that page could be trusted: one hue for magnitude, a confidence tell beside
 * every number, and two visibly different glyphs for the two kinds of empty.
 * `/explore`'s three grid levels now render the SAME components rather than a
 * second implementation that agrees with this one until somebody edits one of
 * them. The alternative was four grids that look alike and drift apart, which
 * is exactly how `/explore/[major]/[course]` came to be the one page missing a
 * disclosure the other three had.
 *
 * ⚠ WHAT THE COLOUR MEANS, AND WHAT IT DELIBERATELY DOES NOT. One hue, five
 * steps, stronger for higher — magnitude, never verdict. It is NOT a
 * red-to-green heatmap: these are means over small samples, and a ramp from
 * bad-red to good-green turns a 0.55 into a judgement the evidence does not
 * support. The confidence tell in each cell is what says how much to trust it,
 * and that is a separate axis from how large it is.
 *
 * ⚠ COLOUR IS NEVER THE ONLY ENCODING. Every cell carries its number, so the
 * grid is fully readable with no colour perception at all.
 */

import Link from "next/link";

import { ConfidenceTell } from "@/components/trust-badges";
import { formatScore, formatScore100 } from "@/lib/format";
import { RAMP_STEPS, type MatrixCell } from "@/lib/matrix";
import { confidenceLabel } from "@/lib/rollup";

/** The ramp legend. Also the only place the step boundaries are stated. */
type ScoreScale = 1 | 100;

export function RampLegend({ scale = 1 }: { scale?: ScoreScale } = {}) {
  return (
    <div className="cg-legend">
      <span className="cg-legend-label">Score</span>
      <span className="cg-legend-ramp" aria-hidden="true">
        {Array.from({ length: RAMP_STEPS }, (_, i) => (
          <span key={i} className={`cg-swatch cg-step-${i + 1}`} />
        ))}
      </span>
      <span className="muted cg-legend-ends">
        <span>{scale === 100 ? "0" : "0.0"}</span>
        <span>{scale === 100 ? "100" : "1.0"}</span>
      </span>
      <span className="muted cg-legend-note">
        Stronger colour means a higher score, not a better model — how much to
        trust a number is the confidence pips, which are a separate thing.
      </span>
    </div>
  );
}

/**
 * One cell of any score matrix.
 *
 * `rowLabel` and `columnLabel` are what the cell is a crossing OF, in the
 * reader's words, and they are what the screen-reader sentence and the tooltip
 * are built from. `/compare` crosses a model with an outcome; `/explore`
 * crosses a course with a model. The cell does not care which way round it is —
 * it only has to say, out loud, which two things it is about.
 */
export function ScoreCell({
  cell,
  rowLabel,
  columnLabel,
  href,
  scale = 1,
  compact = false,
}: {
  cell: MatrixCell;
  rowLabel: string;
  columnLabel: string;
  /**
   * Where the score links, when it should not link to its run.
   *
   * ⚠ AN OVERRIDE, AND THE DEFAULT IS STILL THE RECEIPT. `/compare` is a
   * terminal grid — there is no level below it — so a cell there links to the
   * run that produced the number, which is the most useful thing a cell can
   * do when nothing is deeper. `/explore` is a drill-down, and a cell is the
   * crossing of a model and a thing you can open; its link carries both halves
   * one level down, and the run stays reachable from the evidence page at the
   * bottom. Passing the override rather than branching on a page name is what
   * keeps this one component instead of two that agree until somebody edits
   * one of them.
   */
  href?: string;
  /** Display the score on a 0–1 or 0–100 scale. */
  scale?: ScoreScale;
  /** Use a visible confidence word in dense grids, without confidence pips. */
  compact?: boolean;
}) {
  const label = `${rowLabel} on ${columnLabel}: ${cell.reason}`;
  const target = href ?? (cell.runId ? `/runs/${encodeURIComponent(cell.runId)}` : null);
  const scoreText =
    cell.score === null
      ? "—"
      : scale === 100
        ? formatScore100(cell.score)
        : formatScore(cell.score);
  const scoreAccessible = scale === 100 && cell.score !== null ? `${scoreText} out of 100` : scoreText;
  const confidence = confidenceLabel(cell.confidence);
  const coverage = `${cell.measuredTasks} of ${cell.tasksAvailable} tasks measured`;
  const measuredAccessible = `${label} Score: ${scoreAccessible}. Confidence: ${confidence}. ${coverage}.`;

  if (cell.status === "measured") {
    return (
      <td className={`cg-cell cg-measured cg-step-${cell.step}`} title={label}>
        {target ? (
          <Link href={target} className="cg-score">
            {scoreText}
            {scale === 100 && <span className="sr-only"> out of 100</span>}
          </Link>
        ) : (
          <span className="cg-score">
            {scoreText}
            {scale === 100 && cell.score !== null && <span className="sr-only"> out of 100</span>}
          </span>
        )}
        {!compact && <span className="cg-sub">{cell.measuredTasks}/{cell.tasksAvailable}</span>}
        {/* ⚠ THE PIPS THE PAGE TELLS YOU TO LOOK FOR. Three separate pieces of
            copy — the legend, the how-to-read panel, and the stylesheet's own
            comment — point the reader at a confidence tell beside each number,
            and the cell once drew the score and nothing else. A reader who
            follows the instructions and finds nothing concludes they have
            misread the page, which is the one thing a grid cannot afford.
            Compact here (`cg-confidence` drops the word, keeps the pips)
            because the grid is dense and the label would wrap every cell — the
            full wording stays in the title and the sr-only sentence. */}
        <span className="cg-confidence">
          {compact ? (
            <span className="cg-confidence-compact-label">{confidence}</span>
          ) : (
            <ConfidenceTell
              confidence={cell.confidence}
              label={confidence}
              reason={`${confidence}. How much weight this number can bear — how it was marked, over how many attempts, and whether anything failed. It is about the measurement, not about the model.`}
            />
          )}
        </span>
        <span className="sr-only">{measuredAccessible}</span>
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
