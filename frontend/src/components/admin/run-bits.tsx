"use client";

/** Small pieces shared by the run and sweep pages. */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { adminApi } from "@/lib/admin/client";
import { runStatus } from "@/lib/admin/format";

import { ConfirmButton } from "./confirm-button";

export function StatusBadge({ status }: { status: string }) {
  const s = runStatus(status);
  return <span className={`adm-badge adm-badge-${s.tone}`}>{s.label}</span>;
}

/** Re-reads the page from the server every `seconds` while `active` (e.g. a sweep still running). */
export function AutoRefresh({ active, seconds = 5 }: { active: boolean; seconds?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => router.refresh(), seconds * 1000);
    return () => clearInterval(id);
  }, [active, seconds, router]);
  return active ? (
    <p className="adm-hint" role="status">
      Updating automatically every {seconds} seconds.
    </p>
  ) : null;
}

export function CancelButton({ kind, id, label }: { kind: "run" | "sweep"; id: string; label?: string }) {
  const router = useRouter();
  const path = kind === "run" ? `/admin/runs/${encodeURIComponent(id)}/cancel` : `/admin/sweeps/${encodeURIComponent(id)}/cancel`;
  return (
    <ConfirmButton
      label={label ?? (kind === "run" ? "Cancel this run" : "Cancel all unfinished runs")}
      title={kind === "run" ? "Cancel this run?" : "Cancel every unfinished run in this launch?"}
      body={
        <p>
          Waiting runs are dropped. A run already in progress stops after the question it is on; the answers it has
          already received, and their cost, are kept.
        </p>
      }
      confirmLabel={kind === "run" ? "Cancel run" : "Cancel runs"}
      onConfirm={async () => {
        const res = await adminApi("POST", path);
        if (!res.ok) return res.error.message;
        router.refresh();
      }}
    />
  );
}

/** Loads one sample's full transcript on demand (prompt, answer, raw provider response). */
export function TranscriptButton({ runId, sampleId }: { runId: string; sampleId: string }) {
  const [state, setState] = useState<{ loading: boolean; text?: string; error?: string } | null>(null);
  async function load() {
    if (state?.text) return setState(null);
    setState({ loading: true });
    const res = await adminApi<unknown>("GET", `/admin/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(sampleId)}/transcript`);
    setState(res.ok ? { loading: false, text: JSON.stringify(res.data, null, 2) } : { loading: false, error: res.error.message });
  }
  return (
    <div>
      <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" onClick={load} aria-expanded={!!state?.text}>
        {state?.loading ? "Loading…" : state?.text ? "Hide transcript" : "Show transcript"}
      </button>
      {state?.error ? <p className="adm-field-error">{state.error}</p> : null}
      {state?.text ? <pre style={{ marginTop: "0.5rem", maxHeight: "28rem", overflow: "auto" }}>{state.text}</pre> : null}
    </div>
  );
}
