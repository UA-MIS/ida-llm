/**
 * Level 2: the classes of one major, against every model.
 *
 * The class list is read from `curriculum/majors.yaml` — the course catalog —
 * and each class's outcome profile from `curriculum/slo.yaml`'s coverage grid,
 * joined on the course code. Nothing here holds its own list of classes, for
 * the same reason nothing holds its own list of outcomes: the registrar owns
 * both, and a list typed into a component is a list that disagrees with the
 * catalog the first time either is edited.
 *
 * ⚠ MOST OF THESE COLUMNS ARE EMPTY, AND THE EMPTINESS IS THE HONEST PART. The
 * catalog lists fourteen MIS classes; tasks have been authored about one of
 * them. Each column says which it is and why, in its own words, under the grid.
 *
 * Class order is the CATALOG's order, never score order — see `buildClasses`.
 * Putting classes on the horizontal axis is part of the same argument: a
 * vertical list of a department's own classes reads as a ranking of them, and
 * this benchmark has no business ranking a curriculum.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp, ModelFocus } from "@/components/explore-chrome";
import { ExploreMatrixGrid } from "@/components/explore-matrix";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { getLeaderboard } from "@/lib/api";
import { buildIndex, findMajor } from "@/lib/explore";
import { buildClassMatrix } from "@/lib/explore-matrix";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Classes — Capstone-IDA",
  description: "Every model against every class in one major, and what each class teaches.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One row per model, strongest first, and one column per class in this major, " +
  "in the order the catalog lists them. Each cell is how that model does on the " +
  "tasks written about that class. Open a class for the outcomes behind its " +
  "number.";

export default async function ClassesPage({
  params,
  searchParams,
}: {
  params: Promise<{ major: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { major: majorSlug } = await params;
  const query = searchParams ? await searchParams : {};
  const here = `/explore/${encodeURIComponent(majorSlug)}`;

  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable
        what="this major's classes"
        retryHref={here}
        cause={cause}
        singular
      />
    );
  }

  const major = findMajor(buildIndex(board), majorSlug);
  // ⚠ 404, NOT AN EMPTY GRID. A grid of dashes under a major's name reads as
  // "we measured this major and found nothing", which is a different and false
  // claim from "no such major is on this platform".
  if (!major) notFound();

  const matrix = buildClassMatrix(board, major);

  // Only honoured when it names a model actually on this level: a focus note
  // for a model the grid does not contain would be a caption describing a
  // different page.
  const wanted = typeof query.model === "string" ? query.model : null;
  const focus = matrix.models.find((m) => m.model_key === wanted) ?? null;

  return (
    <>
      <Breadcrumbs trail={[{ label: "Majors", href: "/" }]} here={major.name} />
      <ExploreHelp explain={EXPLAIN} />

      {matrix.demonstration.any ? (
        <div className="notice">{matrix.demonstration.notice}</div>
      ) : null}

      <section className="hero">
        <h2 className="xp-title">{major.name}</h2>
        <p className="subtitle">
          {major.class_count} {major.class_count === 1 ? "class" : "classes"}.{" "}
          {major.measurable_class_count === 0
            ? "No task in the catalogue is about any of them yet."
            : `${major.measured_class_count} of the ${major.measurable_class_count} we have written tasks about ${major.measurable_class_count === 1 ? "has" : "have"} a score so far.`}{" "}
          <span className="muted">{major.department}.</span>
          {major.catalog ? (
            <>
              {" "}
              <a className="xp-source" href={major.catalog} rel="noreferrer">
                Catalog
              </a>
            </>
          ) : null}
        </p>
      </section>

      {focus ? <ModelFocus displayName={focus.display_name} clearHref={here} /> : null}

      {!matrix.available ? (
        <div className="empty">
          <h2>This major lists no classes</h2>
          <p className="muted">{matrix.unavailable_reason}</p>
          <p className="muted">
            That is a gap in what has been transcribed from the catalog, not a
            reading of any model. <Link href="/">Back to all majors</Link>.
          </p>
        </div>
      ) : (
        <ExploreMatrixGrid
          matrix={matrix}
          columnKind="Class"
          overallLabel="All classes"
          focusModel={focus?.model_key ?? null}
        />
      )}
    </>
  );
}
