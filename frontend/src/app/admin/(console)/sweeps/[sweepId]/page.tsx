import Link from "next/link";

import { LoadError } from "@/components/admin/load-error";
import { AutoRefresh, CancelButton, StatusBadge } from "@/components/admin/run-bits";
import { adminGet } from "@/lib/admin/api";
import { TERMINAL_STATUSES, formatUsd, formatWhen, safeDecode } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { SweepDetail } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function SweepPage({ params, searchParams }: { params: Promise<{ sweepId: string }>; searchParams: Promise<{ launched?: string }> }) {
  const sweepId = safeDecode((await params).sweepId);
  const here = `/admin/sweeps/${encodeURIComponent(sweepId)}`;
  const admin = await requireAdmin(here);
  const launched = (await searchParams).launched;
  let detail: SweepDetail;
  try {
    detail = await adminGet<SweepDetail>(`/admin/sweeps/${encodeURIComponent(sweepId)}`, getActor(admin));
  } catch (error) {
    return <LoadError error={error} retryHref={here} />;
  }
  const { summary, runs } = detail;
  const live = runs.some((r) => !TERMINAL_STATUSES.includes(r.status));
  return (
    <>
      <Link href="/admin/runs" className="back">
        ← Runs
      </Link>
      <h1>{summary.label ?? "Launch"}</h1>
      <p className="adm-lede">
        {formatWhen(summary.created_at)}
        {summary.launched_by ? ` by @${summary.launched_by}` : ""} · {summary.run_count} runs · {formatUsd(summary.total_cost_usd)} spent so far
      </p>
      {launched ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Launched {launched} run{launched === "1" ? "" : "s"}. They start as soon as a worker is free; this page updates by itself.
        </p>
      ) : null}
      <AutoRefresh active={live} />
      {live ? (
        <div className="adm-actions">
          <CancelButton kind="sweep" id={summary.sweep_id} />
        </div>
      ) : null}
      <div className="adm-table-wrap">
        <table className="adm-table">
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Task</th>
              <th scope="col">Status</th>
              <th scope="col" className="num">
                Score
              </th>
              <th scope="col" className="num">
                Cost
              </th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link href={`/admin/runs/${encodeURIComponent(r.id)}`}>{r.model_key}</Link>
                </td>
                <td className="mono">{r.task_id}</td>
                <td>
                  <StatusBadge status={r.status} />
                </td>
                <td className="num">{r.mean_score === null ? "—" : `${Math.round(r.mean_score * 100)}%`}</td>
                <td className="num">{formatUsd(r.total_cost_usd, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
