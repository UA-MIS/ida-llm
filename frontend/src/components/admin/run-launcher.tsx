"use client";

/**
 * Launch benchmark runs: pick models × task families, see a live cost
 * estimate, confirm, launch.
 *
 * ⚠ SPEND GUARDS (design AD-13, §5.6). The estimate is re-requested
 * (debounced) on every change. The hard caps (most runs / questions per
 * launch) are enforced by the API; when the estimate is above the
 * per-launch ceiling, or a chosen model is testing-only, the admin must TYPE
 * the dollar figure before Launch is enabled. A UI should make overspending
 * harder than the command line does, not easier.
 */

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { adminApi } from "@/lib/admin/client";
import { formatUsd } from "@/lib/admin/format";
import type { AdminError, AdminModel, EnqueueResponse, RunEstimate, RunLaunchInput, TaskFamily } from "@/lib/admin/types";

import { EmptyState, FormError } from "./form-bits";

/** The figure the admin types: the estimate rounded UP to the cent, so typing it always covers it. */
export function spendFigure(estimate: number): string {
  return (Math.ceil(estimate * 100 - 1e-9) / 100).toFixed(2);
}

export function ConfirmSpend({ estimate, value, onChange }: { estimate: RunEstimate; value: string; onChange: (v: string) => void }) {
  const figure = spendFigure(estimate.est_usd_high);
  const ok = value.trim().replace(/^\$/, "") === figure;
  return (
    <div className="adm-panel adm-panel-warn" role="group" aria-labelledby="spend-title">
      <h2 className="adm-panel-title" id="spend-title">
        Confirm the spending
      </h2>
      <p>
        This launch could cost up to <strong>${figure}</strong>
        {estimate.est_usd_high > estimate.caps.max_estimated_usd
          ? `, which is more than the ${formatUsd(estimate.caps.max_estimated_usd)} limit for a single launch.`
          : ", and includes a model that always needs confirmation."}{" "}
        Real costs are usually lower.
      </p>
      <div className="adm-field">
        <label className="adm-label" htmlFor="spend-typed">
          Type {figure} to confirm
        </label>
        <input
          id="spend-typed"
          className="adm-input"
          style={{ maxWidth: "12rem" }}
          inputMode="decimal"
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={value && !ok ? true : undefined}
        />
        {value && !ok ? <p className="adm-field-error">Type exactly {figure}.</p> : null}
      </div>
    </div>
  );
}

export function RunLauncher({ models, families }: { models: AdminModel[]; families: TaskFamily[] }) {
  const router = useRouter();
  const usable = useMemo(() => models.filter((m) => m.enabled && !m.archived_at), [models]);
  const [modelKeys, setModelKeys] = useState<string[]>([]);
  const [familyKeys, setFamilyKeys] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [estimate, setEstimate] = useState<RunEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState<AdminError | null>(null);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  const input: RunLaunchInput = { model_keys: modelKeys, family_keys: familyKeys, label: label.trim() || undefined };
  const ready = modelKeys.length > 0 && familyKeys.length > 0;

  useEffect(() => {
    setTyped("");
    setError(null);
    if (!ready) {
      setEstimate(null);
      setEstimateError(null);
      return;
    }
    const mine = ++seq.current;
    setEstimating(true);
    const timer = setTimeout(async () => {
      const res = await adminApi<RunEstimate>("POST", "/admin/runs/estimate", { body: { model_keys: modelKeys, family_keys: familyKeys } });
      if (mine !== seq.current) return; // a newer selection superseded this one
      setEstimating(false);
      if (res.ok) {
        setEstimate(res.data);
        setEstimateError(null);
      } else {
        setEstimate(null);
        setEstimateError(res.error);
      }
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the keys ARE the inputs; arrays are compared by content below
  }, [modelKeys.join(","), familyKeys.join(","), ready]);

  const overCap = !!estimate && (estimate.runs > estimate.caps.max_runs || estimate.samples > estimate.caps.max_samples);
  const confirmed = !estimate?.needs_confirmation || typed.trim().replace(/^\$/, "") === spendFigure(estimate.est_usd_high);
  const canLaunch = ready && !!estimate && !estimating && !overCap && confirmed && !busy;

  const toggle = (list: string[], set: (v: string[]) => void, key: string) => set(list.includes(key) ? list.filter((k) => k !== key) : [...list, key]);

  async function launch() {
    if (!estimate) return;
    setBusy(true);
    setError(null);
    const body: RunLaunchInput = { ...input, confirm_spend_usd: estimate.needs_confirmation ? Number(typed.trim().replace(/^\$/, "")) : undefined };
    const res = await adminApi<EnqueueResponse>("POST", "/admin/runs", { body });
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      // The API's estimate may have moved since ours: take its figure and ask again.
      if (res.error.code === "spend_confirmation_required" && res.error.current) setEstimate(res.error.current as RunEstimate);
      return;
    }
    router.push(`/admin/sweeps/${encodeURIComponent(res.data.sweep_id)}?launched=${res.data.queued}`);
  }

  if (!usable.length) {
    return (
      <EmptyState title="No models are switched on">
        <p>Enable at least one model on the Models page before launching runs.</p>
      </EmptyState>
    );
  }

  return (
    <div className="adm-form" style={{ maxWidth: "60rem" }}>
      <fieldset className="adm-fieldset">
        <legend>1. Models</legend>
        <div className="adm-checklist">
          {usable.map((m) => (
            <label key={m.key} className="adm-check">
              <input type="checkbox" checked={modelKeys.includes(m.key)} onChange={() => toggle(modelKeys, setModelKeys, m.key)} />
              <span>
                {m.display_name}
                {m.tags.includes("testing-only") ? <span className="adm-badge adm-badge-warn"> always confirm</span> : null}
                {!m.key_present && m.uses !== "none" ? <span className="adm-badge adm-badge-bad"> key missing</span> : null}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="adm-fieldset">
        <legend>2. Task families</legend>
        {families.length ? (
          <div className="adm-checklist">
            {families.map((f) => (
              <label key={f.key} className="adm-check">
                <input type="checkbox" checked={familyKeys.includes(f.key)} onChange={() => toggle(familyKeys, setFamilyKeys, f.key)} />
                <span>
                  {f.title} <span className="muted">({f.task_count} tasks, {f.sample_count} questions)</span>
                </span>
              </label>
            ))}
          </div>
        ) : (
          <p className="adm-hint">There are no task families yet.</p>
        )}
      </fieldset>

      <div className="adm-field">
        <label className="adm-label" htmlFor="run-label">
          Label (optional)
        </label>
        <p className="adm-hint">A note to find this launch later, e.g. “November re-run after model update”.</p>
        <input id="run-label" className="adm-input" value={label} onChange={(e) => setLabel(e.target.value)} />
      </div>

      <section aria-live="polite" aria-labelledby="estimate-title">
        <h2 id="estimate-title">3. Estimate</h2>
        {!ready ? <p className="adm-hint">Choose at least one model and one task family to see the estimate.</p> : null}
        {ready && estimating ? <p className="adm-hint">Working out the estimate…</p> : null}
        <FormError error={estimateError} unmatched={estimateError?.issues ?? []} />
        {estimate && !estimating ? (
          <>
            <div className="adm-cards">
              <div className="adm-stat">
                <span className="adm-stat-label">Runs</span>
                <span className="adm-stat-value">{estimate.runs}</span>
                <span className="adm-stat-note">Limit {estimate.caps.max_runs}</span>
              </div>
              <div className="adm-stat">
                <span className="adm-stat-label">Questions asked</span>
                <span className="adm-stat-value">{estimate.samples}</span>
                <span className="adm-stat-note">Limit {estimate.caps.max_samples}</span>
              </div>
              <div className="adm-stat">
                <span className="adm-stat-label">Cost, at most</span>
                <span className="adm-stat-value">{formatUsd(estimate.est_usd_high)}</span>
                <span className="adm-stat-note">{estimate.includes_judge ? "Includes judge-model marking." : "No judge-model marking needed."}</span>
              </div>
            </div>
            {overCap ? (
              <div className="adm-panel adm-panel-error" role="alert">
                This is more than one launch is allowed to do. Choose fewer models or task families.
              </div>
            ) : null}
            {estimate.warnings.length ? (
              <div className="adm-panel adm-panel-warn">
                <ul style={{ margin: 0 }}>
                  {estimate.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <details className="adm-detail">
              <summary>Cost per task and model</summary>
              <div className="adm-table-wrap">
                <table className="adm-table">
                  <thead>
                    <tr>
                      <th scope="col">Task</th>
                      <th scope="col">Model</th>
                      <th scope="col" className="num">
                        Questions
                      </th>
                      <th scope="col" className="num">
                        At most
                      </th>
                      <th scope="col">Based on</th>
                    </tr>
                  </thead>
                  <tbody>
                    {estimate.pairs.map((p) => (
                      <tr key={`${p.task_id}|${p.model_key}`}>
                        <td className="mono">{p.task_id}</td>
                        <td>{p.model_key}</td>
                        <td className="num">{p.samples}</td>
                        <td className="num">{formatUsd(p.est_usd_high, 4)}</td>
                        <td>{p.basis === "history" ? "Recent runs" : "Worst case"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
            {estimate.needs_confirmation && !overCap ? <ConfirmSpend estimate={estimate} value={typed} onChange={setTyped} /> : null}
          </>
        ) : null}
      </section>

      <FormError error={error} unmatched={error?.issues ?? []} />
      <div className="adm-actions">
        <button type="button" className="adm-btn adm-btn-primary" disabled={!canLaunch} onClick={launch}>
          {busy ? "Launching…" : estimate ? `Launch ${estimate.runs} run${estimate.runs === 1 ? "" : "s"}` : "Launch"}
        </button>
      </div>
    </div>
  );
}
