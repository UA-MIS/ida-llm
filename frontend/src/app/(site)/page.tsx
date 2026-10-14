/**
 * The front door — screen 01 of the drill-down, one question answered, nothing
 * to explain.
 *
 * ⚠ IT IS THE BY-MAJOR GRID, AND NOTHING ELSE. The mockup's first screen is a
 * single matrix: every model against every major this college offers. The old
 * landing carried a second "general classes" section below the grid; it is gone,
 * because the core classes are reachable by opening their major and a second list
 * is exactly the "too many doors" the client asked us to remove.
 *
 * ⚠ IT RENDERS THE SAME MATRIX THE DRILL-DOWN DOES. The by-major grid is
 * `buildMajorMatrix` through the shared `ExploreMatrixGrid` — the same cells, the
 * same classifier, the same honest empties as every level below it. The landing
 * invents no number and has no way to; most majors' worth of emptiness is the
 * real shape of what has been measured, not a placeholder.
 *
 * ⚠ THE MEASURED-CLASS COUNT IS A SINGLE TOP-OF-PAGE SUMMARY. The human asked for
 * the "N of M classes measured" tally once, at the top, not repeated on every
 * major — so it lives in the subtitle here and the per-major coverage clutter is
 * gone from the grid.
 */

import type { Metadata } from "next";

import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { DemonstrationNotice } from "@/components/trust-badges";
import { getLeaderboard } from "@/lib/api";
import { buildClasses, buildIndex } from "@/lib/explore";
import { buildMajorMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "AI performance by major — Capstone-IDA",
  description:
    "We measure AI models against the learning outcomes your programme publishes, on real coursework, and report what each is good for in your class. Pick your major to see.",
};

export default async function LandingPage() {
  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return <ResultsUnavailable what="the benchmark" retryHref="/" cause={cause} singular />;
  }

  const index = buildIndex(board);
  const matrix = buildMajorMatrix(board);

  // The single measured-class tally, computed once for the subtitle. "Measured"
  // means a class that has a real score from at least one model — not merely one
  // we have authored tasks about. Honest and specific: today that is one class.
  let totalClasses = 0;
  let measuredClasses = 0;
  if (index.available) {
    for (const major of index.majors) {
      const classes = buildClasses(board, major);
      totalClasses += classes.length;
      measuredClasses += classes.filter((klass) => klass.status === "measured").length;
    }
  }

  return (
    <>
      <section className="hero">
        <p className="xp-kicker">01 · Majors</p>
        <h2 className="xp-title">AI performance by major</h2>
        <p className="subtitle">
          {matrix.models.length} {matrix.models.length === 1 ? "model" : "models"},{" "}
          {matrix.entities.length} {matrix.entities.length === 1 ? "major" : "majors"}.{" "}
          <strong>
            {measuredClasses} of {totalClasses} {totalClasses === 1 ? "class" : "classes"}
          </strong>{" "}
          measured so far. Open a major to see each class.
        </p>
      </section>

      {/* ⚠ ABOVE THE GRID IT QUALIFIES — a reader forms an impression from the
          first row, so a seeded-data disclosure below the grid is one they have
          already formed an impression without. Same rollup, same words as every
          other level. Silent in the dev preview (see `DemonstrationNotice`). */}
      <DemonstrationNotice when={matrix.demonstration.any} text={matrix.demonstration.notice} />

      {matrix.available ? (
        <ExploreMatrixGrid matrix={matrix} columnKind="Major" overallLabel="Overall" />
      ) : (
        <p className="muted">{matrix.unavailable_reason}</p>
      )}
    </>
  );
}
