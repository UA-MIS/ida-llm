/**
 * Level 3: the outcomes one course teaches, against every model.
 *
 * ⚠ THIS IS `/compare`, SCOPED TO ONE COURSE, AND THAT IS THE WHOLE IDEA. The
 * comparison grid shows every model against every outcome the programme
 * publishes; a professor who teaches MIS 200 wants the same grid narrowed to
 * the outcomes MIS 200 is responsible for. Same cells, same ramp, same three
 * empty states, same classifier — see `components/explore-matrix.tsx`. Reusing
 * it rather than restyling it is what stops this page from quietly disagreeing
 * with the leaderboard it is drawn from.
 *
 * ⚠ EVERY OUTCOME THE MAP MARKS FOR THIS COURSE GETS A ROW, including the ones
 * a text benchmark cannot reach. Showing only the measurable ones would make
 * MIS 200 look like a three-outcome course and GBA 300 like a five-outcome one,
 * which is a claim about the curriculum rather than about us — and it is the
 * exact edit `curriculum/slo.yaml` warns against, one level down.
 *
 * The published level (Introduced / Reinforced / Mastered / Assessment point)
 * is shown on every row because it is what makes the number worth anything: a
 * benchmark aimed at a pair the department already grades is aimed at something
 * with a human number to compare against later. A pair the map marks `I` is not.
 */

import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp } from "@/components/explore-chrome";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildCourses, buildIndex, findCourse, findMajor } from "@/lib/explore";
import { buildOutcomeMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Course outcomes — Capstone-IDA",
  description: "The learning outcomes one course teaches, against every model, in one grid.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One row per learning outcome this course teaches, with the level the " +
  "curriculum map publishes for it, and one column per model. Each cell is how " +
  "that model does on that outcome. Open a row for the evidence behind it.";

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

  const matrix = buildOutcomeMatrix(board, course, major.slug);
  const unmeasurable = course.outcomes.filter((o) => !o.benchmarkable);
  // The map's published level for each outcome, by id — the badge on each row.
  const levels = new Map(course.outcomes.map((o) => [o.slo, o]));

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

      {/* ⚠ ABOVE THE GRID IT QUALIFIES, same as every other level — see
          `/explore/page.tsx`. Scoped to this course's own outcomes, not the
          whole board: only the models that actually contributed a score here
          are counted, so a course whose own outcomes are all measured never
          carries a caveat that belongs to a different course. Same rollup,
          same words — see `summariseDemonstration`. */}
      {matrix.demonstration.any ? (
        <div className="notice">{matrix.demonstration.notice}</div>
      ) : null}

      <section className="hero">
        <h2 className="xp-title">
          <span className="xp-title-code">{course.code}</span> {course.title}
        </h2>
        <p className="subtitle">
          {/* ⚠ COUNTED OFF THE GRID ITSELF, not off a parallel tally. This
              level's rows ARE its outcomes, so the sentence above the matrix
              and the matrix cannot end up describing different things. */}
          {matrix.measured_rows} of {matrix.benchmarkable_rows} measurable
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

      {!matrix.available ? (
        <div className="empty">
          <h2>The map marks no outcomes for {course.code}</h2>
          <p className="muted">{matrix.unavailable_reason}</p>
        </div>
      ) : (
        <ExploreMatrixGrid
          matrix={matrix}
          rowKind="Outcome"
          badgeFor={(row) => {
            const outcome = levels.get(row.key);
            if (!outcome) return null;
            const assessed = outcome.assessment_point;
            return (
              <span
                className={`badge badge-facet${assessed ? " xp-badge-assessed" : ""}`}
                title={
                  assessed
                    ? "The programme reports on this outcome in this course, so there is a human number to compare against."
                    : "The level the published curriculum map marks for this pair."
                }
              >
                {outcome.level_label}
              </span>
            );
          }}
        />
      )}
    </>
  );
}
