import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError, getRun, getTask } from "@/lib/api";
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
import { FACET_CAPTION, groupSamples, type SampleGroup } from "@/lib/samples";
import type { ResultRecord, RunRecord, ServingConfig } from "@/lib/types";
import { SAMPLE_FACET_LABEL, sampleFacets } from "@/lib/trust";
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
      {/* ⚠ `<h2>`, NOT `<h3>`. This card and the "Samples" section below it are
          the only two sections on this page, and this one renders first — an
          `<h3>` here with no preceding `<h2>` on the page was the only `<h3>`
          before the only `<h2>`, an inversion heading navigation cannot make
          sense of. */}
      <h2 style={{ fontSize: "0.95rem", marginTop: 0 }}>Serving configuration</h2>
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
          <dd className="mono">
            <Link href={`/models/${encodeURIComponent(run.model_key)}`}>
              {run.model_key}
            </Link>
          </dd>
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

/**
 * The per-sample drill-down, from the sample's own authored `metadata`.
 *
 * Results group by the TASK's `tags`; a single sample is drilled into through
 * its un-prefixed `metadata` (`slo`, `use_mode`, `skill`, `provenance`). The
 * task validator requires the two spellings to agree, so a reader moving from
 * the outcome heading on the results page down to one sample here never meets a
 * contradiction — and `skill` is the part that only exists at this level, which
 * is what makes the drill-down worth taking.
 */
function SampleFacets({ metadata }: { metadata: Record<string, unknown> | undefined }) {
  const facets = sampleFacets(metadata);
  if (facets.length === 0) return null;
  return (
    <div className="sample-facets">
      {facets.map(([key, value]) => (
        <span key={key} className="badge badge-tag" title={SAMPLE_FACET_LABEL[key] ?? key}>
          {SAMPLE_FACET_LABEL[key] ?? key}: <span className="mono">{value}</span>
        </span>
      ))}
    </div>
  );
}

function ResultRow({
  result,
  metadata,
}: {
  result: ResultRecord;
  metadata: Record<string, unknown> | undefined;
}) {
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
          <SampleFacets metadata={metadata} />
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

/**
 * One group of samples, collapsible, with its own mean.
 *
 * ⚠ WHY `<details>` AND NOT A CLIENT COMPONENT. The whole run view is server-
 * rendered and the transcripts inside it already carry the only client JS on the
 * page. A native disclosure keeps the collapse working before hydration, keeps
 * it keyboard-accessible for free, and keeps Ctrl-F over a closed group working
 * in the browsers that support it — none of which a `useState` toggle would.
 */
function SampleGroupSection({
  group,
  metadata,
  defaultOpen,
}: {
  group: SampleGroup;
  metadata: Record<string, Record<string, unknown>>;
  defaultOpen: boolean;
}) {
  return (
    <details className="sample-group" open={defaultOpen}>
      <summary className="sample-group-head">
        <span className="sample-group-name">{group.label}</span>
        <span className="sample-group-stats muted">
          {group.mean_score === null ? (
            /* Null is not zero: a group nothing scored has no mean, and a 0.00
               here would read as "every answer was wrong". */
            <span>no score</span>
          ) : (
            <span className="sample-group-mean">
              mean {formatScore(group.mean_score)}
            </span>
          )}
          <span>
            {group.scored_count}/{group.sample_count} scored
          </span>
          {group.error_count > 0 ? (
            <span style={{ color: "var(--fail)" }}>
              {group.error_count} errored
            </span>
          ) : null}
        </span>
      </summary>
      <div className="table-scroll">
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
            {group.results.map((result) => (
              <ResultRow
                key={result.id}
                result={result}
                metadata={metadata[result.sample_id]}
              />
            ))}
          </tbody>
        </table>
      </div>
    </details>
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

  // The task spec, for each sample's authored metadata. Best-effort: a run can
  // outlive the task file that produced it (an id is never reused for different
  // content, but a family can be removed), and losing the drill-down labels must
  // never take down the page that shows the actual results.
  let sampleMetadata: Record<string, Record<string, unknown>> = {};
  try {
    const task = await getTask(run.task_id);
    sampleMetadata = Object.fromEntries(
      task.samples.map((sample) => [sample.id, sample.metadata]),
    );
  } catch {
    sampleMetadata = {};
  }
  // Classified from the taxonomy and the failure signal, never from score
  // nullity -- see lib/outcome.ts for what that mistake produced.
  const outcome = classifyRun(run, results);

  // A run is one task x one model, so grouping by learning outcome would yield
  // exactly one group. groupSamples picks the finest facet that actually splits
  // THIS run -- normally the sample's own `skill` -- and says which it used.
  const grouped = groupSamples(results, sampleMetadata);

  return (
    <>
      <Link href="/" className="back">
        ← Back to the grid
      </Link>
      {/* A bare UUID told the reader nothing about what they had opened. The
          id stays — it is the thing to quote when reporting a problem — but it
          is now labelled, and the task and model are links rather than dead
          monospace text one page short of the evidence behind them. */}
      <p className="subtitle">
        The full record behind one measurement.{" "}
        <span className="mono muted">{run.id}</span>
      </p>

      <RunSummary run={run} />

      {run.error ? (
        <div className="notice notice-error">
          <strong>Run failed:</strong> <span className="mono">{run.error}</span>
        </div>
      ) : null}

      {outcome === "all-errored" ? (
        <div className="notice notice-error">
          <strong>Nothing was measured.</strong> Every attempt to reach the
          model failed, so this run produced no answers to mark. The scores
          below are missing because there was nothing to mark — not because the
          model did badly, and not because this work cannot be graded.
        </div>
      ) : null}

      {outcome === "partial" ? (
        <div className="notice">
          <strong>Only part of this finished.</strong> {run.error_count} of{" "}
          {run.sample_count} attempt{run.sample_count === 1 ? "" : "s"} failed
          before producing an answer. Any score above covers only the{" "}
          {run.scored_count} attempt{run.scored_count === 1 ? "" : "s"} that
          completed — the failed ones are left out rather than counted as zero,
          so the number describes part of the work, not all of it.
        </div>
      ) : null}

      {/* ⚠ THIS PAGE IS THE PROOF, AND PROOF A READER CANNOT PARSE IS NOT
          PROOF. Every "See the proof" link on the site lands here, so it is the
          page a sceptical professor reaches at exactly the moment they have
          decided to check us. This notice used to carry three pieces of
          internal vocabulary in one sentence ("LLM-as-judge", "defined as an
          interface", "the walking skeleton"). The facts below are the same
          ones; only the vocabulary changed. */}
      {outcome === "not-yet-scorable" ? (
        <div className="notice">
          <strong>Not marked yet.</strong> This piece of work has no single
          right answer, so a second AI has to mark it against a written guide —
          and no marker is switched on in this deployment. The model was still
          asked, and everything it wrote was kept, so this can be marked later
          without re-running anything. That is why there is no score above, and
          it is not a score of zero.
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

      <section className="panel">
        <div className="panel-head">
          <h2>Samples</h2>
          <p className="muted panel-note">
            {results.length === 0
              ? "No results yet."
              : grouped.facet
                ? `${results.length} samples, grouped by ${FACET_CAPTION[grouped.facet]} — the axis that actually varies inside one run. Each group shows the mean over the samples that produced a score; errored samples are counted beside it, never folded in as zeros.`
                : `${results.length} sample${results.length === 1 ? "" : "s"}. Nothing in this task's metadata splits them into groups, so they are listed as one set.`}
          </p>
        </div>
        {results.length > 0
          ? grouped.groups.map((group, index) => (
              <SampleGroupSection
                key={group.key}
                group={group}
                metadata={sampleMetadata}
                /* Open the first group so the page is never a wall of closed
                   rows, and open any group with a failure in it — a hidden
                   error is an error nobody fixes. */
                defaultOpen={index === 0 || group.error_count > 0 || grouped.groups.length === 1}
              />
            ))
          : null}
      </section>
    </>
  );
}
