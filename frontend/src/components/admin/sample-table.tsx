"use client";

/**
 * The questions (samples) in a task: add, edit, delete. Each write goes to
 * the per-sample endpoint with the task's current `version`; the API answers
 * with the whole updated task, which becomes the new local state, so several
 * edits in a row each carry the right version.
 */

import { useState } from "react";

import { adminApi } from "@/lib/admin/client";
import { sampleFieldsOf, sampleFromFields, taskPath, type SampleFields } from "@/lib/admin/tasks";
import type { AdminError, AdminTask, Issue, TaskSample } from "@/lib/admin/types";

import { ConfirmButton } from "./confirm-button";
import { EmptyState, Field, FormError } from "./form-bits";

const FIELD_OF = (path: string): keyof SampleFields | null => {
  const last = path.split(/[.[\]]/).filter(Boolean).pop();
  return last === "id" || last === "input" || last === "target" || last === "metadata" ? last : null;
};

function SampleEditor({
  task,
  sample,
  onSaved,
  onCancel,
}: {
  task: AdminTask;
  sample: TaskSample | null;
  onSaved: (task: AdminTask) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState<SampleFields>(() => sampleFieldsOf(sample));
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [error, setError] = useState<AdminError | null>(null);
  const [unmatched, setUnmatched] = useState<Issue[]>([]);
  const [busy, setBusy] = useState(false);
  const verifiable = task.kind === "verifiable";
  const set = (k: keyof SampleFields, v: string) => setF((p) => ({ ...p, [k]: v }));
  const issue = (k: keyof SampleFields) => (problems[k] ? [{ path: k, message: problems[k]!, severity: "error" as const }] : undefined);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setUnmatched([]);
    const { sample: next, problems: local } = sampleFromFields(f, sample, task.kind);
    setProblems(local);
    if (!next) return;
    setBusy(true);
    const res = sample
      ? await adminApi<AdminTask>("PUT", `/admin/tasks/${taskPath(task.id)}/samples/${encodeURIComponent(sample.id)}`, { body: { sample: next }, version: task.version })
      : await adminApi<AdminTask>("POST", `/admin/tasks/${taskPath(task.id)}/samples`, { body: { sample: next }, version: task.version });
    setBusy(false);
    if (!res.ok) {
      const pinned: Record<string, string> = {};
      const rest: Issue[] = [];
      for (const i of res.error.issues ?? []) {
        const field = FIELD_OF(i.path);
        if (field && i.severity !== "warning") pinned[field] = i.message;
        else rest.push(i);
      }
      setProblems(pinned);
      setUnmatched(rest);
      setError(res.error);
      return;
    }
    onSaved(res.data);
  }

  return (
    <form className="adm-form adm-panel" onSubmit={save} noValidate style={{ maxWidth: "none" }}>
      <h3 style={{ margin: 0 }}>{sample ? `Edit question ${sample.id}` : "Add a question"}</h3>
      <FormError error={error} unmatched={unmatched} />
      <Field id="s-id" label="Question id" hint="Short and unique within this task, e.g. q6." issues={issue("id")}>
        <input id="s-id" className="adm-input" value={f.id} spellCheck={false} onChange={(e) => set("id", e.target.value)} aria-invalid={problems.id ? true : undefined} />
      </Field>
      <Field id="s-input" label="Question" hint="Exactly what the model is asked. Not shown on the public site." issues={issue("input")}>
        <textarea id="s-input" className="adm-textarea" rows={6} value={f.input} onChange={(e) => set("input", e.target.value)} aria-invalid={problems.input ? true : undefined} />
      </Field>
      <Field
        id="s-target"
        label={verifiable ? "Correct answer" : "Reference answer (optional)"}
        hint={verifiable ? "Used to mark the model's answer automatically. Never shown on the public site." : "Not shown on the public site."}
        issues={issue("target")}
      >
        <input id="s-target" className="adm-input" value={f.target} onChange={(e) => set("target", e.target.value)} aria-invalid={problems.target ? true : undefined} />
      </Field>
      <Field id="s-metadata" label="Extra details (optional, advanced)" hint='A JSON object, e.g. {"skill": "addition"}. Never put the answer here.' issues={issue("metadata")}>
        <textarea id="s-metadata" className="adm-textarea mono" rows={3} value={f.metadata} spellCheck={false} onChange={(e) => set("metadata", e.target.value)} aria-invalid={problems.metadata ? true : undefined} />
      </Field>
      <div className="adm-actions" style={{ margin: 0 }}>
        <button type="submit" className="adm-btn adm-btn-primary" disabled={busy}>
          {busy ? "Saving…" : sample ? "Save question" : "Add question"}
        </button>
        <button type="button" className="adm-btn adm-btn-quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

const preview = (s: string, n = 140) => (s.length > n ? `${s.slice(0, n)}…` : s);

export function SampleTable({ task, onChange }: { task: AdminTask; onChange: (task: AdminTask) => void }) {
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const samples = task.document.samples ?? [];
  const verifiable = task.kind === "verifiable";
  const archived = task.archived_at !== null && task.archived_at !== undefined;

  return (
    <>
      {samples.length ? (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th scope="col">Id</th>
                <th scope="col">Question</th>
                {verifiable ? <th scope="col">Correct answer</th> : null}
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {samples.map((s) => (
                <tr key={s.id}>
                  <td className="mono">{s.id}</td>
                  <td style={{ whiteSpace: "pre-wrap" }}>{preview(String(s.input ?? ""))}</td>
                  {verifiable ? <td className="mono">{String(s.target ?? "")}</td> : null}
                  <td className="adm-cell-actions">
                    <span className="adm-actions" style={{ margin: 0, justifyContent: "flex-end" }}>
                      <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" disabled={archived} onClick={() => setEditing(s.id)}>
                        Edit
                      </button>
                      <ConfirmButton
                        small
                        label="Delete"
                        disabled={archived || samples.length <= 1}
                        title={`Delete question ${s.id}?`}
                        body={<p>The question is removed from this task. Results already recorded for it are kept.</p>}
                        confirmLabel="Delete question"
                        onConfirm={async () => {
                          const res = await adminApi<AdminTask>("DELETE", `/admin/tasks/${taskPath(task.id)}/samples/${encodeURIComponent(s.id)}`, {
                            version: task.version,
                          });
                          if (!res.ok) return res.error.message;
                          onChange(res.data);
                        }}
                      />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {samples.length <= 1 ? <p className="adm-hint">A task needs at least one question, so the last one cannot be deleted.</p> : null}
        </div>
      ) : (
        <EmptyState title="No questions yet" />
      )}
      {editing && editing !== "new" ? (
        <SampleEditor
          key={`${editing}:${task.version}`}
          task={task}
          sample={samples.find((s) => s.id === editing) ?? null}
          onSaved={(t) => {
            setEditing(null);
            onChange(t);
          }}
          onCancel={() => setEditing(null)}
        />
      ) : null}
      {editing === "new" ? (
        <SampleEditor
          key={`new:${task.version}`}
          task={task}
          sample={null}
          onSaved={(t) => {
            setEditing(null);
            onChange(t);
          }}
          onCancel={() => setEditing(null)}
        />
      ) : (
        <div className="adm-actions">
          <button type="button" className="adm-btn adm-btn-secondary" disabled={archived} onClick={() => setEditing("new")}>
            Add a question
          </button>
        </div>
      )}
    </>
  );
}
