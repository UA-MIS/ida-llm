"use client";

/**
 * The learning-outcomes document (slo.yaml), edited as YAML and validated by
 * the API on save. Validation also re-checks every class against the
 * outcomes, so a change that would leave a class unreachable is refused with
 * the reason.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi } from "@/lib/admin/client";
import type { AdminError, SloDocument } from "@/lib/admin/types";

import { FormError, IssuesList } from "./form-bits";

export function SloEditor({ doc }: { doc: SloDocument }) {
  const router = useRouter();
  const [text, setText] = useState(doc.yaml);
  const [error, setError] = useState<AdminError | null>(null);
  const [warnings, setWarnings] = useState(doc.issues ?? []);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const dirty = text !== doc.yaml;

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    const res = await adminApi<SloDocument>("PUT", "/admin/curriculum/slo", { body: { yaml: text }, version: doc.version });
    setBusy(false);
    if (!res.ok) return setError(res.error);
    setWarnings(res.data.issues ?? []);
    setSaved(true);
    router.refresh();
  }

  return (
    <div className="adm-form" style={{ maxWidth: "none" }}>
      <label className="sr-only" htmlFor="slo-yaml">
        Learning outcomes YAML
      </label>
      <textarea id="slo-yaml" className="adm-textarea adm-code" value={text} spellCheck={false} onChange={(e) => { setText(e.target.value); setSaved(false); }} />
      <FormError error={error} unmatched={error?.issues ?? []} />
      {warnings.length ? <IssuesList issues={warnings} /> : null}
      {saved ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Saved. The public site picks it up within a few seconds.
        </p>
      ) : null}
      <div className="adm-actions">
        <button type="button" className="adm-btn adm-btn-primary" disabled={!dirty || busy} onClick={save}>
          {busy ? "Checking and saving…" : "Save outcomes"}
        </button>
        {dirty ? (
          <button type="button" className="adm-btn adm-btn-quiet" onClick={() => { setText(doc.yaml); setError(null); }}>
            Undo my edits
          </button>
        ) : null}
      </div>
    </div>
  );
}
