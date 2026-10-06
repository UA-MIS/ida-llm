/**
 * The front door — one page, one question answered, nothing to explain.
 *
 * ⚠ THIS USED TO BE AN EDITORIAL ESSAY, AND BEFORE THAT A LEADERBOARD. The
 * essay made the argument in sentences; the leaderboard made it in a table. The
 * client's verdict on both: too much to read, too many doors, and a professor
 * should not have to be told what is on the screen. So the landing is now the
 * thing itself — the by-major grid you drill and the core classes you can jump
 * straight into. No pitch, no "how to read this": a screen that needs
 * explaining has already failed, and the explanation lives on /methodology for
 * anyone who wants it.
 *
 * ⚠ IT RENDERS THE SAME MATRIX THE DRILL-DOWN DOES. The by-major grid is
 * `buildMajorMatrix` through the shared `ExploreMatrixGrid` — the same cells,
 * the same classifier, the same honest empties as every level below it. The
 * landing invents no number and has no way to; two of its majors' worth of
 * emptiness is the real shape of what has been measured, not a placeholder.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { DemonstrationBadge } from "@/components/trust-badges";
import { getLeaderboard } from "@/lib/api";
import { buildCoreClasses, buildIndex } from "@/lib/explore";
import { buildMajorMatrix } from "@/lib/explore-matrix";
import { formatScore } from "@/lib/format";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Which AI helps in your course — Capstone-IDA",
  description:
    "We measure AI models against the learning outcomes your programme publishes, on real coursework, and report what each is good for in your class. Pick your major, or a core class, to see.",
};

/** The one line the by-major grid would need if a reader asked for it. */
const EXPLAIN =
  "One row per model, strongest first; one column per major this college offers. " +
  "Each cell is how that model does across the classes in that major we have " +
  "written tasks about. Open a major to see its classes, or a model to see its " +
  "own report.";

export default async function LandingPage() {
  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return <ResultsUnavailable what="the benchmark" retryHref="/" cause={cause} singular />;
  }

  const index = buildIndex(board);
  const matrix = buildMajorMatrix(board);
  const core = buildCoreClasses(board);

  return (
    <>
      <section className="hero">
        <h2 className="xp-title">Which AI can actually do the work in your course</h2>
        <p className="subtitle">
          We test today&rsquo;s models against the outcomes your programme publishes, on
          real coursework, and report what each is good for — with the evidence behind
          every number. Pick your major, or jump straight to a core class.
        </p>
        <div className="cta-row">
          <Link className="muted" href="/methodology">
            How we test
          </Link>
        </div>
      </section>

      {/* ⚠ ABOVE THE GRID IT QUALIFIES — a reader forms an impression from the
          first row, so a seeded-data disclosure below the grid is one they have
          already formed an impression without. Same rollup, same words as every
          other level. */}
      {matrix.demonstration.any ? (
        <div className="notice">{matrix.demonstration.notice}</div>
      ) : null}

      <section className="panel panel-lead">
        <div className="panel-head">
          <h2>By major</h2>
          <p className="muted panel-note">{EXPLAIN}</p>
        </div>
        {matrix.available ? (
          <ExploreMatrixGrid matrix={matrix} columnKind="Major" overallLabel="All majors" />
        ) : (
          <p className="muted">{matrix.unavailable_reason}</p>
        )}
      </section>

      {core.length > 0 ? (
        <section className="panel">
          <div className="panel-head">
            <h2>General classes</h2>
            <p className="muted panel-note">
              The shared business core every student takes, whatever their major. Open one
              to see what it is made of and how the models do on each part.
            </p>
          </div>
          <ul className="core-grid">
            {core.map(({ major, klass }) => {
              const measured = klass.status === "measured" && klass.aggregate.score !== null;
              return (
                <li key={klass.code}>
                  <Link
                    className={`core-tile core-tile-${klass.status}`}
                    href={`/explore/${major.slug}/${klass.slug}`}
                  >
                    <span className="core-tile-code">{klass.code}</span>
                    <span className="core-tile-title">{klass.title}</span>
                    <span className="core-tile-foot">
                      {measured ? (
                        <>
                          <span className="core-tile-score">{formatScore(klass.aggregate.score)}</span>
                          <span className="muted">
                            {" "}
                            across {klass.measured_count} of {klass.benchmarkable_count} categories
                          </span>
                          {klass.demonstration.any ? (
                            <span className="core-tile-badge">
                              <DemonstrationBadge />
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <span className="muted">Not measured yet</span>
                      )}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          {index.unassigned.length > 0 ? (
            <p className="muted core-unassigned">
              {index.unassigned.map((row) => (
                <span key={row.course}>
                  <strong>{row.course}</strong> is in the core but owned by no major, so it
                  cannot be drilled into from one — {row.reason}
                </span>
              ))}
            </p>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
