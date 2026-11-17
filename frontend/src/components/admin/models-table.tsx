"use client";

/**
 * The models list: order, quick on/off and hide toggles, and links to edit.
 * Every change is saved immediately with the row's `version`, then the page
 * re-reads from the server so the versions stay current.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi } from "@/lib/admin/client";
import { formatUsd } from "@/lib/admin/format";
import type { AdminModel, ModelFamily } from "@/lib/admin/types";

function keySource(m: AdminModel) {
  if (m.uses === "none") return <span className="adm-badge adm-badge-neutral">No key needed</span>;
  const label = m.uses === "credential" ? `Stored key: ${m.credential_ref}` : `Server setting: ${m.api_key_env}`;
  return (
    <span>
      {label}{" "}
      {m.key_present ? (
        <span className="adm-badge adm-badge-ok">ready</span>
      ) : (
        <span className="adm-badge adm-badge-bad" title="The key is not available, so runs against this model will fail.">
          missing
        </span>
      )}
    </span>
  );
}

export function ModelsTable({ models, families }: { models: AdminModel[]; families: ModelFamily[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const familyName = new Map(families.map((f) => [f.key, f.display_name]));
  const active = models.filter((m) => m.archived_at === null);

  async function patch(m: AdminModel, body: Partial<Pick<AdminModel, "enabled" | "hidden">>) {
    setBusy(m.key);
    setError(null);
    const res = await adminApi("PATCH", `/admin/models/${encodeURIComponent(m.key)}`, { body, version: m.version });
    setBusy(null);
    if (!res.ok) setError(`${m.display_name}: ${res.error.message}`);
    router.refresh();
  }

  async function move(index: number, delta: -1 | 1) {
    const order = active.map((m) => m.key);
    const target = index + delta;
    if (target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target]!, order[index]!];
    setBusy("reorder");
    setError(null);
    const res = await adminApi("POST", "/admin/models/reorder", { body: { order } });
    setBusy(null);
    if (!res.ok) setError(res.error.message);
    router.refresh();
  }

  return (
    <>
      {error ? (
        <div className="adm-panel adm-panel-error" role="alert">
          {error}
        </div>
      ) : null}
      <div className="adm-table-wrap">
        <table className="adm-table">
          <thead>
            <tr>
              <th scope="col">Order</th>
              <th scope="col">Model</th>
              <th scope="col">Family</th>
              <th scope="col">Enabled</th>
              <th scope="col">On public site</th>
              <th scope="col" className="num">
                Price in / out
              </th>
              <th scope="col">API key</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => {
              const index = active.indexOf(m);
              const archived = m.archived_at !== null;
              return (
                <tr key={m.key} className={archived ? "is-muted" : undefined}>
                  <td>
                    {archived ? (
                      <span className="adm-badge adm-badge-neutral">archived</span>
                    ) : (
                      <span className="adm-actions" style={{ margin: 0, gap: "0.25rem" }}>
                        <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" aria-label={`Move ${m.display_name} up`} disabled={busy !== null || index === 0} onClick={() => move(index, -1)}>
                          ↑
                        </button>
                        <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" aria-label={`Move ${m.display_name} down`} disabled={busy !== null || index === active.length - 1} onClick={() => move(index, 1)}>
                          ↓
                        </button>
                      </span>
                    )}
                  </td>
                  <td>
                    <strong>{m.display_name}</strong>
                    <div className="mono muted">{m.key}</div>
                  </td>
                  <td>{m.family_key ? familyName.get(m.family_key) ?? m.family_key : <span className="muted">—</span>}</td>
                  <td>
                    <input
                      type="checkbox"
                      checked={m.enabled}
                      disabled={archived || busy !== null}
                      aria-label={`${m.display_name} enabled`}
                      onChange={(e) => patch(m, { enabled: e.target.checked })}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={!m.hidden}
                      disabled={archived || busy !== null}
                      aria-label={`Show ${m.display_name} on the public site`}
                      onChange={(e) => patch(m, { hidden: !e.target.checked })}
                    />
                  </td>
                  <td className="num">
                    {formatUsd(m.cost.input_usd_per_mtok)} / {formatUsd(m.cost.output_usd_per_mtok)}
                  </td>
                  <td>{keySource(m)}</td>
                  <td className="adm-cell-actions">
                    <Link href={`/admin/models/${encodeURIComponent(m.key)}`} className="adm-btn adm-btn-quiet adm-btn-small">
                      {archived ? "View" : "Edit"}
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
