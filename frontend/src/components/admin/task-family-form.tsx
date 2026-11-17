"use client";

/**
 * Create or edit a task family (a group of related tasks sharing an id
 * prefix). Title and description are shown on the public site.
 *
 * ⚠ `private` IS BLOCKED until the API reports `tasks_spec_gated: true`
 * (design R10 / PR B6). Before B6, a task's prompts are still readable by any
 * in-cluster caller of `GET /tasks/{id}`, so material that must never leave
 * the university cannot honestly be called private yet.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi, partitionIssues } from "@/lib/admin/client";
import type { AdminError, Issue, TaskFamily } from "@/lib/admin/types";

import { ConfirmButton } from "./confirm-button";
import { Field, FormError } from "./form-bits";

const KEY_RE = /^[a-z0-9][a-z0-9-]*$/;
/** Static segments under /admin/material that a family key would be shadowed by. */
const RESERVED = ["families", "tasks", "upload"];

export function TaskFamilyForm({ family, privateAllowed }: { family: TaskFamily | null; privateAllowed: boolean }) {
  const router = useRouter();
  const creating = family === null;
  const [key, setKey] = useState(family?.key ?? "");
  const [title, setTitle] = useState(family?.title ?? "");
  const [description, setDescription] = useState(family?.description ?? "");
  const [provenance, setProvenance] = useState<"synthetic" | "private">(family?.provenance ?? "synthetic");
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const { byField, other } = partitionIssues(issues, ["key", "title", "description", "provenance"]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const local: Issue[] = [];
    if (creating && !KEY_RE.test(key)) local.push({ path: "key", message: "Use lowercase letters, digits and dashes, e.g. mis200-databases.", severity: "error" });
    if (creating && RESERVED.includes(key)) local.push({ path: "key", message: `“${key}” is reserved by the console. Choose another id.`, severity: "error" });
    if (!title.trim()) local.push({ path: "title", message: "Give the family a title.", severity: "error" });
    if (provenance === "private" && !privateAllowed) local.push({ path: "provenance", message: "Private material cannot be stored yet (see the note below).", severity: "error" });
    setIssues(local);
    if (local.length) return;
    setBusy(true);
    const body = { title: title.trim(), description, provenance };
    const res = creating
      ? await adminApi<TaskFamily>("POST", "/admin/task-families", { body: { key, ...body } })
      : await adminApi<TaskFamily>("PUT", `/admin/task-families/${encodeURIComponent(family.key)}`, { body, version: family.version });
    setBusy(false);
    if (!res.ok) {
      setIssues(res.error.issues ?? []);
      setError(res.error);
      return;
    }
    if (creating) router.push(`/admin/material/${encodeURIComponent(res.data.key)}?created=1`);
    else {
      // Re-keyed by version on the family page: the page shows the notice.
      router.replace(`/admin/material/${encodeURIComponent(family.key)}?saved=1`);
      router.refresh();
    }
  }

  return (
    <form className="adm-form" onSubmit={submit} noValidate>
      <FormError error={error} unmatched={other} />
      <Field id="tf-title" label="Title" isPublic hint="e.g. “MIS 200: database concepts”." issues={byField.title}>
        <input id="tf-title" className="adm-input" value={title} onChange={(e) => setTitle(e.target.value)} aria-invalid={byField.title ? true : undefined} />
      </Field>
      <Field
        id="tf-key"
        label="Short id"
        hint={creating ? "Permanent: every task id in this family starts with it." : "Permanent: task ids in this family start with it."}
        issues={byField.key}
      >
        <input id="tf-key" className="adm-input" value={key} readOnly={!creating} spellCheck={false} onChange={(e) => setKey(e.target.value)} aria-invalid={byField.key ? true : undefined} />
      </Field>
      <Field id="tf-description" label="Description" isPublic hint="One or two sentences on what this family measures." issues={byField.description}>
        <textarea id="tf-description" className="adm-textarea" value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <fieldset className="adm-fieldset">
        <legend>Where the material comes from</legend>
        <label className="adm-check">
          <input type="radio" name="provenance" checked={provenance === "synthetic"} onChange={() => setProvenance("synthetic")} />
          <span>
            <strong>Written for this benchmark</strong>
            <span className="adm-hint">Synthetic questions that may be shared publicly.</span>
          </span>
        </label>
        <label className={`adm-check ${privateAllowed ? "" : "is-disabled"}`}>
          <input
            type="radio"
            name="provenance"
            checked={provenance === "private"}
            disabled={!privateAllowed && provenance !== "private"}
            onChange={() => setProvenance("private")}
          />
          <span>
            <strong>Private (for example, real exam questions)</strong>
            <span className="adm-hint">
              {privateAllowed
                ? "Never exported or shown outside the admin console."
                : "Not available yet: the extra protection that keeps private questions out of every public path has not been switched on. Until it is, add only material you would be comfortable publishing."}
            </span>
          </span>
        </label>
        {byField.provenance?.map((i, n) => (
          <p key={n} className="adm-field-error" role="alert">
            {i.message}
          </p>
        ))}
      </fieldset>
      <div className="adm-actions">
        <button type="submit" className="adm-btn adm-btn-primary" disabled={busy}>
          {busy ? "Saving…" : creating ? "Create family" : "Save changes"}
        </button>
        <Link href={creating ? "/admin/material" : `/admin/material/${encodeURIComponent(family.key)}`} className="adm-btn adm-btn-quiet">
          Cancel
        </Link>
      </div>
      {family && family.archived_at === null ? (
        <div className="adm-actions">
          <ConfirmButton
            label="Archive this family"
            title={`Archive “${family.title}”?`}
            body={
              <p>
                It and its {family.task_count} task{family.task_count === 1 ? "" : "s"} leave the public site. Past results stay
                on record. A family that a class or unit still uses cannot be archived: remove it there first.
              </p>
            }
            confirmLabel="Archive family"
            typeToConfirm={family.key}
            onConfirm={async () => {
              const res = await adminApi("DELETE", `/admin/task-families/${encodeURIComponent(family.key)}`, { version: family.version });
              if (!res.ok) return res.error.message;
              router.push("/admin/material?archived=done");
              router.refresh();
            }}
          />
        </div>
      ) : null}
    </form>
  );
}
