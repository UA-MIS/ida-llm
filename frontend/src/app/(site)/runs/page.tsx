import Link from "next/link";

import { GlossaryPanel, Term } from "@/components/glossary";
import { HowToRead, ReadStep } from "@/components/how-to-read";
import { listRuns } from "@/lib/api";
import { RUNS_TERMS } from "@/lib/glossary";
import {
  formatCost,
  formatDuration,
  formatScore,
  formatTimestamp,
  shortSha,
} from "@/lib/format";
import type { RunRecord } from "@/lib/types";

/** Runs change while you watch them, so never statically render this page. */
export const dynamic = "force-dynamic";

function StatusBadge({ status }: { status: RunRecord["status"] }) {
  return <span className={`badge badge-${status}`}>{status}</span>;
}

/**
 * Mean score cell.
 *
 * `null` means "not scored", which is NOT the same as a score of zero. But it
 * also does not mean one single thing: a subjective run has no score because
 * the judge is unimplemented, and a run whose calls all failed has none because
 * nothing was measured. The tooltip must not guess — it reads `error_count`,
 * which the API populates precisely so this can be told apart.
 */
function ScoreCell({ run }: { run: RunRecord }) {
  if (run.mean_score === null) {
    const reason =
      run.error_count > 0 || run.status === "failed"
        ? `not scored — ${run.error_count || run.sample_count} sample(s) failed`
        : run.status === "succeeded" && run.sample_count > 0
          ? "not yet scorable — this task needs LLM-as-judge grading"
          : "not scored";
    return (
      <span className="muted" title={reason}>
        —
      </span>
    );
  }
  return (
    <>
      {formatScore(run.mean_score)}{" "}
      <span className="muted">
        ({run.scored_count}/{run.sample_count})
      </span>
      {run.error_count > 0 ? (
        <div
          className="muted"
          style={{ fontSize: "0.75rem" }}
          title={`${run.error_count} sample(s) errored and are excluded from this mean`}
        >
          {run.error_count} failed
        </div>
      ) : null}
    </>
  );
}

/**
 * The raw run log — every benchmark run, newest first.
 *
 * This is the "show me the data" drill-down, deliberately NOT the front door.
 * The front door is `/`, which leads with the task ("can it grade my
 * quizzes?"); a professor who wants the underlying runs comes here, and a
 * teammate debugging a sweep starts here.
 */
export default async function RunsPage() {
  const { runs } = await listRuns(50);

  if (runs.length === 0) {
    return (
      <>
        <p className="subtitle">Every benchmark run, newest first.</p>
        <div className="empty">
          <p>No runs yet.</p>
          <p className="muted">
            Start one with:
            <br />
            <code className="mono">
              curl -X POST localhost:8000/runs -H &apos;content-type:
              application/json&apos; -d &apos;
              {`{"task_ids":["demo/arithmetic-quiz-check"],"model_keys":["mock"]}`}
              &apos;
            </code>
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      <p className="subtitle">
        {runs.length} most recent benchmark <Term id="run">run</Term>
        {runs.length === 1 ? "" : "s"}. This is the raw log — for results by
        task, start at <Link href="/leaderboard">the leaderboard</Link>.
      </p>

      {/* ⚠ THE ONE PAGE WHERE THE HONEST ORIENTATION IS "YOU PROBABLY WANTED
          THE OTHER PAGE". This is the engineering log, and it is reachable in
          one click from the front door. Telling a professor who landed here by
          accident that they have not broken anything, and where to go instead,
          costs four lines and saves the visit. */}
      <HowToRead title="This is the raw log. You may want the leaderboard instead.">
        <ReadStep n={1} heading="One line per run">
          A <Term id="run">run</Term> is one recorded sitting: one{" "}
          <Term id="model">model</Term>, one <Term id="task">piece of work</Term>,
          every attempt kept on file. This page lists them newest first, exactly
          as they happened, including the ones that failed.
        </ReadStep>
        <ReadStep n={2} heading="It is deliberately technical">
          The columns are here so a result can be audited — down to the version
          of the task file that ran. Nothing is hidden from you, but nothing is
          summarised for you either.
        </ReadStep>
        <ReadStep n={3} heading="For an answer rather than a log">
          <Link href="/leaderboard">The leaderboard</Link> ranks the models in
          plain language, and{" "}
          <Link href="/recommend">the recommendation questions</Link> ask about
          your situation and tell you what to use.
        </ReadStep>
      </HowToRead>

      <GlossaryPanel terms={RUNS_TERMS} />

      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Task</th>
            <th>Model</th>
            <th className="num">Mean score</th>
            <th className="num" title="Roughly three quarters of a word each — the unit outside services bill by.">
              Tokens
            </th>
            <th className="num">Cost</th>
            <th className="num">Duration</th>
            <th>Task SHA</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>
                <StatusBadge status={run.status} />
              </td>
              <td>
                <Link href={`/runs/${run.id}`}>{run.task_id}</Link>
                {run.label ? (
                  <div className="muted" style={{ fontSize: "0.8rem" }}>
                    {run.label}
                  </div>
                ) : null}
              </td>
              <td className="mono">{run.model_key}</td>
              <td className="num">
                <ScoreCell run={run} />
              </td>
              <td className="num">
                {run.total_usage.prompt_tokens +
                  run.total_usage.completion_tokens}
              </td>
              <td className="num">{formatCost(run.total_cost_usd)}</td>
              <td className="num">
                {formatDuration(run.started_at, run.finished_at)}
              </td>
              <td className="mono muted" title={run.task_git_sha ?? undefined}>
                {shortSha(run.task_git_sha)}
              </td>
              <td className="muted">{formatTimestamp(run.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
