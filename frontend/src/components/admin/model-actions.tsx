"use client";

/** "Test connection" and "Archive" on a model's edit page. */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi } from "@/lib/admin/client";
import type { AdminModel, ModelTestResult } from "@/lib/admin/types";

import { ConfirmButton } from "./confirm-button";

export function ModelActions({ model }: { model: AdminModel }) {
  const router = useRouter();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const path = `/admin/models/${encodeURIComponent(model.key)}`;

  async function test() {
    setTesting(true);
    setResult(null);
    const res = await adminApi<ModelTestResult>("POST", `${path}/test`);
    setTesting(false);
    if (!res.ok) setResult({ ok: false, text: res.error.message });
    else if (res.data.ok) setResult({ ok: true, text: `Connected. The model answered in ${Math.round(res.data.latency_ms)} ms.` });
    else setResult({ ok: false, text: `The model did not answer: ${res.data.error ?? "unknown error"}` });
  }

  return (
    <section className="adm-panel" aria-labelledby="model-actions-title">
      <h2 className="adm-panel-title" id="model-actions-title">
        Check and retire
      </h2>
      <div className="adm-actions">
        <button type="button" className="adm-btn adm-btn-secondary" onClick={test} disabled={testing || model.archived_at !== null}>
          {testing ? "Testing…" : "Test connection"}
        </button>
        <span className="adm-hint">Sends one tiny request. On paid models this costs a fraction of a cent.</span>
      </div>
      {result ? (
        <p role="status" className={result.ok ? "adm-badge adm-badge-ok" : "adm-field-error"}>
          {result.text}
        </p>
      ) : null}
      {model.archived_at === null ? (
        <div className="adm-actions">
          <ConfirmButton
            label="Archive this model"
            title={`Archive ${model.display_name}?`}
            body={
              <p>
                The model disappears from the public site and no new runs can be launched against it. Its past results are kept.
                The id <span className="mono">{model.key}</span> can never be reused.
              </p>
            }
            confirmLabel="Archive model"
            typeToConfirm={model.key}
            onConfirm={async () => {
              const res = await adminApi("DELETE", path, { version: model.version });
              if (!res.ok) return res.error.message;
              router.push("/admin/models?archived=done");
              router.refresh();
            }}
          />
        </div>
      ) : (
        <p className="adm-hint">This model is archived. Its results are kept for the record.</p>
      )}
    </section>
  );
}
