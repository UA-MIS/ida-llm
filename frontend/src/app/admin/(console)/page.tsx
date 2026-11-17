import Link from "next/link";

import { AuditTable } from "@/components/admin/audit-table";
import { LoadError } from "@/components/admin/load-error";
import { StatusBadge } from "@/components/admin/run-bits";
import { adminGet } from "@/lib/admin/api";
import { formatWhen } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { AdminRunList, AuditList, SystemInfo } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function AdminDashboard() {
  const admin = await requireAdmin("/admin");
  const actor = getActor(admin);
  let system: SystemInfo;
  let running: AdminRunList | null;
  let audit: AuditList | null;
  try {
    // The overview degrades gracefully: runs and the log are extras.
    [system, running, audit] = await Promise.all([
      adminGet<SystemInfo>("/admin/system", actor),
      adminGet<AdminRunList>("/admin/runs?status=running&limit=10", actor).catch(() => null),
      adminGet<AuditList>("/admin/audit?limit=10", actor).catch(() => null),
    ]);
  } catch (error) {
    return (
      <>
        <h1>Admin console</h1>
        <LoadError error={error} retryHref="/admin" />
      </>
    );
  }

  return (
    <>
      <h1>Admin console</h1>
      <p className="adm-lede">
        Manage the models, course material and classes the public site shows. Changes you save here appear on the
        public site within a few seconds.
      </p>

      <section className="adm-cards" aria-label="Status">
        <div className="adm-stat">
          <span className="adm-stat-label">Settings come from</span>
          <span className="adm-stat-value">{system.config_source === "db" ? "This console" : "Files in the code repository"}</span>
          {system.config_source !== "db" ? (
            <span className="adm-stat-note">Edits made here will not reach the public site until an operator switches this environment over.</span>
          ) : null}
        </div>
        <div className="adm-stat">
          <span className="adm-stat-label">Last change</span>
          <span className="adm-stat-value">{system.revision === null ? "None yet" : `Revision ${system.revision}`}</span>
          {system.revision_at ? <span className="adm-stat-note">{formatWhen(system.revision_at)}</span> : null}
        </div>
        <div className="adm-stat">
          <span className="adm-stat-label">Spending limit per launch</span>
          <span className="adm-stat-value">${system.guards.admin_run_max_estimated_usd.toFixed(2)}</span>
          <span className="adm-stat-note">Launches estimated above this need you to type the amount to confirm.</span>
        </div>
      </section>

      <h2>Running now</h2>
      {running === null ? (
        <p className="adm-hint">Run information is not available yet.</p>
      ) : running.runs.length ? (
        <ul>
          {running.runs.map((r) => (
            <li key={r.id}>
              <StatusBadge status={r.status} /> <Link href={`/admin/runs/${encodeURIComponent(r.id)}`}>{r.model_key}</Link> on{" "}
              <span className="mono">{r.task_id}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="adm-hint">
          Nothing is running. <Link href="/admin/runs/new">Launch runs</Link>
        </p>
      )}

      <h2>Recent activity</h2>
      {audit === null ? (
        <p className="adm-hint">The activity log is not available yet.</p>
      ) : audit.entries.length ? (
        <>
          <AuditTable entries={audit.entries} compact />
          <Link href="/admin/audit">See the full activity log</Link>
        </>
      ) : (
        <p className="adm-hint">No changes have been made yet.</p>
      )}

      <p>
        <Link href="/admin/system">See all system settings</Link>
      </p>
    </>
  );
}
