import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp, ModelFocus } from "@/components/explore-chrome";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildClasses, buildIndex, findClass, findMajor } from "@/lib/explore";
import { buildUnitMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "What this class is made of — Capstone-IDA",
  description:
    "The course units that make up this class, against every model, with the evidence behind each score.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One row per model, one column per unit of this class — each column lists what " +
  "that unit's tests cover. Each score comes from tasks written about this " +
  "class's own material. Open a score to see every question and the run behind it.";

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

  const matrix = buildUnitMatrix(board, klass, major.slug);
  const wanted = typeof query.model === "string" ? query.model : null;
  const focus = matrix.models.find((m) => m.model_key === wanted) ?? null;

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: "Majors", href: "/" },
          { label: major.name, href: `/explore/${major.slug}` },
        ]}
        here={klass.code}
      />
      <ExploreHelp explain={EXPLAIN} />

      {/* ⚠ ABOVE THE GRID IT QUALIFIES, same as every other level — see
          `/explore/page.tsx`. Scoped to this class's own results, not the whole
          board: only the models that actually contributed a score here are
          counted, so a class whose own categories are all measured never carries
          a caveat that belongs to a different class. Same rollup, same words —
          see `summariseDemonstration`. */}
      {matrix.demonstration.any ? (
        <div className="notice">{matrix.demonstration.notice}</div>
      ) : null}

      <section className="hero">
        <p className="xp-kicker">{klass.code}</p>
        <h2 className="xp-title">{klass.title}</h2>
        <p className="subtitle">
          {matrix.entities.length} {matrix.entities.length === 1 ? "unit" : "units"}. Each column
          lists what that unit&rsquo;s tests cover. {matrix.measured_entities} of{" "}
          {matrix.benchmarkable_entities}{" "}
          {matrix.measured_entities === 1 ? "has" : "have"} a score so far.
        </p>
      </section>

      {focus ? <ModelFocus displayName={focus.display_name} clearHref={here} /> : null}

      {!matrix.available ? (
        <div className="empty">
          <h2>No unit breakdown for {klass.code}</h2>
          <p className="muted">{matrix.unavailable_reason}</p>
          <p className="muted">
            That is a gap in what has been published and run, not a reading of
            any model.
          </p>
        </div>
      ) : (
        <ExploreMatrixGrid
          matrix={matrix}
          columnKind="Unit"
          overallLabel="Overall"
          focusModel={focus?.model_key ?? null}
        />
      )}
    </>
  );
}
