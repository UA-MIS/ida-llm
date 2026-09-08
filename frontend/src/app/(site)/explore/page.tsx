/**
 * Level 1 of the guided drill-down: the majors, against every model.
 *
 * ⚠ MAJORS, NOT A PROGRAMME, AND THAT IS THE WHOLE REDIRECT. This level used to
 * be one row — "BScBA General Business (core)", the single programme
 * `curriculum/slo.yaml` describes. It was the wrong first screen for the only
 * reader this product has. Nobody is a professor OF THE CORE. They teach
 * Management Information Systems, and a front door that opens on somebody
 * else's programme asks them to locate themselves before it tells them
 * anything. The eleven majors come from the college's own catalog
 * (`curriculum/majors.yaml`); a visitor finds their own name in the header row
 * and clicks it.
 *
 * ⚠ WHY THIS FLOW EXISTS, AND WHY IT IS NOT A REDESIGN OF `/leaderboard`. The
 * client's verdict on the previous shape was blunt: too much information, too
 * many clicks, and you should not have to explain what is on the screen. The
 * remedy they prescribed is this — one grid per level, drilling from a major to
 * a class to the outcomes behind it to the evidence, so a reader arrives at
 * exactly the thing they care about instead of a wall of everything.
 *
 * ⚠ A GRID MEANS THE MATRIX, NOT A WALL OF CARDS. The first cut of this flow
 * read "grid" as a tiled layout of paragraph cards, one per entity. It is the
 * `/compare` matrix that was asked for: models down one axis, entities across
 * the other, a score in every cell. `components/explore-matrix.tsx` draws it
 * from the same components and the same classifier `/compare` uses.
 *
 * ⚠ TEN OF THE ELEVEN COLUMNS HAVE NOTHING IN THEM, AND THEY STAY. MIS is the
 * only major with a benchmarked class today. Showing only that one would tell a
 * professor of Marketing that this benchmark has nothing for them without ever
 * admitting the reason is us and not them.
 *
 * ⚠ IT SITS ALONGSIDE THE EXISTING PAGES, IT DOES NOT REPLACE THEM. `/` and
 * `/overview` are untouched, and `/leaderboard` and `/compare` still answer the
 * questions they were built for. This is a candidate front door offered for the
 * client to react to, and deleting the others before they have would throw away
 * the comparison that decision needs.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs, ExploreHelp } from "@/components/explore-chrome";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildIndex } from "@/lib/explore";
import { buildMajorMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Explore by major — Capstone-IDA",
  description:
    "Every model against every major, drilling to a class, the outcomes behind it, and the evidence behind the number.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One row per model, strongest first, and one column per major this college " +
  "offers. Each cell is how that model does across the classes in that major " +
  "we have written tasks about — sample-weighted, so a small task cannot " +
  "outweigh a large one. Open a major to see its classes, or a model to see " +
  "its own report.";

export default async function ExplorePage() {
  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable what="the list of majors" retryHref="/explore" cause={cause} singular />
    );
  }

  const index = buildIndex(board);
  const matrix = buildMajorMatrix(board);

  return (
    <>
      <Breadcrumbs trail={[]} here="Majors" />
      <ExploreHelp explain={EXPLAIN} />

      {/* ⚠ ABOVE THE GRID IT QUALIFIES. A reader forms their impression from the
          first row they read, so a disclosure below the grid is a disclosure
          they have already formed an impression without. Same rollup and the
          same words as `/overview`, `/leaderboard` and `/compare` — see
          `summariseDemonstration`. */}
      {matrix.demonstration.any ? (
        <div className="notice">{matrix.demonstration.notice}</div>
      ) : null}

      {!matrix.available ? (
        <div className="empty">
          <h2>No major to explore</h2>
          <p className="muted">{matrix.unavailable_reason}</p>
          <p className="muted">
            The <Link href="/leaderboard">leaderboard</Link> still works — it
            groups by task rather than by curriculum.
          </p>
        </div>
      ) : (
        <>
          <ExploreMatrixGrid
            matrix={matrix}
            columnKind="Major"
            overallLabel="All majors"
          />

          {/* Courses in the shared business core that no single major owns.
              Surfaced rather than dropped: a course that is in the core but
              reachable from no major is a fact about the college, and a
              drill-down that silently omitted it would be quietly shortening
              the curriculum. */}
          {index.unassigned.length > 0 ? (
            <section className="panel">
              <div className="panel-head">
                <h2>
                  In the core, under no major
                  {index.unassigned.length === 1 ? "" : ` (${index.unassigned.length})`}
                </h2>
              </div>
              <ul className="result-list">
                {index.unassigned.map((row) => (
                  <li key={row.course} className="muted">
                    <strong>{row.course}</strong> — {row.reason}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </>
  );
}
