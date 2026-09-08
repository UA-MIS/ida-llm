/**
 * Level 2: the courses of one programme, against every model.
 *
 * Read from the published course x outcome coverage grid, which the API serves
 * alongside the outcomes (`CurriculumView.coverage`). Nothing here holds its own
 * list of courses, for the same reason nothing holds its own list of outcomes:
 * the registrar owns both, and a list typed into a component is a list that
 * disagrees with the programme the first time either is edited.
 *
 * Course order is the MAP's order, never score order — see `buildCourses`. A
 * matrix makes that temptation stronger, not weaker: rows sorted by score would
 * turn a coverage grid into a ranking of a department's own courses.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp } from "@/components/explore-chrome";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildIndex, findMajor } from "@/lib/explore";
import { buildCourseMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Courses — Capstone-IDA",
  description: "Every course in the programme against every model, and what each one teaches.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One row per course in this programme, in the order the curriculum map " +
  "publishes them, and one column per model. Each cell is how that model does " +
  "across the outcomes that course is responsible for. Open a row to see those " +
  "outcomes.";

export default async function CoursesPage({
  params,
}: {
  params: Promise<{ major: string }>;
}) {
  const { major: majorSlug } = await params;

  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable
        what="this programme's courses"
        retryHref={`/explore/${encodeURIComponent(majorSlug)}`}
        cause={cause}
        singular
      />
    );
  }

  const major = findMajor(buildIndex(board), majorSlug);
  // ⚠ 404, NOT AN EMPTY GRID. A grid of dashes under a programme name reads as
  // "we measured this programme and found nothing", which is a different and
  // false claim from "no such programme is on this platform".
  if (!major) notFound();

  const matrix = buildCourseMatrix(board, major.slug);

  return (
    <>
      <Breadcrumbs trail={[{ label: "Programmes", href: "/explore" }]} here={major.name} />
      <ExploreHelp explain={EXPLAIN} />

      {matrix.demonstration.any ? (
        <div className="notice">{matrix.demonstration.notice}</div>
      ) : null}

      <section className="hero">
        <h2 className="xp-title">{major.name}</h2>
        <p className="subtitle">
          {major.course_count} courses. {major.measured_count} of{" "}
          {major.benchmarkable_count} measurable outcomes have a score so far.
          {major.source ? (
            <>
              {" "}
              <a className="xp-source" href={major.source} rel="noreferrer">
                Curriculum map
              </a>
            </>
          ) : null}
        </p>
      </section>

      {!matrix.available ? (
        <div className="empty">
          <h2>This programme lists no courses</h2>
          <p className="muted">{matrix.unavailable_reason}</p>
          <p className="muted">
            The <Link href="/compare">comparison grid</Link> still reads by
            outcome.
          </p>
        </div>
      ) : (
        <ExploreMatrixGrid matrix={matrix} rowKind="Course" />
      )}
    </>
  );
}
