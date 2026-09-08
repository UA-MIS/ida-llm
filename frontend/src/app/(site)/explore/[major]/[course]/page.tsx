/**
 * Level 3: the outcomes one course teaches.
 *
 * ⚠ EVERY OUTCOME THE MAP MARKS FOR THIS COURSE GETS A TILE, including the ones
 * a text benchmark cannot reach. Showing only the measurable ones would make
 * MIS 200 look like a three-outcome course and GBA 300 like a five-outcome one,
 * which is a claim about the curriculum rather than about us — and it is the
 * exact edit `curriculum/slo.yaml` warns against, one level down.
 *
 * The published level (Introduced / Reinforced / Mastered / Assessment point) is
 * shown on every tile because it is what makes the number worth anything: a
 * benchmark aimed at a pair the department already grades is aimed at something
 * with a human number to compare against later. A pair the map marks `I` is not.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp } from "@/components/explore-chrome";
import { ExploreTile } from "@/components/explore-tile";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildCourses, buildIndex, findCourse, findMajor } from "@/lib/explore";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Course outcomes — Capstone-IDA",
  description: "The learning outcomes one course teaches, and how the models read on each.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One tile per learning outcome this course teaches, with the level the " +
  "curriculum map publishes for it. The number is how the models do on that " +
  "outcome. Open one for the evidence behind it.";

export default async function CourseOutcomesPage({
  params,
}: {
  params: Promise<{ major: string; course: string }>;
}) {
  const { major: majorSlug, course: courseSlug } = await params;

  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable
        what="this course's outcomes"
        retryHref={`/explore/${encodeURIComponent(majorSlug)}/${encodeURIComponent(courseSlug)}`}
        cause={cause}
        singular
      />
    );
  }

  const major = findMajor(buildIndex(board), majorSlug);
  if (!major) notFound();
  const course = findCourse(buildCourses(board), courseSlug);
  if (!course) notFound();

  const unmeasurable = course.outcomes.filter((o) => !o.benchmarkable);

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: "Programmes", href: "/explore" },
          { label: major.name, href: `/explore/${major.slug}` },
        ]}
        here={course.code}
      />
      <ExploreHelp explain={EXPLAIN} />

      <section className="hero">
        <h2 className="xp-title">
          <span className="xp-title-code">{course.code}</span> {course.title}
        </h2>
        <p className="subtitle">
          {course.measured_count} of {course.benchmarkable_count} measurable
          outcomes have a score.
          {unmeasurable.length > 0 ? (
            <>
              {" "}
              {unmeasurable.length === 1
                ? "One outcome it teaches"
                : `${unmeasurable.length} outcomes it teaches`}{" "}
              cannot be measured by a text benchmark at all — shown below rather
              than dropped.
            </>
          ) : null}
        </p>
      </section>

      {course.outcomes.length === 0 ? (
        <div className="empty">
          <h2>The map marks no outcomes for {course.code}</h2>
          <p className="muted">
            A blank row in the published coverage grid means the map does not mark
            this course against any outcome — not that it teaches none. The{" "}
            <Link href={`/explore/${major.slug}`}>other courses</Link> in this
            programme do.
          </p>
        </div>
      ) : (
        <ul className="xp-grid">
          {course.outcomes.map((outcome) => (
            <ExploreTile
              key={outcome.slo}
              href={`/explore/${major.slug}/${course.slug}/${outcome.slo.toLowerCase()}`}
              eyebrow={outcome.slo}
              heading={outcome.title}
              status={outcome.status}
              aggregate={outcome.aggregate}
              reason={outcome.reason}
              footnote={outcome.statement}
              badges={
                <span
                  className={`badge badge-facet${outcome.assessment_point ? " xp-badge-assessed" : ""}`}
                  title={
                    outcome.assessment_point
                      ? "The programme reports on this outcome in this course, so there is a human number to compare against."
                      : "The level the published curriculum map marks for this pair."
                  }
                >
                  {outcome.level_label}
                </span>
              }
            />
          ))}
        </ul>
      )}
    </>
  );
}
