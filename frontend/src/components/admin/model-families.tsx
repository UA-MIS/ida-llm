"use client";

/** Model families: add, rename, and delete (only when no model uses it). */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi, partitionIssues } from "@/lib/admin/client";
import type { AdminError, Issue, ModelFamily } from "@/lib/admin/types";

import { ConfirmButton } from "./confirm-button";
import { EmptyState, Field, FormError } from "./form-bits";

const KEY_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;

function RenameRow({ family }: { family: ModelFamily }) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(family.display_name);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!name.trim()) return setError("Enter a name.");
    setBusy(true);
    const res = await adminApi("PUT", `/admin/model-families/${encodeURIComponent(family.key)}`, {
      body: { display_name: name.trim() },
      version: family.version,
    });
    setBusy(false);
    if (!res.ok) return setError(res.error.message);
    setEditing(false);
    setError(null);
    router.refresh();
  }

  return (
    <tr>
      <td>
        {editing ? (
          <div className="adm-field">
            <label className="sr-only" htmlFor={`fam-${family.key}`}>
              Name for {family.key}
            </label>
            <input id={`fam-${family.key}`} className="adm-input" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={error ? true : undefined} />
            {error ? <p className="adm-field-error">{error}</p> : null}
          </div>
        ) : (
          <strong>{family.display_name}</strong>
        )}
        <div className="mono muted">{family.key}</div>
      </td>
      <td>{family.member_keys.length ? family.member_keys.join(", ") : <span className="muted">No models yet</span>}</td>
      <td className="adm-cell-actions">
        {editing ? (
          <span className="adm-actions" style={{ margin: 0, justifyContent: "flex-end" }}>
            <button type="button" className="adm-btn adm-btn-primary adm-btn-small" onClick={save} disabled={busy}>
              Save
            </button>
            <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" onClick={() => { setEditing(false); setName(family.display_name); setError(null); }}>
              Cancel
            </button>
          </span>
        ) : (
          <span className="adm-actions" style={{ margin: 0, justifyContent: "flex-end" }}>
            <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" onClick={() => setEditing(true)}>
              Rename
            </button>
            <ConfirmButton
              small
              label="Delete"
              disabled={family.member_keys.length > 0}
              title={`Delete the family “${family.display_name}”?`}
              body={<p>No models belong to it, so nothing else changes.</p>}
              confirmLabel="Delete family"
              onConfirm={async () => {
                const res = await adminApi("DELETE", `/admin/model-families/${encodeURIComponent(family.key)}`, { version: family.version });
                if (!res.ok) return res.error.message;
                router.refresh();
              }}
            />
          </span>
        )}
      </td>
    </tr>
  );
}

export function ModelFamiliesManager({ families }: { families: ModelFamily[] }) {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const { byField, other } = partitionIssues(issues, ["key", "display_name"]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const local: Issue[] = [];
    if (!KEY_RE.test(key)) local.push({ path: "key", message: "Use lowercase letters, digits and dashes, e.g. openai-gpt-5.", severity: "error" });
    if (!name.trim()) local.push({ path: "display_name", message: "Enter a name.", severity: "error" });
    setIssues(local);
    if (local.length) return;
    setBusy(true);
    const res = await adminApi("POST", "/admin/model-families", { body: { key, display_name: name.trim() } });
    setBusy(false);
    if (!res.ok) {
      setIssues(res.error.issues ?? []);
      setError(res.error);
      return;
    }
    setKey("");
    setName("");
    router.refresh();
  }

  return (
    <>
      {families.length ? (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th scope="col">Family</th>
                <th scope="col">Models in it</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {families.map((f) => (
                <RenameRow key={`${f.key}:${f.version}`} family={f} />
              ))}
            </tbody>
          </table>
          <p className="adm-hint">A family can only be deleted once no model belongs to it.</p>
        </div>
      ) : (
        <EmptyState title="No model families yet">
          <p>Families group versions of one model (for example every GPT-5 release) into a single row on the public site.</p>
        </EmptyState>
      )}

      <h2>Add a family</h2>
      <form className="adm-form" onSubmit={add} noValidate>
        <FormError error={error} unmatched={other} />
        <div className="adm-field-row">
          <Field id="fam-new-name" label="Name" isPublic hint="e.g. “GPT-5”" issues={byField.display_name}>
            <input id="fam-new-name" className="adm-input" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={byField.display_name ? true : undefined} />
          </Field>
          <Field id="fam-new-key" label="Short id" hint="Permanent, e.g. openai-gpt-5" issues={byField.key}>
            <input id="fam-new-key" className="adm-input" value={key} spellCheck={false} onChange={(e) => setKey(e.target.value)} aria-invalid={byField.key ? true : undefined} />
          </Field>
        </div>
        <div className="adm-actions">
          <button type="submit" className="adm-btn adm-btn-primary" disabled={busy}>
            {busy ? "Adding…" : "Add family"}
          </button>
        </div>
      </form>
    </>
  );
}
