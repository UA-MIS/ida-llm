import { LoadError } from "@/components/admin/load-error";
import { adminGet } from "@/lib/admin/api";
import { formatUsd, formatWhen } from "@/lib/admin/format";
import { getActor, requireAdmin } from "@/lib/admin/session";
import type { SystemInfo } from "@/lib/admin/types";

export const dynamic = "force-dynamic";

function list(values: string[]): string {
  return values.length ? values.join(", ") : "None";
}

export default async function SystemPage() {
  const admin = await requireAdmin("/admin/system");
  let s: SystemInfo;
  try {
    s = await adminGet<SystemInfo>("/admin/system", getActor(admin));
  } catch (error) {
    return (
      <>
        <h1>System</h1>
        <LoadError error={error} retryHref="/admin/system" />
      </>
    );
  }
  return (
    <>
      <h1>System</h1>
      <p className="adm-lede">Read-only settings that operators control. You cannot change these here.</p>
      <dl className="adm-dl">
        <dt>Settings source</dt>
        <dd>{s.config_source === "db" ? "Database (edited in this console)" : "YAML files in the repository"}</dd>
        <dt>Current revision</dt>
        <dd>
          {s.revision ?? "—"}
          {s.revision_at ? <span className="muted"> · {formatWhen(s.revision_at)}</span> : null}
        </dd>
        <dt>Most runs per launch</dt>
        <dd>{s.guards.sweep_max_runs}</dd>
        <dt>Most samples per launch</dt>
        <dd>{s.guards.sweep_max_samples}</dd>
        <dt>Estimated cost needing typed confirmation</dt>
        <dd>Above {formatUsd(s.guards.admin_run_max_estimated_usd)}</dd>
        <dt>Model tags that always need confirmation</dt>
        <dd>{list(s.guards.sweep_exclude_tags)}</dd>
        <dt>Model tags hidden from the public site</dt>
        <dd>{list(s.guards.public_hide_tags)}</dd>
        <dt>Judge model</dt>
        <dd>{s.judge_model_key ?? "None configured"}</dd>
        <dt>Stored API keys can be used</dt>
        <dd>
          {s.kek_configured ? `Yes (encryption key ${s.kek_active_id ?? "?"})` : "No: the encryption key is not configured, so new API keys cannot be saved"}
        </dd>
        {s.admin_group_hint ? (
          <>
            <dt>Who can sign in</dt>
            <dd>{s.admin_group_hint}</dd>
          </>
        ) : null}
      </dl>
    </>
  );
}
