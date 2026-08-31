/**
 * One model's report card — every number about it, in one place.
 *
 * ⚠ THIS IS THE SCREEN THAT DID NOT EXIST. The site was task-first end to end:
 * to learn what one model could do you opened seventy task views and read one
 * row out of each. "Show me this model's results" was not a slow path, it was
 * not a path at all.
 *
 * Built entirely by regrouping `GET /leaderboard` — no new endpoint, because the
 * unfiltered response already contains every task × model pairing and a second
 * server-side aggregation would eventually disagree with the first.
 *
 * ⚠ THE UNMEASURED ROWS ARE LOAD-BEARING. Every outcome the programme publishes
 * gets a row here, including the ones this model has never been run against, and
 * including the two the curriculum marks as not measurable by a text benchmark
 * at all. A report card listing only the outcomes with data is a highlight reel:
 * seven strong rows read as full coverage. The gaps are stated in words; they
 * are never rendered as a zero, and there is no bar drawn for them.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { GlossaryPanel, Term } from "@/components/glossary";
import { HowToRead, ReadStep } from "@/components/how-to-read";
import { ScoreBar } from "@/components/score-bar";
import {
  Caveats,
  ConfidenceMeter,
  ConfidenceTell,
  ResidencyBadge,
  TrustBadge,
} from "@/components/trust-badges";
import { getLeaderboard } from "@/lib/api";
import { formatCost, formatTimestamp } from "@/lib/format";
import { REPORT_CARD_TERMS } from "@/lib/glossary";
import {
  confidenceLabel,
  findRollup,
  rollupByOutcome,
  WEIGHTING_NOTE,
  type ModelRollup,
  type OutcomeRollup,
} from "@/lib/rollup";
import { outcomeHeading } from "@/lib/trust";
import type { CurriculumView } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  return { title: `${decodeURIComponent(key)} — Capstone-IDA` };
}

/** The headline block: what this model is, and how it does overall. */
function ReportHead({
  rollup,
  outcomeCount,
}: {
  rollup: ModelRollup;
  outcomeCount: number;
}) {
  const { overall } = rollup;
  return (
    <section className="panel panel-lead report-head">
      <div className="report-identity">
        <h2 className="report-title">{rollup.display_name}</h2>
        <div className="model-sub">
          <span className="mono muted">{rollup.model_key}</span>
          <ResidencyBadge
            residency={rollup.data_residency}
            label={rollup.data_residency_label}
          />
          {!rollup.recommendable ? (
            <span
              className="badge badge-partial"
              title="A deterministic stub used to exercise the pipeline. Its numbers are real; they are just not about a model."
            >
              test stub — never recommended
            </span>
          ) : null}
          {!rollup.enabled ? (
            <span
              className="badge"
              title="These measurements stand — they happened — but the registry has since disabled the model, so it cannot be run today."
            >
              not currently runnable
            </span>
          ) : null}
        </div>
      </div>

      <div className="report-score">
        <div className="report-score-label muted">Overall score</div>
        <ScoreBar
          score={overall.score}
          size="large"
          note={
            overall.score === null
              ? "nothing measured yet"
              : `${overall.scored_samples} scored samples across ${overall.measured_tasks} task${overall.measured_tasks === 1 ? "" : "s"}`
          }
        />
        <ConfidenceTell
          confidence={overall.confidence}
          label={confidenceLabel(overall.confidence)}
          reason={`The weakest confidence among the ${overall.measured_tasks} measurement${overall.measured_tasks === 1 ? "" : "s"} behind this number, not an average of them.`}
        />
      </div>

      <dl className="grid report-stats">
        <div>
          <dt>
            <Term id="learning-outcome">Outcomes</Term> covered
          </dt>
          <dd>
            {rollup.slos_measured.length}{" "}
            <span className="muted">of {outcomeCount} published</span>
          </dd>
        </div>
        <div>
          <dt>
            <Term id="task">Tasks</Term> measured
          </dt>
          <dd>
            {overall.measured_tasks}{" "}
            <span className="muted">of {overall.covered_tasks} attempted</span>
          </dd>
        </div>
        <div>
          <dt>
            <Term id="sample">Attempts</Term> scored
          </dt>
          <dd>
            {overall.scored_samples}{" "}
            <span className="muted">of {overall.sample_count} run</span>
          </dd>
        </div>
        <div>
          <dt>
            <Term id="errored-sample">Failed attempts</Term>
          </dt>
          <dd className={overall.error_count > 0 ? "" : "muted"}>
            {overall.error_count > 0 ? overall.error_count : "none"}
          </dd>
        </div>
        <div>
          <dt>
            Checked vs <Term id="judged">judged</Term>
          </dt>
          <dd>
            {Math.round(overall.verifiable_share * 100)}%{" "}
            <span className="muted">of the weight programmatically checked</span>
          </dd>
        </div>
        <div>
          <dt>Total cost</dt>
          <dd>{formatCost(overall.total_cost_usd)}</dd>
        </div>
        <div>
          <dt>Where data goes</dt>
          <dd>{rollup.data_residency_label}</dd>
        </div>
        <div>
          <dt>Last measured</dt>
          <dd className="muted">{formatTimestamp(overall.latest_measured_at)}</dd>
        </div>
      </dl>

      <p className="muted panel-note report-weighting">{WEIGHTING_NOTE}</p>
    </section>
  );
}

/** One outcome row — measured or, honestly, not. */
function OutcomeRow({ row }: { row: OutcomeRollup }) {
  const { aggregate: agg } = row;
  const notBenchmarkable = row.outcome?.text_benchmarkable === false;
  return (
    <tr className={agg.score === null ? "row-muted" : undefined}>
      <td>
        <div className="outcome-cell-heading">{row.heading}</div>
        {row.outcome ? (
          <p className="muted outcome-cell-statement">{row.outcome.statement}</p>
        ) : null}
      </td>
      <td className="col-score">
        <ScoreBar
          score={agg.score}
          note={
            agg.score !== null
              ? `${agg.scored_samples} scored sample${agg.scored_samples === 1 ? "" : "s"}`
              : notBenchmarkable
                ? "not measurable by a text benchmark"
                : agg.covered_tasks > 0
                  ? "run, but nothing scored"
                  : "not measured"
          }
        />
      </td>
      <td className="num col-optional">
        {agg.measured_tasks}
        <span className="muted"> / {row.tasks_available}</span>
      </td>
      <td className="col-optional">
        {agg.score === null ? (
          <span className="muted">
            {notBenchmarkable
              ? (row.outcome?.benchmark_note ??
                "The curriculum records this outcome as not measurable by a single-turn text benchmark.")
              : row.tasks_available === 0
                ? "No task in the catalogue measures this outcome yet."
                : "This model has not been run against it."}
          </span>
        ) : (
          <ConfidenceTell
            confidence={agg.confidence}
            label={confidenceLabel(agg.confidence)}
            reason={`The weakest confidence among the ${agg.measured_tasks} measurement${agg.measured_tasks === 1 ? "" : "s"} under ${row.slo ?? "this heading"}.`}
          />
        )}
      </td>
      <td>
        {/* D-3: the evidence is one click from the number, always. */}
        {agg.latest_run_id ? (
          <Link href={`/runs/${agg.latest_run_id}`}>See the proof ▸</Link>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
    </tr>
  );
}

/** Every task this model has a row for, with its own trust tell intact. */
function TaskBreakdown({
  rollup,
  curriculum,
}: {
  rollup: ModelRollup;
  curriculum: CurriculumView;
}) {
  const entries = [...rollup.entries].sort((a, b) => {
    const left = a.result.mean_score;
    const right = b.result.mean_score;
    if (left === null && right === null) return a.task_title.localeCompare(b.task_title);
    if (left === null) return 1;
    if (right === null) return -1;
    return right - left;
  });

  return (
    <div className="table-scroll">
      <table className="task-table">
        <thead>
          <tr>
            <th>Task</th>
            <th className="col-optional">Outcome</th>
            <th className="col-score">Score</th>
            <th className="col-optional">Evidence</th>
            <th>Receipt</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={entry.task_id}
              className={entry.result.mean_score === null ? "row-muted" : undefined}
            >
              <td>
                <Link href={`/leaderboard?task=${encodeURIComponent(entry.task_id)}`}>
                  {entry.task_title}
                </Link>
                <div className="mono muted task-id">{entry.task_id}</div>
                <Caveats caveats={entry.result.trust.caveats} />
              </td>
              <td className="col-optional muted">
                {entry.slo ? outcomeHeading(curriculum, entry.slo) : "—"}
              </td>
              <td className="col-score">
                <ScoreBar
                  score={entry.result.mean_score}
                  note={
                    entry.result.mean_score === null
                      ? entry.result.trust.confidence_label
                      : `${entry.result.scored_count}/${entry.result.sample_count} samples`
                  }
                />
              </td>
              <td className="col-optional">
                <div className="stacked-badges">
                  <TrustBadge trust={entry.result.trust} />
                  <ConfidenceMeter trust={entry.result.trust} />
                </div>
              </td>
              <td>
                <Link href={`/runs/${entry.result.run_id}`}>See the proof ▸</Link>
                <div className="muted task-id">
                  {formatTimestamp(entry.result.measured_at)}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function ModelReportPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  const modelKey = decodeURIComponent(key);

  const board = await getLeaderboard();
  const rollup = findRollup(board, modelKey);
  // A key with no rows is not an empty report card — it is a URL for a model
  // this benchmark has never run. Saying "not found" is the honest answer.
  if (!rollup) notFound();

  const rows = rollupByOutcome(rollup, board);
  const outcomeCount = board.curriculum.available
    ? board.curriculum.outcomes.length
    : board.slos.length;

  return (
    <>
      <Link href="/leaderboard" className="back">
        ← All models
      </Link>

      <ReportHead rollup={rollup} outcomeCount={outcomeCount} />

      {/* ⚠ THE ORIENTATION SITS BELOW THE HEADLINE FIGURE, NOT ABOVE IT. A
          reader arriving here clicked a model's name; the number they came for
          must not be pushed under a paragraph explaining what numbers are. */}
      <HowToRead title={`How to read ${rollup.display_name}'s report card.`}>
        <ReadStep n={1} heading="One model, everything we know about it">
          The figure at the top is this model&rsquo;s{" "}
          <Term id="overall-score">overall score</Term> across every piece of
          work it has been measured on. The two tables below break that one
          number apart — first by{" "}
          <Term id="learning-outcome">learning outcome</Term>, then by
          individual <Term id="task">task</Term>.
        </ReadStep>
        <ReadStep n={2} heading="The empty rows are the honest part">
          Every outcome your programme publishes gets a row here, including the
          ones this model has never been run against and the two that a written
          test cannot measure at all. Those read{" "}
          <Term id="not-measured">not measured yet</Term>. A report card showing
          only the rows with data would be a highlight reel.
        </ReadStep>
        <ReadStep n={3} heading="Check the evidence column before you trust a row">
          <Term id="verifiable">Checked by a program</Term> is stronger evidence
          than <Term id="judged">marked by another AI</Term>, and the{" "}
          <Term id="confidence">confidence</Term> beside each score says how much
          weight it can bear.
        </ReadStep>
      </HowToRead>

      <GlossaryPanel terms={REPORT_CARD_TERMS} />

      <section className="panel">
        <div className="panel-head">
          <h2>
            Across the {outcomeCount} learning outcome
            {outcomeCount === 1 ? "" : "s"}
          </h2>
          <p className="muted panel-note">
            Every <Term id="learning-outcome">outcome</Term>
            {board.curriculum.program ? ` ${board.curriculum.program} publishes` : " the programme publishes"} gets a row,
            including the ones this model has never been measured against. An
            outcome with no data says so — it is never shown as a zero.
            {!board.curriculum.available
              ? ` ${board.curriculum.unavailable_reason ?? ""}`
              : ""}
          </p>
        </div>
        <div className="table-scroll">
          <table className="outcome-table">
            <thead>
              <tr>
                <th>Outcome</th>
                <th className="col-score">Score</th>
                <th className="num col-optional">Tasks</th>
                <th className="col-optional">Confidence</th>
                <th>Receipt</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <OutcomeRow key={row.slo ?? "unfiled"} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Task by task</h2>
          <p className="muted panel-note">
            The {rollup.entries.length} <Term id="task">task</Term>
            {rollup.entries.length === 1 ? "" : "s"} this model has been run
            against, best first. &ldquo;Evidence&rdquo; says whether a program{" "}
            <Term id="verifiable">checked</Term> the answer or another AI{" "}
            <Term id="judged">marked</Term> it, and &ldquo;Receipt&rdquo; opens
            the <Term id="run">full record</Term> behind the score.
          </p>
        </div>
        <TaskBreakdown rollup={rollup} curriculum={board.curriculum} />
      </section>
    </>
  );
}
