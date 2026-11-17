"use client";

/**
 * One task, three ways in: a form for the common fields, the whole document
 * as YAML for everything else (rubrics, normalisation, …), and the question
 * list. All three edit the same stored document (design AD-8) and run the
 * same server-side validation.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi, partitionIssues } from "@/lib/admin/client";
import { formatWhen } from "@/lib/admin/format";
import { applyDetails, detailsOf, taskPath, type TaskDetails } from "@/lib/admin/tasks";
import type { AdminError, AdminTask, Issue, UploadResult, ValidateResult } from "@/lib/admin/types";
import { toYaml } from "@/lib/admin/yaml";

import { ConfirmButton } from "./confirm-button";
import { Field, FormError, IssuesList } from "./form-bits";
import { SampleTable } from "./sample-table";

type Tab = "details" | "yaml" | "samples";

const DETAIL_FIELDS = ["title", "description", "domain", "system_prompt", "scorer.tolerance", "scorer", "tags"];

function DetailsForm({ task, onSaved }: { task: AdminTask; onSaved: (t: AdminTask, message?: string) => void }) {
  const [d, setD] = useState<TaskDetails>(() => detailsOf(task.document));
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof TaskDetails, v: string) => setD((p) => ({ ...p, [k]: v }));
  const { byField, other } = partitionIssues(issues, DETAIL_FIELDS);
  const verifiable = task.kind === "verifiable";

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const local: Issue[] = [];
    if (!d.title.trim()) local.push({ path: "title", message: "Give the task a title.", severity: "error" });
    if (d.scorer_kind === "numeric_match" && d.tolerance.trim() && !Number.isFinite(Number(d.tolerance))) {
      local.push({ path: "scorer.tolerance", message: "Enter a number, e.g. 0.01.", severity: "error" });
    }
    setIssues(local);
    if (local.length) return;
    setBusy(true);
    const res = await adminApi<AdminTask>("PUT", `/admin/tasks/${taskPath(task.id)}`, {
      body: { document: applyDetails(task.document, d) },
      version: task.version,
    });
    setBusy(false);
    if (!res.ok) {
      setIssues(res.error.issues ?? []);
      setError(res.error);
      return;
    }
    // Saving bumps the version, which remounts this form with the saved
    // document; the confirmation therefore lives in the parent.
    onSaved(res.data, "Saved.");
  }

  return (
    <form className="adm-form" onSubmit={save} noValidate>
      <FormError error={error} unmatched={other} />
      <Field id="t-title" label="Title" isPublic issues={byField.title}>
        <input id="t-title" className="adm-input" value={d.title} onChange={(e) => set("title", e.target.value)} aria-invalid={byField.title ? true : undefined} />
      </Field>
      <Field id="t-description" label="Description (for authors)" issues={byField.description}>
        <textarea id="t-description" className="adm-textarea" rows={4} value={d.description} onChange={(e) => set("description", e.target.value)} />
      </Field>
      <Field id="t-domain" label="Subject area" hint="e.g. statistics, assessment" issues={byField.domain}>
        <input id="t-domain" className="adm-input" value={d.domain} onChange={(e) => set("domain", e.target.value)} />
      </Field>
      <Field id="t-system_prompt" label="Instructions to the model" hint="Include the answer format you expect. Not shown on the public site." issues={byField.system_prompt}>
        <textarea id="t-system_prompt" className="adm-textarea" rows={6} value={d.system_prompt} onChange={(e) => set("system_prompt", e.target.value)} />
      </Field>
      {verifiable ? (
        <div className="adm-field-row">
          <Field id="t-scorer" label="How answers are checked" issues={byField.scorer}>
            <select id="t-scorer" className="adm-select" value={d.scorer_kind} onChange={(e) => set("scorer_kind", e.target.value)}>
              <option value="exact_match">Text must match exactly</option>
              <option value="numeric_match">Number must match (within a tolerance)</option>
            </select>
          </Field>
          {d.scorer_kind === "numeric_match" ? (
            <Field id="t-tolerance" label="Tolerance" hint="How far off still counts as correct, e.g. 0.01." issues={byField["scorer.tolerance"]}>
              <input id="t-tolerance" className="adm-input" inputMode="decimal" value={d.tolerance} onChange={(e) => set("tolerance", e.target.value)} aria-invalid={byField["scorer.tolerance"] ? true : undefined} />
            </Field>
          ) : null}
        </div>
      ) : (
        <p className="adm-hint">Answers to this task are marked by a judge model against its rubric. Edit the rubric in the YAML tab.</p>
      )}
      <Field id="t-tags" label="Tags" hint="Comma-separated. Keep the family name as a tag." issues={byField.tags}>
        <input id="t-tags" className="adm-input" value={d.tags} onChange={(e) => set("tags", e.target.value)} />
      </Field>
      <div className="adm-actions">
        <button type="submit" className="adm-btn adm-btn-primary" disabled={busy || !!task.archived_at}>
          {busy ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

export async function uploadMaterial(content: Blob, filename: string, mode: "create" | "replace", commit: boolean) {
  const form = new FormData();
  form.append("file", content, filename);
  form.append("mode", mode);
  form.append("commit", commit ? "true" : "false");
  return adminApi<UploadResult>("POST", "/admin/material/upload", { form });
}

function YamlTab({ task, onSaved }: { task: AdminTask; onSaved: (t: AdminTask, message?: string) => void }) {
  const router = useRouter();
  const [text, setText] = useState(() => toYaml(task.document));
  const [check, setCheck] = useState<ValidateResult | null>(null);
  const [preview, setPreview] = useState<UploadResult | null>(null);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const file = () => new Blob([text], { type: "application/yaml" });

  async function validate() {
    setBusy(true);
    setError(null);
    setPreview(null);
    const res = await adminApi<ValidateResult>("POST", "/admin/tasks/validate", { body: { yaml: text } });
    setBusy(false);
    if (!res.ok) return setError(res.error);
    setCheck(res.data);
  }

  async function previewSave() {
    setBusy(true);
    setError(null);
    setCheck(null);
    const res = await uploadMaterial(file(), `${task.id.split("/").pop()}.yaml`, "replace", false);
    setBusy(false);
    if (!res.ok) return setError(res.error);
    setPreview(res.data);
  }

  return (
    <div className="adm-form" style={{ maxWidth: "none" }}>
      <p className="adm-hint">
        The whole task as YAML, in the format described in <span className="mono">tasks/SCHEMA.md</span>. Use this for rubrics
        and other details the form does not show. Comments are not kept.
      </p>
      <label className="sr-only" htmlFor="t-yaml">
        Task YAML
      </label>
      <textarea
        id="t-yaml"
        className="adm-textarea adm-code"
        value={text}
        spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          setCheck(null);
          setPreview(null);
        }}
      />
      <FormError error={error} unmatched={error?.issues ?? []} />
      {check ? (
        check.ok ? (
          <div className="adm-panel adm-panel-ok" role="status">
            This YAML is valid: {check.sample_count ?? "?"} question{check.sample_count === 1 ? "" : "s"}.
            {check.issues.length ? <IssuesList issues={check.issues} /> : null}
          </div>
        ) : (
          <IssuesList issues={check.issues} title="This YAML has problems:" />
        )
      ) : null}
      {preview ? (
        preview.ok ? (
          <div className="adm-panel adm-panel-ok" role="status">
            <p style={{ marginTop: 0 }}>
              Ready to save. {preview.diff ? `${preview.diff.samples_added} question(s) added, ${preview.diff.samples_changed} changed, ${preview.diff.samples_removed} removed.` : null}
            </p>
            {preview.issues.length ? <IssuesList issues={preview.issues} /> : null}
            <ConfirmButton
              danger={false}
              label="Save this YAML"
              title="Replace this task with the YAML?"
              body={<p>The task is replaced by what is in the editor. The previous version is kept in the history.</p>}
              confirmLabel="Replace task"
              onConfirm={async () => {
                const res = await uploadMaterial(file(), `${task.id.split("/").pop()}.yaml`, "replace", true);
                if (!res.ok) return res.error.message;
                if (!res.data.ok) {
                  setPreview(res.data);
                  return "The file did not pass validation.";
                }
                const fresh = await adminApi<AdminTask>("GET", `/admin/tasks/${taskPath(task.id)}`);
                if (fresh.ok) onSaved(fresh.data, "The task was replaced with your YAML.");
                setPreview(null);
                router.refresh();
              }}
            />
          </div>
        ) : (
          <IssuesList issues={preview.issues} title="This YAML has problems:" />
        )
      ) : null}
      <div className="adm-actions">
        <button type="button" className="adm-btn adm-btn-secondary" onClick={validate} disabled={busy}>
          Check for problems
        </button>
        <button type="button" className="adm-btn adm-btn-primary" onClick={previewSave} disabled={busy || !!task.archived_at}>
          Review and save…
        </button>
        <button
          type="button"
          className="adm-btn adm-btn-quiet"
          onClick={() => {
            setText(toYaml(task.document));
            setCheck(null);
            setPreview(null);
          }}
        >
          Undo my edits
        </button>
      </div>
    </div>
  );
}

export function TaskEditor({ task: initial }: { task: AdminTask }) {
  const router = useRouter();
  const [task, setTask] = useState(initial);
  const [tab, setTab] = useState<Tab>("details");
  const [flash, setFlash] = useState<string | null>(null);
  const tabs: { id: Tab; label: string }[] = [
    { id: "details", label: "Details" },
    { id: "samples", label: `Questions (${task.document.samples?.length ?? 0})` },
    { id: "yaml", label: "YAML" },
  ];
  const update = (t: AdminTask, message?: string) => {
    setTask(t);
    setFlash(message ?? null);
  };

  return (
    <>
      <p className="adm-lede">
        <span className="mono">{task.id}</span> · {task.kind === "verifiable" ? "checked automatically" : "marked by a judge model"} ·
        last changed {task.updated_by ? `by @${task.updated_by} ` : ""}
        {formatWhen(task.updated_at)}
      </p>
      {task.issues.length ? <IssuesList issues={task.issues} /> : null}
      {flash ? (
        <p role="status" className="adm-panel adm-panel-ok">
          {flash}
        </p>
      ) : null}
      <div className="adm-tabs" role="tablist" aria-label="Task editor">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            className="adm-tab"
            onClick={() => {
              setTab(t.id);
              setFlash(null);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "details" ? <DetailsForm key={task.version} task={task} onSaved={update} /> : null}
        {tab === "samples" ? <SampleTable task={task} onChange={update} /> : null}
        {tab === "yaml" ? <YamlTab key={task.version} task={task} onSaved={update} /> : null}
      </div>
      {!task.archived_at ? (
        <div className="adm-actions" style={{ marginTop: "2rem" }}>
          <ConfirmButton
            label="Archive this task"
            title={`Archive “${task.title}”?`}
            body={<p>The task leaves the public site and no new runs use it. Past results, and the exact text they were measured on, are kept.</p>}
            confirmLabel="Archive task"
            typeToConfirm={task.id.split("/").pop()}
            onConfirm={async () => {
              const res = await adminApi("DELETE", `/admin/tasks/${taskPath(task.id)}`, { version: task.version });
              if (!res.ok) return res.error.message;
              router.push(`/admin/material/${encodeURIComponent(task.family_key)}?archived=done`);
              router.refresh();
            }}
          />
        </div>
      ) : (
        <p className="adm-panel adm-panel-warn">This task is archived. It is kept for the record and can no longer be edited.</p>
      )}
    </>
  );
}
