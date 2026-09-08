/**
 * Level 1 of the guided drill-down: the programmes, against every model.
 *
 * ⚠ WHY THIS FLOW EXISTS, AND WHY IT IS NOT A REDESIGN OF `/leaderboard`. The
 * client's verdict on the previous shape was blunt: too much information, too
 * many clicks, and you should not have to explain what is on the screen. The
 * remedy they prescribed is this — one grid per level, drilling from a
 * programme to a course to an outcome to the evidence, so a reader arrives at
 * exactly the thing they care about instead of a wall of everything.
 *
 * ⚠ A GRID MEANS THE MATRIX, NOT A WALL OF CARDS. The first cut of this flow
 * read "grid" as a tiled layout of paragraph cards, one per entity. It is the
 * `/compare` matrix that was asked for: entities down one axis, models across
 * the other, a score in every cell. `components/explore-matrix.tsx` draws it
 * from the same components and the same classifier `/compare` uses.
 *
 * ⚠ IT SITS ALONGSIDE THE EXISTING PAGES, IT DOES NOT REPLACE THEM. `/` and
 * `/overview` are untouched, and `/leaderboard` and `/compare` still answer the
 * questions they were built for. This is a candidate front door offered for the
 * client to react to, and deleting the others before they have would throw away
 * the comparison that decision needs.
 *
 * One programme is in the map today. It is a one-row matrix anyway — see
 * `buildMajorMatrix` in lib/explore-matrix.ts for why the level is not skipped.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs, ExploreHelp } from "@/components/explore-chrome";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildMajorMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Explore by programme — Capstone-IDA",
  description:
    "Every programme against every model, drilling to a course, an outcome, and the evidence behind the number.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One row per programme on this platform, one column per model. Each cell is " +
  "how that model does across every outcome the programme publishes and a text " +
  "benchmark can reach — sample-weighted, so a small task cannot outweigh a " +
  "large one. Open a row to see its courses.";

export default async function ExplorePage() {
  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable
        what="the programme list"
        retryHref="/explore"
        cause={cause}
        singular
      />
    );
  }

  const matrix = buildMajorMatrix(board);

  return (
    <>
      <Breadcrumbs trail={[]} here="Programmes" />
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
          <h2>No programme to explore</h2>
          <p className="muted">{matrix.unavailable_reason}</p>
          <p className="muted">
            The <Link href="/leaderboard">leaderboard</Link> still works — it
            groups by task rather than by curriculum.
          </p>
        </div>
      ) : (
        <ExploreMatrixGrid matrix={matrix} rowKind="Programme" />
      )}
    </>
  );
}
