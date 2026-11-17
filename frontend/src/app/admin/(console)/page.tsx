import Link from "next/link";

import { LoadError } from "@/components/admin/load-error";
import { adminGet } from "@/lib/admin/api";
import { formatWhen } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { SystemInfo } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

export default async function AdminDashboard() {
  const admin = await requireAdmin("/admin");
  let system: SystemInfo;
  try {
    system = await adminGet<SystemInfo>("/admin/system", getActor(admin));
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

      <p>
        <Link href="/admin/system">See all system settings</Link>
      </p>
    </>
  );
}
