"use client";

/** Create a task in a family: the common fields plus its first question. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi } from "@/lib/admin/client";
import { TASK_NAME_RE, newTaskDocument, taskPath, type NewTask } from "@/lib/admin/tasks";
import type { AdminError, AdminTask, Issue } from "@/lib/admin/types";

import { Field, FormError } from "./form-bits";

/** Where an API issue path belongs in this form. */
function fieldFor(path: string): keyof NewTask | null {
  if (path === "id") return "name";
  if (/^samples(\[0\]|\.0)\.id$/.test(path)) return "sample_id";
  if (/^samples(\[0\]|\.0)\.input$/.test(path)) return "sample_input";
  if (/^samples(\[0\]|\.0)\.target$/.test(path)) return "sample_target";
  if (path.startsWith("rubric")) return "rubric_description";
  if (path === "scorer.tolerance") return "tolerance";
  const top = path.split(/[.[]/)[0] as keyof NewTask;
  return ["title", "description", "domain", "system_prompt", "tags"].includes(top) ? top : null;
}

export function NewTaskForm({ family, familyTitle }: { family: string; familyTitle: string }) {
  const router = useRouter();
  const [t, setT] = useState<NewTask>({
    family,
    name: "",
    kind: "verifiable",
    title: "",
    description: "",
    domain: "",
    system_prompt: "",
    scorer_kind: "exact_match",
    tolerance: "",
    tags: family,
    rubric_description: "",
    sample_id: "q1",
    sample_input: "",
    sample_target: "",
  });
  const [problems, setProblems] = useState<Partial<Record<keyof NewTask, string>>>({});
  const [unmatched, setUnmatched] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof NewTask>(k: K, v: NewTask[K]) => setT((p) => ({ ...p, [k]: v }));
  const issue = (k: keyof NewTask) => (problems[k] ? [{ path: k, message: problems[k]!, severity: "error" as const }] : undefined);
  const inv = (k: keyof NewTask) => (problems[k] ? true : undefined);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setUnmatched([]);
    const local: Partial<Record<keyof NewTask, string>> = {};
    if (!TASK_NAME_RE.test(t.name)) local.name = "Use lowercase letters, digits and dashes, e.g. l1-key-terms.";
    if (!t.title.trim()) local.title = "Give the task a title.";
    if (!t.sample_input.trim()) local.sample_input = "Write the first question.";
    if (t.kind === "verifiable" && !t.sample_target.trim()) local.sample_target = "Give the correct answer.";
    if (t.kind === "subjective" && !t.rubric_description.trim()) local.rubric_description = "Describe what a full-marks, half-marks and zero answer looks like.";
    setProblems(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    const res = await adminApi<AdminTask>("POST", "/admin/tasks", { body: { document: newTaskDocument(t) } });
    setBusy(false);
    if (!res.ok) {
      const pinned: Partial<Record<keyof NewTask, string>> = {};
      const rest: Issue[] = [];
      for (const i of res.error.issues ?? []) {
        const f = fieldFor(i.path);
        if (f && !pinned[f] && i.severity !== "warning") pinned[f] = i.message;
        else rest.push(i);
      }
      setProblems(pinned);
      setUnmatched(rest);
      setError(res.error);
      return;
    }
    router.push(`/admin/material/tasks/${taskPath(res.data.id)}?created=1`);
  }

  return (
    <form className="adm-form" onSubmit={submit} noValidate>
      <FormError error={error} unmatched={unmatched} />
      <Field id="nt-title" label="Title" isPublic hint="e.g. “Key terms: definitions”." issues={issue("title")}>
        <input id="nt-title" className="adm-input" value={t.title} onChange={(e) => set("title", e.target.value)} aria-invalid={inv("title")} />
      </Field>
      <Field id="nt-name" label="Short id" hint={<>Permanent. The task&apos;s full id will be <span className="mono">{family}/{t.name || "…"}</span>.</>} issues={issue("name")}>
        <input id="nt-name" className="adm-input" value={t.name} spellCheck={false} onChange={(e) => set("name", e.target.value)} aria-invalid={inv("name")} />
      </Field>
      <fieldset className="adm-fieldset">
        <legend>How answers are marked</legend>
        <label className="adm-check">
          <input type="radio" name="kind" checked={t.kind === "verifiable"} onChange={() => set("kind", "verifiable")} />
          <span>
            <strong>Checked automatically</strong>
            <span className="adm-hint">Each question has one correct answer (a word, phrase or number).</span>
          </span>
        </label>
        <label className="adm-check">
          <input type="radio" name="kind" checked={t.kind === "subjective"} onChange={() => set("kind", "subjective")} />
          <span>
            <strong>Marked by a judge model against a rubric</strong>
            <span className="adm-hint">For written answers with no single right answer.</span>
          </span>
        </label>
        {t.kind === "verifiable" ? (
          <div className="adm-field-row">
            <Field id="nt-scorer" label="Matching">
              <select id="nt-scorer" className="adm-select" value={t.scorer_kind} onChange={(e) => set("scorer_kind", e.target.value)}>
                <option value="exact_match">Text must match exactly</option>
                <option value="numeric_match">Number must match (within a tolerance)</option>
              </select>
            </Field>
            {t.scorer_kind === "numeric_match" ? (
              <Field id="nt-tolerance" label="Tolerance" hint="e.g. 0.01" issues={issue("tolerance")}>
                <input id="nt-tolerance" className="adm-input" inputMode="decimal" value={t.tolerance} onChange={(e) => set("tolerance", e.target.value)} />
              </Field>
            ) : null}
          </div>
        ) : (
          <Field
            id="nt-rubric"
            label="Rubric"
            hint="Say what a 1.0, a 0.5 and a 0.0 answer actually does. You can split this into several weighted criteria later in the YAML tab."
            issues={issue("rubric_description")}
          >
            <textarea id="nt-rubric" className="adm-textarea" rows={6} value={t.rubric_description} onChange={(e) => set("rubric_description", e.target.value)} aria-invalid={inv("rubric_description")} />
          </Field>
        )}
      </fieldset>
      <Field id="nt-system_prompt" label="Instructions to the model (optional)" hint="Include the answer format you expect, e.g. “Answer with a single number on the last line.”" issues={issue("system_prompt")}>
        <textarea id="nt-system_prompt" className="adm-textarea" rows={4} value={t.system_prompt} onChange={(e) => set("system_prompt", e.target.value)} />
      </Field>
      <div className="adm-field-row">
        <Field id="nt-domain" label="Subject area (optional)" issues={issue("domain")}>
          <input id="nt-domain" className="adm-input" value={t.domain} onChange={(e) => set("domain", e.target.value)} />
        </Field>
        <Field id="nt-tags" label="Tags" hint="Comma-separated; the family name is always included." issues={issue("tags")}>
          <input id="nt-tags" className="adm-input" value={t.tags} onChange={(e) => set("tags", e.target.value)} />
        </Field>
      </div>
      <fieldset className="adm-fieldset">
        <legend>First question</legend>
        <p className="adm-hint">You can add more questions after saving. Questions and answers are never shown on the public site.</p>
        <Field id="nt-sample_id" label="Question id" issues={issue("sample_id")}>
          <input id="nt-sample_id" className="adm-input" value={t.sample_id} onChange={(e) => set("sample_id", e.target.value)} aria-invalid={inv("sample_id")} />
        </Field>
        <Field id="nt-sample_input" label="Question" issues={issue("sample_input")}>
          <textarea id="nt-sample_input" className="adm-textarea" rows={5} value={t.sample_input} onChange={(e) => set("sample_input", e.target.value)} aria-invalid={inv("sample_input")} />
        </Field>
        {t.kind === "verifiable" ? (
          <Field id="nt-sample_target" label="Correct answer" issues={issue("sample_target")}>
            <input id="nt-sample_target" className="adm-input" value={t.sample_target} onChange={(e) => set("sample_target", e.target.value)} aria-invalid={inv("sample_target")} />
          </Field>
        ) : null}
      </fieldset>
      <div className="adm-actions">
        <button type="submit" className="adm-btn adm-btn-primary" disabled={busy}>
          {busy ? "Creating…" : "Create task"}
        </button>
        <Link href={`/admin/material/${encodeURIComponent(family)}`} className="adm-btn adm-btn-quiet">
          Cancel
        </Link>
        <span className="adm-hint">In {familyTitle}</span>
      </div>
    </form>
  );
}
