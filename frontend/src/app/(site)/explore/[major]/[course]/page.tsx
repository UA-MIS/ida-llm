import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp, ModelFocus } from "@/components/explore-chrome";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildClasses, buildIndex, findClass, findMajor } from "@/lib/explore";
import { buildAssignmentMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Why this class reads as it does — Capstone-IDA",
  description: "Results by assignment type, against every model, with evidence behind each score.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One row per model, one column per assignment type. Each score comes from " +
  "tasks written about this class. Open an assignment type for its results and evidence.";

export default async function ClassAssignmentsPage({
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

  const matrix = buildAssignmentMatrix(board, klass, major.slug);
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
          {matrix.measured_entities} of {matrix.benchmarkable_entities} assignment types have a score.
        </p>
      </section>

      {focus ? <ModelFocus displayName={focus.display_name} clearHref={here} /> : null}

      {!matrix.available ? (
        <div className="empty">
          <h2>No assignment breakdown for {klass.code}</h2>
          <p className="muted">{matrix.unavailable_reason}</p>
          <p className="muted">
            That is a gap in what has been published and run, not a reading of
            any model.
          </p>
        </div>
      ) : (
        <ExploreMatrixGrid
          matrix={matrix}
          columnKind="Assignment type"
          overallLabel="All assignment types"
          focusModel={focus?.model_key ?? null}
        />
      )}
    </>
  );
}
