/**
 * Level 2: the courses of one programme.
 *
 * Read from the published course x outcome coverage grid, which the API now
 * serves alongside the outcomes (`CurriculumView.coverage`). Nothing here holds
 * its own list of courses, for the same reason nothing holds its own list of
 * outcomes: the registrar owns both, and a list typed into a component is a list
 * that disagrees with the programme the first time either is edited.
 *
 * Course order is the MAP's order, never score order — see `buildCourses`.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp } from "@/components/explore-chrome";
import { ExploreTile } from "@/components/explore-tile";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildCourses, buildIndex, findMajor } from "@/lib/explore";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Courses — Capstone-IDA",
  description: "Every course in the programme, and how the models read on what it teaches.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One tile per course in this programme, in the order the curriculum map " +
  "publishes them. The number is how the models do across the outcomes that " +
  "course is responsible for. Open one to see those outcomes.";

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

  const index = buildIndex(board);
  const major = findMajor(index, majorSlug);
  // ⚠ 404, NOT AN EMPTY GRID. A page of dashes under a programme name reads as
  // "we measured this programme and found nothing", which is a different and
  // false claim from "no such programme is on this platform".
  if (!major) notFound();

  const courses = buildCourses(board);

  return (
    <>
      <Breadcrumbs trail={[{ label: "Programmes", href: "/explore" }]} here={major.name} />
      <ExploreHelp explain={EXPLAIN} />

      {index.demonstration.any ? (
        <div className="notice">{index.demonstration.notice}</div>
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

      {courses.length === 0 ? (
        <div className="empty">
          <h2>This programme lists no courses</h2>
          <p className="muted">
            The curriculum map has no coverage grid for it, so there is nothing to
            drill into. The <Link href="/compare">comparison grid</Link> still
            reads by outcome.
          </p>
        </div>
      ) : (
        <ul className="xp-grid">
          {courses.map((course) => (
            <ExploreTile
              key={course.slug}
              href={`/explore/${major.slug}/${course.slug}`}
              eyebrow={course.code}
              heading={course.title}
              status={course.status}
              aggregate={course.aggregate}
              reason={course.reason}
              footnote={
                <>
                  Teaches {course.outcomes.length}{" "}
                  {course.outcomes.length === 1 ? "outcome" : "outcomes"}
                  {course.assessment_count > 0 ? (
                    <>
                      {" "}
                      ·{" "}
                      <strong>
                        {course.assessment_count} assessment{" "}
                        {course.assessment_count === 1 ? "point" : "points"}
                      </strong>
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
