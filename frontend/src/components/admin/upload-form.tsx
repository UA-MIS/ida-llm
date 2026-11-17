"use client";

/**
 * Upload a task as a YAML file: check it first (nothing is stored), then
 * save. A rejected file is never stored (design §5.4).
 */

import Link from "next/link";
import { useState } from "react";

import { taskPath } from "@/lib/admin/tasks";
import type { AdminError, UploadResult } from "@/lib/admin/types";

import { FormError, IssuesList } from "./form-bits";
import { uploadMaterial } from "./task-editor";

export function UploadForm({ maxBytes }: { maxBytes: number }) {
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"create" | "replace">("create");
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<AdminError | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<UploadResult | null>(null);

  function choose(f: File | null) {
    setResult(null);
    setError(null);
    setSaved(null);
    setProblem(null);
    if (f && !/\.ya?ml$/i.test(f.name)) {
      setProblem("Choose a .yaml or .yml file.");
      setFile(null);
      return;
    }
    if (f && f.size > maxBytes) {
      setProblem(`That file is ${(f.size / 1024).toFixed(0)} KB; the limit is ${(maxBytes / 1024).toFixed(0)} KB.`);
      setFile(null);
      return;
    }
    setFile(f);
  }

  async function send(commit: boolean) {
    if (!file) return setProblem("Choose a file first.");
    setBusy(true);
    setError(null);
    const res = await uploadMaterial(file, file.name, mode, commit);
    setBusy(false);
    if (!res.ok) return setError(res.error);
    if (commit && res.data.ok) {
      setSaved(res.data);
      setResult(null);
    } else setResult(res.data);
  }

  return (
    <div className="adm-form">
      <div className="adm-field">
        <label className="adm-label" htmlFor="up-file">
          Task file
        </label>
        <p className="adm-hint">A single task in the YAML format described in tasks/SCHEMA.md.</p>
        <input id="up-file" type="file" accept=".yaml,.yml" className="adm-input" onChange={(e) => choose(e.target.files?.[0] ?? null)} aria-invalid={problem ? true : undefined} />
        {problem ? (
          <p className="adm-field-error" role="alert">
            {problem}
          </p>
        ) : null}
      </div>
      <fieldset className="adm-fieldset">
        <legend>This file is…</legend>
        <label className="adm-check">
          <input type="radio" name="mode" checked={mode === "create"} onChange={() => { setMode("create"); setResult(null); }} />
          <span>A new task</span>
        </label>
        <label className="adm-check">
          <input type="radio" name="mode" checked={mode === "replace"} onChange={() => { setMode("replace"); setResult(null); }} />
          <span>A new version of an existing task (same id)</span>
        </label>
      </fieldset>
      <FormError error={error} unmatched={error?.issues ?? []} />
      {result ? (
        result.ok ? (
          <div className="adm-panel adm-panel-ok" role="status">
            <h2 className="adm-panel-title">The file looks good</h2>
            <p>
              {result.task ? <><strong>{result.task.title}</strong> (<span className="mono">{result.task.id}</span>), </> : null}
              {result.sample_count ?? "?"} question{result.sample_count === 1 ? "" : "s"}.
              {result.diff ? ` Compared with the current version: ${result.diff.samples_added} added, ${result.diff.samples_changed} changed, ${result.diff.samples_removed} removed.` : ""}
            </p>
            {result.issues.length ? <IssuesList issues={result.issues} /> : null}
            <button type="button" className="adm-btn adm-btn-primary" disabled={busy} onClick={() => send(true)}>
              {busy ? "Saving…" : mode === "create" ? "Save as a new task" : "Replace the task"}
            </button>
          </div>
        ) : (
          <IssuesList issues={result.issues} title="The file has problems. Nothing was saved. Fix these and check again:" />
        )
      ) : null}
      {saved ? (
        <div className="adm-panel adm-panel-ok" role="status">
          <h2 className="adm-panel-title">Saved</h2>
          {saved.task ? (
            <p>
              <Link href={`/admin/material/tasks/${taskPath(saved.task.id)}`}>Open {saved.task.title}</Link>
            </p>
          ) : null}
        </div>
      ) : null}
      <div className="adm-actions">
        <button type="button" className="adm-btn adm-btn-secondary" disabled={busy || !file} onClick={() => send(false)}>
          {busy ? "Checking…" : "Check the file"}
        </button>
        <span className="adm-hint">Checking stores nothing.</span>
      </div>
    </div>
  );
}
