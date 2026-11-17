import Link from "next/link";

import { EmptyState } from "@/components/admin/form-bits";
import { LoadError } from "@/components/admin/load-error";
import { StatusBadge } from "@/components/admin/run-bits";
import { adminGet } from "@/lib/admin/api";
import { formatUsd, formatWhen } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { AdminRunList, SweepList } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

const STATUSES = ["queued", "running", "succeeded", "partial", "failed", "cancelled"];

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; model_key?: string; launched_by?: string; cursor?: string; sweeps_cursor?: string }>;
}) {
  const admin = await requireAdmin("/admin/runs");
  const actor = getActor(admin);
  const sp = await searchParams;
  const q = new URLSearchParams({ limit: "50" });
  if (sp.status && STATUSES.includes(sp.status)) q.set("status", sp.status);
  if (sp.model_key) q.set("model_key", sp.model_key);
  if (sp.launched_by) q.set("launched_by", sp.launched_by);
  if (sp.cursor) q.set("cursor", sp.cursor);
  const sq = new URLSearchParams({ limit: "20" });
  if (sp.sweeps_cursor) sq.set("cursor", sp.sweeps_cursor);
  let sweeps: SweepList;
  let runs: AdminRunList;
  try {
    [sweeps, runs] = await Promise.all([adminGet<SweepList>(`/admin/sweeps?${sq}`, actor), adminGet<AdminRunList>(`/admin/runs?${q}`, actor)]);
  } catch (error) {
    return (
      <>
        <h1>Runs</h1>
        <LoadError error={error} retryHref="/admin/runs" />
      </>
    );
  }
  const filtered = !!(sp.status || sp.model_key || sp.launched_by);
  const nextRuns = new URLSearchParams({ ...(sp as Record<string, string>), cursor: runs.next_cursor ?? "" });
  const nextSweeps = new URLSearchParams({ ...(sp as Record<string, string>), sweeps_cursor: sweeps.next_cursor ?? "" });

  return (
    <>
      <h1>Runs</h1>
      <p className="adm-lede">A run asks one model every question in one task. Each launch creates a group of runs.</p>
      <div className="adm-toolbar">
        <Link href="/admin/runs/new" className="adm-btn adm-btn-primary">
          Launch runs
        </Link>
      </div>

      <h2>Launches</h2>
      {sweeps.sweeps.length ? (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th scope="col">Launched</th>
                <th scope="col">By</th>
                <th scope="col">Label</th>
                <th scope="col">Progress</th>
                <th scope="col" className="num">
                  Cost so far
                </th>
              </tr>
            </thead>
            <tbody>
              {sweeps.sweeps.map((s) => (
                <tr key={s.sweep_id}>
                  <td>
                    <Link href={`/admin/sweeps/${encodeURIComponent(s.sweep_id)}`}>{formatWhen(s.created_at)}</Link>
                  </td>
                  <td>{s.launched_by ? `@${s.launched_by}` : <span className="muted">automatic</span>}</td>
                  <td>{s.label ?? <span className="muted">—</span>}</td>
                  <td>
                    {s.run_count} run{s.run_count === 1 ? "" : "s"}:{" "}
                    {Object.entries(s.by_status)
                      .filter(([, n]) => n)
                      .map(([status, n]) => (
                        <span key={status} style={{ marginRight: "0.35rem" }}>
                          <StatusBadge status={status} /> {n}
                        </span>
                      ))}
                  </td>
                  <td className="num">{formatUsd(s.total_cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {sweeps.next_cursor ? <Link href={`/admin/runs?${nextSweeps}`}>Older launches →</Link> : null}
        </div>
      ) : (
        <EmptyState title="No launches yet">
          <p>Use “Launch runs” to measure models on your course material.</p>
        </EmptyState>
      )}

      <h2>Individual runs</h2>
      <form method="get" className="adm-actions" aria-label="Filter runs">
        <label className="adm-label" htmlFor="f-status">
          Status
        </label>
        <select id="f-status" name="status" defaultValue={sp.status ?? ""} className="adm-select" style={{ width: "auto" }}>
          <option value="">Any</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <label className="adm-label" htmlFor="f-model">
          Model id
        </label>
        <input id="f-model" name="model_key" defaultValue={sp.model_key ?? ""} className="adm-input" style={{ width: "12rem" }} />
        <label className="adm-label" htmlFor="f-by">
          Launched by
        </label>
        <input id="f-by" name="launched_by" defaultValue={sp.launched_by ?? ""} className="adm-input" style={{ width: "10rem" }} />
        <button type="submit" className="adm-btn adm-btn-secondary">
          Filter
        </button>
        {filtered ? (
          <Link href="/admin/runs" className="adm-btn adm-btn-quiet">
            Clear
          </Link>
        ) : null}
      </form>
      {runs.runs.length ? (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Status</th>
                <th scope="col">Model</th>
                <th scope="col">Task</th>
                <th scope="col" className="num">
                  Score
                </th>
                <th scope="col" className="num">
                  Cost
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.runs.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link href={`/admin/runs/${encodeURIComponent(r.id)}`} className="mono">
                      {r.id}
                    </Link>
                    <div className="muted">{formatWhen(r.created_at)}</div>
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td>{r.model_key}</td>
                  <td className="mono">{r.task_id}</td>
                  <td className="num">{r.mean_score === null ? "—" : `${Math.round(r.mean_score * 100)}%`}</td>
                  <td className="num">{formatUsd(r.total_cost_usd, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs.next_cursor ? <Link href={`/admin/runs?${nextRuns}`}>Older runs →</Link> : null}
        </div>
      ) : (
        <EmptyState title={filtered ? "No runs match these filters" : "No runs yet"} />
      )}
    </>
  );
}
