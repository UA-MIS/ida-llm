"use client";

/** Create or edit a major (degree programme) and its catalogue details. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi, partitionIssues } from "@/lib/admin/client";
import type { AdminError, AdminMajor, Issue, MajorInput } from "@/lib/admin/types";

import { ConfirmButton } from "./confirm-button";
import { Field, FormError } from "./form-bits";

const ID_RE = /^[a-z0-9][a-z0-9-]*$/;
const FIELDS = ["id", "name", "department", "subject_codes", "display_code", "catalog", "class_source"];

export function MajorForm({ major, nextPosition }: { major: AdminMajor | null; nextPosition: number }) {
  const router = useRouter();
  const creating = major === null;
  const [f, setF] = useState({
    id: major?.id ?? "",
    name: major?.name ?? "",
    department: major?.department ?? "",
    subject_codes: (major?.subject_codes ?? []).join(", "),
    display_code: major?.display_code ?? "",
    catalog: major?.catalog ?? "",
    class_source: major?.class_source ?? "catalog",
  });
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f, v: string) => setF((p) => ({ ...p, [k]: v }));
  const { byField, other } = partitionIssues(issues, FIELDS);
  const inv = (k: string) => (byField[k] ? true : undefined);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const local: Issue[] = [];
    if (creating && !ID_RE.test(f.id)) local.push({ path: "id", message: "Use lowercase letters, digits and dashes, e.g. mis.", severity: "error" });
    if (!f.name.trim()) local.push({ path: "name", message: "Give the major a name.", severity: "error" });
    setIssues(local);
    if (local.length) return;
    const body: MajorInput = {
      id: creating ? f.id : major.id,
      name: f.name.trim(),
      department: f.department.trim(),
      subject_codes: f.subject_codes.split(",").map((c) => c.trim().toUpperCase()).filter(Boolean),
      display_code: f.display_code.trim() || null,
      catalog: f.catalog.trim() || null,
      class_source: f.class_source.trim() || "catalog",
      position: major?.position ?? nextPosition,
    };
    setBusy(true);
    const res = creating
      ? await adminApi<AdminMajor>("POST", "/admin/majors", { body })
      : await adminApi<AdminMajor>("PUT", `/admin/majors/${encodeURIComponent(major.id)}`, { body, version: major.version });
    setBusy(false);
    if (!res.ok) {
      setIssues(res.error.issues ?? []);
      setError(res.error);
      return;
    }
    router.replace(`/admin/classes/majors/${encodeURIComponent(res.data.id)}?saved=1`);
    router.refresh();
  }

  return (
    <form className="adm-form" onSubmit={submit} noValidate>
      <FormError error={error} unmatched={other} />
      <Field id="mj-name" label="Name" isPublic hint="e.g. Management Information Systems" issues={byField.name}>
        <input id="mj-name" className="adm-input" value={f.name} onChange={(e) => set("name", e.target.value)} aria-invalid={inv("name")} />
      </Field>
      <div className="adm-field-row">
        <Field id="mj-id" label="Short id" hint={creating ? "Permanent, used in links, e.g. mis." : "Permanent."} issues={byField.id}>
          <input id="mj-id" className="adm-input" value={f.id} readOnly={!creating} spellCheck={false} onChange={(e) => set("id", e.target.value)} aria-invalid={inv("id")} />
        </Field>
        <Field id="mj-display_code" label="Short label (optional)" isPublic hint="e.g. MIS" issues={byField.display_code}>
          <input id="mj-display_code" className="adm-input" value={f.display_code} onChange={(e) => set("display_code", e.target.value)} />
        </Field>
      </div>
      <Field id="mj-department" label="Department" isPublic issues={byField.department}>
        <input id="mj-department" className="adm-input" value={f.department} onChange={(e) => set("department", e.target.value)} />
      </Field>
      <Field id="mj-subject_codes" label="Subject codes" hint="Comma-separated course prefixes, e.g. MIS, CS." issues={byField.subject_codes}>
        <input id="mj-subject_codes" className="adm-input" value={f.subject_codes} onChange={(e) => set("subject_codes", e.target.value)} />
      </Field>
      <div className="adm-field-row">
        <Field id="mj-catalog" label="Catalog link (optional)" issues={byField.catalog}>
          <input id="mj-catalog" className="adm-input" value={f.catalog} onChange={(e) => set("catalog", e.target.value)} />
        </Field>
        <Field id="mj-class_source" label="Where the class list comes from" hint="Usually “catalog”." issues={byField.class_source}>
          <input id="mj-class_source" className="adm-input" value={f.class_source} onChange={(e) => set("class_source", e.target.value)} />
        </Field>
      </div>
      <div className="adm-actions">
        <button type="submit" className="adm-btn adm-btn-primary" disabled={busy}>
          {busy ? "Saving…" : creating ? "Add major" : "Save major"}
        </button>
        <Link href="/admin/classes" className="adm-btn adm-btn-quiet">
          {creating ? "Cancel" : "Back to classes"}
        </Link>
      </div>
      {major ? (
        <div className="adm-actions">
          <ConfirmButton
            label="Delete this major"
            disabled={major.classes.length > 0}
            title={`Delete ${major.name}?`}
            body={<p>The major leaves the public site. It has no classes, so nothing else changes.</p>}
            confirmLabel="Delete major"
            onConfirm={async () => {
              const res = await adminApi("DELETE", `/admin/majors/${encodeURIComponent(major.id)}`, { version: major.version });
              if (!res.ok) return res.error.message;
              router.push("/admin/classes?deleted=1");
              router.refresh();
            }}
          />
          {major.classes.length ? <span className="adm-hint">A major can only be deleted once it has no classes. Move or delete them first.</span> : null}
        </div>
      ) : null}
    </form>
  );
}
