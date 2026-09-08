/**
 * Level 3: WHY one class's number is what it is — its outcomes, against every
 * model.
 *
 * ⚠ THIS IS THE "WHY" LEVEL, AND IT IS `/compare` SCOPED TO ONE CLASS. The
 * comparison grid shows every model against every outcome the programme
 * publishes; a professor who teaches MIS 200 wants that grid narrowed to the
 * outcomes MIS 200 is responsible for, built only from tasks about MIS 200.
 * Same cells, same ramp, same three empty states, same classifier — see
 * `components/explore-matrix.tsx`. Reusing it rather than restyling it is what
 * stops this page from quietly disagreeing with the leaderboard it is drawn
 * from.
 *
 * ⚠ EVERY OUTCOME THE MAP MARKS FOR THIS CLASS GETS A COLUMN, including the
 * ones a text benchmark cannot reach. Showing only the measurable ones would
 * make MIS 200 look like a three-outcome class and GBA 300 like a five-outcome
 * one, which is a claim about the curriculum rather than about us — and it is
 * the exact edit `curriculum/slo.yaml` warns against, one level down.
 *
 * ⚠ A CLASS THE CURRICULUM MAP DOES NOT COVER IS THE COMMON CASE HERE, not an
 * error. The catalog lists fourteen MIS classes and the core map marks one of
 * them; the other thirteen reach this page and say so, rather than 404ing as
 * though the class did not exist.
 *
 * The published level (Introduced / Reinforced / Mastered / Assessment point)
 * is shown on every column because it is what makes the number worth anything:
 * a benchmark aimed at a pair the department already grades is aimed at
 * something with a human number to compare against later. A pair the map marks
 * `I` is not.
 */

import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp, ModelFocus } from "@/components/explore-chrome";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildClasses, buildIndex, findClass, findMajor } from "@/lib/explore";
import { buildOutcomeMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Why this class reads as it does — Capstone-IDA",
  description:
    "The learning outcomes one class teaches, against every model, in one grid — the breakdown behind the class's number.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "The breakdown behind this class's number: one row per model, one column per " +
  "learning outcome the class teaches, with the level the curriculum map " +
  "publishes for it. Each cell is how that model does on that outcome, from " +
  "tasks written about this class. Open a column for the evidence behind it.";

export default async function ClassOutcomesPage({
  params,
  searchParams,
}: {
  params: Promise<{ major: string; course: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { major: majorSlug, course: courseSlug } = await params;
  const query = searchParams ? await searchParams : {};
  const here = `/explore/${encodeURIComponent(majorSlug)}/${encodeURIComponent(courseSlug)}`;

  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable
        what="this class's breakdown"
        retryHref={here}
        cause={cause}
        singular
      />
    );
  }

  const major = findMajor(buildIndex(board), majorSlug);
  if (!major) notFound();
  const klass = findClass(buildClasses(board, major), courseSlug);
  if (!klass) notFound();

  const matrix = buildOutcomeMatrix(board, klass, major.slug);
  const unmeasurable = klass.outcomes.filter((o) => !o.benchmarkable);
  // The map's published level for each outcome, by id — the badge on each column.
  const levels = new Map(klass.outcomes.map((o) => [o.slo, o]));

  const wanted = typeof query.model === "string" ? query.model : null;
  const focus = matrix.models.find((m) => m.model_key === wanted) ?? null;

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: "Majors", href: "/explore" },
          { label: major.name, href: `/explore/${major.slug}` },
        ]}
        here={klass.code}
      />
      <ExploreHelp explain={EXPLAIN} />

      {/* ⚠ ABOVE THE GRID IT QUALIFIES, same as every other level — see
          `/explore/page.tsx`. Scoped to this class's own results, not the whole
          board: only the models that actually contributed a score here are
          counted, so a class whose own outcomes are all measured never carries
          a caveat that belongs to a different class. Same rollup, same words —
          see `summariseDemonstration`. */}
      {matrix.demonstration.any ? (
        <div className="notice">{matrix.demonstration.notice}</div>
      ) : null}

      <section className="hero">
        <h2 className="xp-title">
          <span className="xp-title-code">{klass.code}</span> {klass.title}
        </h2>
        <p className="subtitle">
          {!klass.in_curriculum_map ? (
            <>{klass.reason}</>
          ) : (
            <>
              {/* ⚠ COUNTED OFF THE GRID ITSELF, not off a parallel tally. This
                  level's columns ARE its outcomes, so the sentence above the
                  matrix and the matrix cannot end up describing different
                  things. */}
              {matrix.measured_entities} of {matrix.benchmarkable_entities} measurable
              outcomes have a score.
              {unmeasurable.length > 0 ? (
                <>
                  {" "}
                  {unmeasurable.length === 1
                    ? "One outcome it teaches"
                    : `${unmeasurable.length} outcomes it teaches`}{" "}
                  cannot be measured by a text benchmark at all — shown below
                  rather than dropped.
                </>
              ) : null}
            </>
          )}
        </p>
      </section>

      {focus ? <ModelFocus displayName={focus.display_name} clearHref={here} /> : null}

      {!matrix.available ? (
        <div className="empty">
          <h2>No outcome breakdown for {klass.code}</h2>
          <p className="muted">{matrix.unavailable_reason}</p>
          <p className="muted">
            That is a gap in what has been published and run, not a reading of
            any model.
          </p>
        </div>
      ) : (
        <ExploreMatrixGrid
          matrix={matrix}
          columnKind="Outcome"
          overallLabel="All outcomes"
          focusModel={focus?.model_key ?? null}
          badgeFor={(entity) => {
            const outcome = levels.get(entity.key);
            if (!outcome) return null;
            const assessed = outcome.assessment_point;
            return (
              <span
                className={`badge badge-facet${assessed ? " xp-badge-assessed" : ""}`}
                title={
                  assessed
                    ? "The programme reports on this outcome in this class, so there is a human number to compare against."
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
