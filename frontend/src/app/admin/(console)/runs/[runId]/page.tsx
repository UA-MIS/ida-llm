import Link from "next/link";

import { LoadError } from "@/components/admin/load-error";
import { AutoRefresh, CancelButton, StatusBadge, TranscriptButton } from "@/components/admin/run-bits";
import { adminGet } from "@/lib/admin/api";
import { TERMINAL_STATUSES, formatUsd, formatWhen, safeDecode } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { AdminRunDetail } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

/**
 * ⚠ UNREDACTED. Scorer explanations (which quote the gold answer), per-sample
 * errors and full transcripts are shown here, deliberately: this page exists
 * to debug runs. It is safe only behind `requireAdmin()`, and it does not
 * import `lib/redact` because there is nothing to hide from an admin.
 */
export default async function AdminRunPage({ params }: { params: Promise<{ runId: string }> }) {
  const runId = safeDecode((await params).runId);
  const here = `/admin/runs/${encodeURIComponent(runId)}`;
  const admin = await requireAdmin(here);
  let detail: AdminRunDetail;
  try {
    detail = await adminGet<AdminRunDetail>(`/admin/runs/${encodeURIComponent(runId)}`, getActor(admin));
  } catch (error) {
    return <LoadError error={error} retryHref={here} />;
  }
  const { run, results } = detail;
  const live = !TERMINAL_STATUSES.includes(run.status);
  return (
    <>
      <Link href={run.sweep_id ? `/admin/sweeps/${encodeURIComponent(run.sweep_id)}` : "/admin/runs"} className="back">
        ← {run.sweep_id ? "Back to the launch" : "Runs"}
      </Link>
      <h1>
        {run.model_key} on <span className="mono">{run.task_id}</span>
      </h1>
      <p>
        <StatusBadge status={run.status} />
        {run.cancel_requested_at && live ? <span className="adm-hint"> Stopping after the current question…</span> : null}
      </p>
      <AutoRefresh active={live} />
      <dl className="adm-dl">
        <dt>Run id</dt>
        <dd className="mono">{run.id}</dd>
        <dt>Questions</dt>
        <dd>
          {run.scored_count} scored of {run.sample_count}
          {run.error_count ? `, ${run.error_count} failed` : ""}
        </dd>
        <dt>Mean score</dt>
        <dd>{run.mean_score === null ? "—" : `${(run.mean_score * 100).toFixed(1)}%`}</dd>
        <dt>Cost</dt>
        <dd>{formatUsd(run.total_cost_usd, 4)}</dd>
        <dt>Launched</dt>
        <dd>
          {formatWhen(run.created_at)}
          {run.launched_by ? ` by @${run.launched_by}` : ""}
        </dd>
        <dt>Finished</dt>
        <dd>{formatWhen(run.finished_at)}</dd>
        {run.label ? (
          <>
            <dt>Label</dt>
            <dd>{run.label}</dd>
          </>
        ) : null}
        <dt>Config revision</dt>
        <dd>{run.config_revision ?? "—"}</dd>
        {run.error ? (
          <>
            <dt>Error</dt>
            <dd className="mono">{run.error}</dd>
          </>
        ) : null}
      </dl>
      {live ? (
        <div className="adm-actions">
          <CancelButton kind="run" id={run.id} />
        </div>
      ) : null}

      <h2>
        Answers ({results.length}
        {detail.results_total > results.length ? ` of ${detail.results_total}` : ""})
      </h2>
      {results.length ? (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th scope="col">Question</th>
                <th scope="col" className="num">
                  Score
                </th>
                <th scope="col">Marking</th>
                <th scope="col" className="num">
                  Cost
                </th>
                <th scope="col">Transcript</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.sample_id}</td>
                  <td className="num">
                    {r.error ? <span className="adm-badge adm-badge-bad">error</span> : r.score ? `${Math.round(r.score.value * 100)}%` : <span className="muted">not scored</span>}
                  </td>
                  <td style={{ maxWidth: "30rem" }}>
                    {r.error ? <span className="mono">{r.error}</span> : r.score?.explanation ?? <span className="muted">—</span>}
                  </td>
                  <td className="num">{formatUsd(r.cost_usd, 4)}</td>
                  <td>{r.transcript_uri ? <TranscriptButton runId={run.id} sampleId={r.sample_id} /> : <span className="muted">none</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="adm-hint">{live ? "No answers yet." : "This run recorded no answers."}</p>
      )}
    </>
  );
}
