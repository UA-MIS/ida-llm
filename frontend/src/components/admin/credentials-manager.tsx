"use client";

/**
 * Stored provider API keys. ⚠ WRITE-ONLY: a key is typed into a password
 * field, sent once, and never shown again. The API returns metadata only;
 * the field is cleared as soon as the request finishes, success or not.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi, partitionIssues } from "@/lib/admin/client";
import { formatWhen } from "@/lib/admin/format";
import type { AdminError, Credential, Issue } from "@/lib/admin/types";

import { ConfirmButton } from "./confirm-button";
import { EmptyState, Field, FormError } from "./form-bits";

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,127}$/;

function SecretInput({ id, value, onChange, invalid }: { id: string; value: string; onChange: (v: string) => void; invalid?: boolean }) {
  return (
    <input
      id={id}
      className="adm-input"
      type="password"
      autoComplete="off"
      spellCheck={false}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid ? true : undefined}
    />
  );
}

function RotateForm({ credential, onDone }: { credential: Credential; onDone: () => void }) {
  const router = useRouter();
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function rotate(e: React.FormEvent) {
    e.preventDefault();
    if (!secret.trim()) return setError("Paste the new key.");
    setBusy(true);
    const res = await adminApi("PUT", `/admin/credentials/${encodeURIComponent(credential.name)}/secret`, {
      body: { api_key: secret.trim() },
      version: credential.version,
    });
    setSecret("");
    setBusy(false);
    if (!res.ok) return setError(res.error.message);
    onDone();
    router.refresh();
  }

  return (
    <form onSubmit={rotate} className="adm-form" style={{ maxWidth: "28rem" }} noValidate>
      <Field id={`rot-${credential.name}`} label={`New key for ${credential.name}`} hint="Models using this key switch to the new one straight away." issues={error ? [{ path: "", message: error, severity: "error" }] : undefined}>
        <SecretInput id={`rot-${credential.name}`} value={secret} onChange={setSecret} invalid={!!error} />
      </Field>
      <div className="adm-actions" style={{ margin: 0 }}>
        <button type="submit" className="adm-btn adm-btn-primary adm-btn-small" disabled={busy}>
          {busy ? "Saving…" : "Replace key"}
        </button>
        <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function CredentialsManager({ credentials, kekConfigured }: { credentials: Credential[]; kekConfigured: boolean }) {
  const router = useRouter();
  const [rotating, setRotating] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("");
  const [secret, setSecret] = useState("");
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<string | null>(null);
  const { byField, other } = partitionIssues(issues, ["name", "provider", "api_key"]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setAdded(null);
    const local: Issue[] = [];
    if (!NAME_RE.test(name)) local.push({ path: "name", message: "Use lowercase letters, digits and dashes, e.g. mistral-prod.", severity: "error" });
    if (!provider.trim()) local.push({ path: "provider", message: "Say which provider this key is for, e.g. Mistral.", severity: "error" });
    if (!secret.trim()) local.push({ path: "api_key", message: "Paste the API key.", severity: "error" });
    setIssues(local);
    if (local.length) return;
    setBusy(true);
    const res = await adminApi<Credential>("POST", "/admin/credentials", { body: { name, provider: provider.trim(), api_key: secret.trim() } });
    setSecret("");
    setBusy(false);
    if (!res.ok) {
      setIssues(res.error.issues ?? []);
      setError(res.error);
      return;
    }
    setAdded(res.data.name);
    setName("");
    setProvider("");
    router.refresh();
  }

  return (
    <>
      {!kekConfigured ? (
        <div className="adm-panel adm-panel-warn" role="status">
          <h2 className="adm-panel-title">New keys cannot be saved yet</h2>
          <p>The encryption key that protects stored API keys has not been configured for this environment. An operator needs to set it up first.</p>
        </div>
      ) : null}

      {credentials.length ? (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Provider</th>
                <th scope="col">Used by</th>
                <th scope="col">Added</th>
                <th scope="col">Last replaced</th>
                <th scope="col">Last used</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {credentials.map((c) => (
                <tr key={c.name}>
                  <td className="mono">{c.name}</td>
                  <td>{c.provider}</td>
                  <td>{c.used_by_models.length ? c.used_by_models.join(", ") : <span className="muted">No models</span>}</td>
                  <td>
                    {formatWhen(c.created_at)}
                    {c.created_by ? <div className="muted">by @{c.created_by}</div> : null}
                  </td>
                  <td>{formatWhen(c.rotated_at)}</td>
                  <td>{formatWhen(c.last_used_at)}</td>
                  <td className="adm-cell-actions">
                    {rotating === c.name ? (
                      <RotateForm credential={c} onDone={() => setRotating(null)} />
                    ) : (
                      <span className="adm-actions" style={{ margin: 0, justifyContent: "flex-end" }}>
                        <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" disabled={!kekConfigured} onClick={() => setRotating(c.name)}>
                          Replace key
                        </button>
                        <ConfirmButton
                          small
                          label="Delete"
                          disabled={c.used_by_models.length > 0}
                          title={`Delete the key “${c.name}”?`}
                          body={<p>The stored key is destroyed. No model uses it, so nothing else changes. This cannot be undone.</p>}
                          confirmLabel="Delete key"
                          onConfirm={async () => {
                            const res = await adminApi("DELETE", `/admin/credentials/${encodeURIComponent(c.name)}`, { version: c.version });
                            if (!res.ok) return res.error.message;
                            router.refresh();
                          }}
                        />
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="adm-hint">A key can only be deleted once no model uses it. Stored keys are encrypted and are never shown again after you save them.</p>
        </div>
      ) : (
        <EmptyState title="No API keys stored yet">
          <p>Store a provider&apos;s API key here, then choose it on a model&apos;s page. Models can also keep using keys set by an operator.</p>
        </EmptyState>
      )}

      <h2>Add an API key</h2>
      {added ? (
        <p role="status" className="adm-panel adm-panel-ok">
          Saved <strong className="mono">{added}</strong>. The key itself is now hidden for good; choose it on a model&apos;s page to use it.
        </p>
      ) : null}
      <form className="adm-form" onSubmit={add} noValidate autoComplete="off">
        <FormError error={error} unmatched={other} />
        <div className="adm-field-row">
          <Field id="cred-name" label="Name" hint="Permanent, e.g. mistral-prod" issues={byField.name}>
            <input id="cred-name" className="adm-input" value={name} spellCheck={false} onChange={(e) => setName(e.target.value)} aria-invalid={byField.name ? true : undefined} />
          </Field>
          <Field id="cred-provider" label="Provider" hint="A label for people, e.g. Mistral" issues={byField.provider}>
            <input id="cred-provider" className="adm-input" value={provider} onChange={(e) => setProvider(e.target.value)} aria-invalid={byField.provider ? true : undefined} />
          </Field>
        </div>
        <Field id="cred-secret" label="API key" hint="Paste it from the provider's dashboard. It is encrypted when saved and never shown again." issues={byField.api_key}>
          <SecretInput id="cred-secret" value={secret} onChange={setSecret} invalid={!!byField.api_key} />
        </Field>
        <div className="adm-actions">
          <button type="submit" className="adm-btn adm-btn-primary" disabled={busy || !kekConfigured}>
            {busy ? "Saving…" : "Save key"}
          </button>
        </div>
      </form>
    </>
  );
}
