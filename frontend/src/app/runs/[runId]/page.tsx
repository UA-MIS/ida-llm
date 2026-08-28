import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError, getRun } from "@/lib/api";
import {
  formatCost,
  formatDuration,
  formatLatency,
  formatScore,
  formatTimestamp,
  formatBuildIdentity,
  shortSha,
} from "@/lib/format";
import { classifyRun, classifySample } from "@/lib/outcome";
import type { ResultRecord, RunRecord, ServingConfig } from "@/lib/types";
import { Transcript } from "./transcript";

export const dynamic = "force-dynamic";

/**
 * D-1 rendered.
 *
 * This block is the reason the serving config is copied onto every record: a
 * professor reading a recommendation must be able to see exactly what produced
 * the number, without trusting that `models.yaml` still says what it said the
 * day the run happened.
 */
function ServingConfigCard({ config }: { config: ServingConfig }) {
  return (
    <div className="card">
      <h3>Serving configuration</h3>
      <p className="muted" style={{ fontSize: "0.8rem", marginTop: 0 }}>
        Captured at run time and stored with every result. Editing the registry
        later cannot change what this run reports.
      </p>
      <dl className="grid">
        <div>
          <dt>Model id</dt>
          <dd className="mono">{config.model_id}</dd>
        </div>
        <div>
          <dt>Registry key</dt>
          <dd className="mono">{config.registry_key}</dd>
        </div>
        <div>
          <dt>Serving stack</dt>
          <dd className="mono">
            {config.serving_stack}
            {config.serving_version ? ` · ${config.serving_version}` : ""}
          </dd>
        </div>
        <div>
          <dt>Quantization</dt>
          <dd className="mono">{config.quantization}</dd>
        </div>
        <div>
          <dt>Revision</dt>
          <dd className="mono">{config.revision ?? "—"}</dd>
        </div>
        <div>
          <dt>Context window</dt>
          <dd className="mono">{config.context_window ?? "—"}</dd>
        </div>
        <div>
          <dt>Temperature</dt>
          <dd className="mono">{config.sampling.temperature}</dd>
        </div>
        <div>
          <dt>Top p</dt>
          <dd className="mono">{config.sampling.top_p}</dd>
        </div>
        <div>
          <dt>Max tokens</dt>
          <dd className="mono">{config.sampling.max_tokens}</dd>
        </div>
        <div>
          <dt>Seed</dt>
          <dd className="mono">{config.sampling.seed ?? "—"}</dd>
        </div>
        <div>
          <dt>Hardware</dt>
          <dd className="mono">{config.hardware ?? "—"}</dd>
        </div>
      </dl>
    </div>
  );
}

function RunSummary({ run }: { run: RunRecord }) {
  return (
    <div className="card">
      <dl className="grid">
        <div>
          <dt>Status</dt>
          <dd>
            <span className={`badge badge-${run.status}`}>{run.status}</span>
          </dd>
        </div>
        <div>
          <dt>Task</dt>
          <dd className="mono">{run.task_id}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd className="mono">{run.model_key}</dd>
        </div>
        <div>
          <dt>Mean score</dt>
          <dd>
            {run.mean_score === null ? (
              <span className="muted">
                {run.error_count > 0 || run.status === "failed"
                  ? "nothing measured"
                  : "not scored"}
              </span>
            ) : (
              <>
                {formatScore(run.mean_score)}{" "}
                <span className="muted">
                  ({run.scored_count}/{run.sample_count} samples)
                </span>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Tokens</dt>
          <dd className="mono">
            {run.total_usage.prompt_tokens} in ·{" "}
            {run.total_usage.completion_tokens} out
          </dd>
        </div>
        <div>
          <dt>Cost</dt>
          <dd>{formatCost(run.total_cost_usd)}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>{formatDuration(run.started_at, run.finished_at)}</dd>
        </div>
        <div>
          <dt>Errored samples</dt>
          <dd className={run.error_count > 0 ? "" : "muted"}>
            {run.error_count > 0 ? `${run.error_count} of ${run.sample_count}` : "none"}
          </dd>
        </div>
        <div>
          <dt>Sweep</dt>
          <dd className="mono muted">{run.sweep_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Task git SHA</dt>
          <dd className="mono" title={run.task_git_sha ?? undefined}>
            {shortSha(run.task_git_sha)}
          </dd>
        </div>
        <div>
          <dt>Task content SHA</dt>
          <dd className="mono" title={run.task_content_sha ?? undefined}>
            {shortSha(run.task_content_sha)}
          </dd>
        </div>
        <div>
          <dt>Harness build</dt>
          <dd className="mono" title={run.harness_version}>
            {formatBuildIdentity(run.harness_version)}
          </dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd className="muted">{formatTimestamp(run.created_at)}</dd>
        </div>
      </dl>
    </div>
  );
}

/** One sample's outcome. Distinguishes "failed" from "not yet scorable". */
function OutcomeLabel({ result }: { result: ResultRecord }) {
  const outcome = classifySample(result);
  switch (outcome) {
    case "error":
      return <span style={{ color: "var(--fail)" }}>error</span>;
    case "pass":
      return <span style={{ color: "var(--pass)" }}>pass</span>;
    case "fail":
      return <span style={{ color: "var(--fail)" }}>fail</span>;
    case "not-yet-scorable":
      return (
        <span className="muted" title="subjective task; LLM judge not implemented">
          not yet scorable
        </span>
      );
    default:
      return <span className="muted">not scored</span>;
  }
}

function ResultRow({ result }: { result: ResultRecord }) {
  return (
    <>
      <tr>
        <td className="mono">
          {result.sample_id}
          {result.cached ? (
            <span className="muted" title="served from cache: no cost, no latency">
              {" "}
              (cached)
            </span>
          ) : null}
        </td>
        <td>
          <OutcomeLabel result={result} />
        </td>
        <td className="num">{formatScore(result.score?.value ?? null)}</td>
        <td className="muted" style={{ fontSize: "0.85rem" }}>
          {result.error ?? result.score?.explanation ?? "—"}
          {result.archive_error ? (
            <div style={{ color: "var(--pending)" }}>
              transcript not archived: {result.archive_error}
            </div>
          ) : null}
        </td>
        <td className="num mono">
          {result.usage.prompt_tokens + result.usage.completion_tokens}
        </td>
        <td className="num">{formatLatency(result.latency_ms)}</td>
      </tr>
      {result.transcript_uri ? (
        <tr>
          <td colSpan={6} style={{ paddingTop: 0 }}>
            <Transcript runId={result.run_id} sampleId={result.sample_id} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;

  let detail;
  try {
    detail = await getRun(runId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  const { run, results } = detail;
  // Classified from the taxonomy and the failure signal, never from score
  // nullity -- see lib/outcome.ts for what that mistake produced.
  const outcome = classifyRun(run, results);

  return (
    <>
      <Link href="/runs" className="back">
        ← All runs
      </Link>
      <p className="subtitle mono">{run.id}</p>

      <RunSummary run={run} />

      {run.error ? (
        <div className="notice notice-error">
          <strong>Run failed:</strong> <span className="mono">{run.error}</span>
        </div>
      ) : null}

      {outcome === "all-errored" ? (
        <div className="notice notice-error">
          <strong>No samples completed.</strong> Every call to the model failed,
          so this run measured nothing. The scores below are absent because
          there was nothing to score — not because this task cannot be graded.
          Check that the model endpoint is reachable and re-run.
        </div>
      ) : null}

      {outcome === "partial" ? (
        <div className="notice">
          <strong>Partial run.</strong> {run.error_count} of {run.sample_count}{" "}
          sample(s) failed. Any mean score above is computed over the{" "}
          {run.scored_count} sample(s) that completed — errored samples are
          excluded rather than counted as zero, so this number covers only part
          of the task.
        </div>
      ) : null}

      {outcome === "not-yet-scorable" ? (
        <div className="notice">
          <strong>Not yet scorable.</strong> This is a subjective task: grading
          it needs LLM-as-judge scoring, which is defined as an interface but not
          implemented in the walking skeleton. The model was still called and
          every transcript below was captured, so these samples can be graded
          retroactively once the judge lands.
        </div>
      ) : null}

      {run.serving_config ? (
        <ServingConfigCard config={run.serving_config} />
      ) : (
        <div className="notice">
          No serving configuration recorded yet — this run has not been claimed
          by a runner.
        </div>
      )}

      <h2>Samples</h2>
      {results.length === 0 ? (
        <p className="muted">No results yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Sample</th>
              <th>Outcome</th>
              <th className="num">Score</th>
              <th>Explanation</th>
              <th className="num">Tokens</th>
              <th className="num">Latency</th>
            </tr>
          </thead>
          <tbody>
            {results.map((result) => (
              <ResultRow key={result.id} result={result} />
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
