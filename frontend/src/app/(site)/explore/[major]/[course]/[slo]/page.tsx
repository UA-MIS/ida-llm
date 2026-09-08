/**
 * Level 4: why the number on the level above is what it is.
 *
 * This is the bottom of the drill-down and the only level that is not a grid,
 * because it is not a set of choices — it is one pair, opened. Three things, in
 * the order a sceptical reader asks for them:
 *
 *   1. what the outcome is, and how it is scored (the curriculum's own words)
 *   2. how each model does on it, with the confidence on every number
 *   3. the tasks behind those numbers, each row linking to the run that
 *      produced it — the transcripts, the scorer, the serving config
 *
 * ⚠ NOTHING NEW IS COMPUTED HERE. The per-model reads come from the same
 * `aggregate` every other page uses, and the receipts are the existing
 * `ModelResultCard` pointed at the same run records the leaderboard links to. A
 * second implementation of "what does this model score" would eventually
 * disagree with the first, and the disagreement would surface here — on the one
 * page whose entire job is to be checkable.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Breadcrumbs, ExploreHelp } from "@/components/explore-chrome";
import { ModelResultCard } from "@/components/model-result-card";
import { ResultsUnavailable } from "@/components/service-unavailable";
import { ConfidenceTell, DemonstrationBadge } from "@/components/trust-badges";
import { getLeaderboard } from "@/lib/api";
import {
  buildCourses,
  buildEvidence,
  buildIndex,
  findCourse,
  findMajor,
  findOutcome,
  NOT_MEASURED,
  type EvidenceRow,
} from "@/lib/explore";
import { formatScore } from "@/lib/format";
import { confidenceLabel, WEIGHTING_NOTE } from "@/lib/rollup";
import type { LeaderboardResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "The evidence — Capstone-IDA",
  description: "How each model does on one learning outcome, and the runs behind every number.",
};

/**
 * The one sentence this grid would need if a reader asked for it.
 *
 * ⚠ NOT EXPORTED. Next treats any non-reserved export from a page file as
 * an error, and it is right to: a page module's exports are a framework
 * contract, not a place to share a string.
 */
const EXPLAIN =
  "One learning outcome, opened. The table is how each model reads on it; the " +
  "tasks below are what produced those numbers, and every row opens the run " +
  "that made it — the prompts, the answers and how they were marked.";

function ModelRow({ row }: { row: EvidenceRow }) {
  const agg = row.aggregate;
  return (
    <tr className={row.recommendable ? undefined : "row-muted"}>
      <th scope="row">
        <Link href={`/models/${encodeURIComponent(row.model_key)}`}>
          {row.display_name}
        </Link>
        <span className="model-sub muted">{row.data_residency_label}</span>
        {/* Per model, so it self-clears the moment a real measurement replaces
            the seeded one — see `isSeeded`. */}
        {row.seeded ? (
          <span className="model-sub">
            <DemonstrationBadge />
          </span>
        ) : null}
      </th>
      <td className="col-score">
        {agg.score === null ? (
          <span className="muted">— {NOT_MEASURED}</span>
        ) : (
          formatScore(agg.score)
        )}
      </td>
      <td className="col-trust">
        {agg.score === null ? (
          <span className="muted">—</span>
        ) : (
          <ConfidenceTell
            confidence={agg.confidence}
            label={confidenceLabel(agg.confidence)}
            reason={`${confidenceLabel(agg.confidence)}. How much weight this number can bear — how it was marked, over how many attempts, and whether anything failed. It is about the measurement, not about the model.`}
          />
        )}
      </td>
      <td className="muted">
        {agg.scored_samples} of {agg.sample_count}
        {agg.error_count > 0 ? (
          <>
            {" "}
            · <strong>{agg.error_count} errored</strong>
          </>
        ) : null}
      </td>
      <td className="col-go">
        {agg.latest_run_id ? (
          <Link href={`/runs/${encodeURIComponent(agg.latest_run_id)}`}>
            Latest run
          </Link>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
    </tr>
  );
}

export default async function EvidencePage({
  params,
}: {
  params: Promise<{ major: string; course: string; slo: string }>;
}) {
  const { major: majorSlug, course: courseSlug, slo } = await params;
  const here = `/explore/${encodeURIComponent(majorSlug)}/${encodeURIComponent(courseSlug)}/${encodeURIComponent(slo)}`;

  let board: LeaderboardResponse;
  try {
    board = await getLeaderboard();
  } catch (cause) {
    return (
      <ResultsUnavailable what="this evidence" retryHref={here} cause={cause} singular />
    );
  }

  const major = findMajor(buildIndex(board), majorSlug);
  if (!major) notFound();
  const course = findCourse(buildCourses(board), courseSlug);
  if (!course) notFound();
  const outcome = findOutcome(course, slo);
  // ⚠ 404 FOR A PAIR THE MAP DOES NOT MARK. Rendering an empty evidence page for
  // (AC 210, SLO7) would say "we looked and found nothing" about a pairing the
  // curriculum never claimed existed.
  if (!outcome) notFound();

  const evidence = buildEvidence(board, course, outcome);
  const rows = [...evidence.ranked, ...evidence.unranked];

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: "Programmes", href: "/explore" },
          { label: major.name, href: `/explore/${major.slug}` },
          { label: course.code, href: `/explore/${major.slug}/${course.slug}` },
        ]}
        here={outcome.slo}
      />
      <ExploreHelp explain={EXPLAIN} />

      {evidence.demonstration.any ? (
        <div className="notice">{evidence.demonstration.notice}</div>
      ) : null}

      <section className="hero">
        <h2 className="xp-title">
          <span className="xp-title-code">{outcome.slo}</span> {outcome.title}
        </h2>
        <p className="subtitle">{outcome.statement}</p>
        <p className="muted xp-level">
          {course.code} teaches this at <strong>{outcome.level_label}</strong>.
          {outcome.assessment_point ? (
            <>
              {" "}
              The programme reports on this outcome here, so it already has a
              human number to compare against.
            </>
          ) : null}
        </p>
      </section>

      {/* The curriculum's own reasoning about HOW this outcome is scored — or
          why it is not. Quoted from the map rather than paraphrased: it is the
          answer to "should I believe this number", and it is not ours to
          rewrite. */}
      {outcome.note ? (
        <section className="panel">
          <div className="panel-head">
            <h2>How this outcome is scored</h2>
          </div>
          <p className="outcome-note">{outcome.note}</p>
        </section>
      ) : null}

      {outcome.status === "not_benchmarkable" ? (
        <div className="empty">
          <h2>Nothing was run for this outcome, deliberately</h2>
          <p className="muted">
            The curriculum marks it as one a single-turn text benchmark cannot
            measure. Scoring something adjacent and filing it here would be worse
            than leaving it empty, so it is empty.
          </p>
          <p className="muted">
            The rest of {course.code} is on the{" "}
            <Link href={`/explore/${major.slug}/${course.slug}`}>course page</Link>.
          </p>
        </div>
      ) : rows.length === 0 ? (
        <div className="empty">
          <h2>{NOT_MEASURED}</h2>
          <p className="muted">{outcome.reason}</p>
          <p className="muted">
            No model has a finished, scored run against{" "}
            {outcome.tasks_available === 1 ? "the task" : "the tasks"} filed under{" "}
            {outcome.slo}. That is a gap in what we have run, not a reading of any
            model.
          </p>
        </div>
      ) : (
        <section className="panel panel-lead">
          <div className="panel-head">
            <h2>How the models do</h2>
            <p className="muted panel-note">{WEIGHTING_NOTE}</p>
          </div>
          <div className="table-scroll">
            <table className="leaderboard">
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col">Score</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Scored samples</th>
                  <th scope="col">Receipt</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <ModelRow key={row.model_key} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* The "on what". A score with no visible task behind it is a number
          somebody has to take on trust, which is the thing this product exists
          not to ask for. */}
      {evidence.tasks.length > 0 ? (
        <section className="panel">
          <div className="panel-head">
            <h2>What was asked</h2>
            <p className="muted panel-note">
              {evidence.tasks.length}{" "}
              {evidence.tasks.length === 1 ? "task measures" : "tasks measure"}{" "}
              {outcome.slo}. Every row opens the run behind it — the prompts, the
              answers and how they were marked.
            </p>
          </div>

          {evidence.tasks.map((task) => (
            <div key={task.task_id} className="task-section">
              <h3 className="task-title">
                <Link href={`/leaderboard?task=${encodeURIComponent(task.task_id)}`}>
                  {task.title}
                </Link>
              </h3>
              <p className="task-description muted">{task.description}</p>
              {task.results.length === 0 ? (
                <p className="muted">
                  {NOT_MEASURED} — no model has a finished run against this task.
                </p>
              ) : (
                <ul className="result-list">
                  {task.results.map((result, index) => (
                    <ModelResultCard
                      key={result.model_key}
                      result={result}
                      rank={index + 1}
                      isBest={result.model_key === task.best_model_key}
                    />
                  ))}
                </ul>
              )}
            </div>
          ))}
        </section>
      ) : null}
    </>
  );
}
