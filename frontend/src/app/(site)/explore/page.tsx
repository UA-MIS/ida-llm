/**
 * Level 1 of the guided drill-down: the programmes.
 *
 * ⚠ WHY THIS FLOW EXISTS, AND WHY IT IS NOT A REDESIGN OF `/leaderboard`. The
 * client's verdict on the previous shape was blunt: too much information, too
 * many clicks, and you should not have to explain what is on the screen. The
 * remedy they prescribed is this — one grid per level, drilling from a
 * programme to a course to an outcome to the evidence, so a reader arrives at
 * exactly the thing they care about instead of a wall of everything.
 *
 * ⚠ IT SITS ALONGSIDE THE EXISTING PAGES, IT DOES NOT REPLACE THEM. `/` and
 * `/overview` are untouched, and `/leaderboard` and `/compare` still answer the
 * questions they were built for. This is a candidate front door offered for the
 * client to react to, and deleting the others before they have would throw away
 * the comparison that decision needs.
 *
 * One programme is in the map today. The grid is a grid anyway — see
 * `buildIndex` in lib/explore.ts for why the level is not skipped.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { Breadcrumbs, ExploreHelp } from "@/components/explore-chrome";
import { ExploreTile } from "@/components/explore-tile";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildIndex } from "@/lib/explore";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Explore by programme — Capstone-IDA",
  description:
    "Drill from a programme to a course to a learning outcome to the evidence behind the number.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One tile per programme on this platform. The number is how the models do " +
  "across every outcome that programme publishes and a text benchmark can " +
  "reach — sample-weighted, so a small task cannot outweigh a large one. Open " +
  "one to see its courses.";

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

  const index = buildIndex(board);

  return (
    <>
      <Breadcrumbs trail={[]} here="Programmes" />
      <ExploreHelp explain={EXPLAIN} />

      {/* ⚠ ABOVE THE GRID IT QUALIFIES. A reader forms their impression from the
          first tile they read, so a disclosure below the grid is a disclosure
          they have already formed an impression without. Same rollup and the
          same words as `/overview`, `/leaderboard` and `/compare` — see
          `summariseDemonstration`. */}
      {index.demonstration.any ? (
        <div className="notice">{index.demonstration.notice}</div>
      ) : null}

      {!index.available ? (
        <div className="empty">
          <h2>No programme to explore</h2>
          <p className="muted">{index.unavailable_reason}</p>
          <p className="muted">
            The <Link href="/leaderboard">leaderboard</Link> still works — it
            groups by task rather than by curriculum.
          </p>
        </div>
      ) : (
        <ul className="xp-grid xp-grid-wide">
          {index.majors.map((major) => (
            <ExploreTile
              key={major.slug}
              href={`/explore/${major.slug}`}
              eyebrow="Programme"
              heading={major.name}
              status={major.status}
              aggregate={major.aggregate}
              reason={major.reason}
              footnote={
                <>
                  {major.course_count} courses ·{" "}
                  {major.measured_count} of {major.benchmarkable_count} measurable
                  outcomes have a score
                  {major.benchmarkable_count < major.outcome_count ? (
                    <>
                      {" "}
                      · {major.outcome_count - major.benchmarkable_count} of{" "}
                      {major.outcome_count} outcomes cannot be measured by a text
                      benchmark
                    </>
                  ) : null}
                </>
              }
            />
          ))}
        </ul>
      )}
    </>
  );
}
