"use client";

/**
 * Create or edit one model (`AdminModelInput`, full replace on save).
 *
 * The form is a flat set of string fields so every input is controlled and
 * forgiving; `toInput()` converts and checks them in one place, and anything
 * the API rejects comes back as `issues[]` pinned next to the field whose
 * dotted `path` matches (design §6.7).
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi, partitionIssues } from "@/lib/admin/client";
import {
  QUANTIZATIONS,
  SERVING_STACKS,
  type AdminError,
  type AdminModel,
  type AdminModelInput,
  type Credential,
  type Issue,
  type ModelFamily,
} from "@/lib/admin/types";

import { Field, FormError } from "./form-bits";

type KeySource = "env" | "credential" | "none";
type UrlSource = "fixed" | "env" | "none";

export interface ModelFormState {
  key: string;
  display_name: string;
  family_key: string;
  display_order: string;
  url_source: UrlSource;
  base_url: string;
  base_url_env: string;
  key_source: KeySource;
  api_key_env: string;
  credential_ref: string;
  enabled: boolean;
  hidden: boolean;
  timeout_s: string;
  max_retries: string;
  tags: string;
  model_id: string;
  serving_stack: string;
  serving_version: string;
  quantization: string;
  context_window: string;
  hardware: string;
  temperature: string;
  top_p: string;
  max_tokens: string;
  seed: string;
  cost_in: string;
  cost_out: string;
}

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

export function stateFromModel(m: AdminModel | null): ModelFormState {
  const s = m?.serving;
  return {
    key: m?.key ?? "",
    display_name: m?.display_name ?? "",
    family_key: m?.family_key ?? "",
    display_order: str(m?.display_order),
    url_source: m?.base_url ? "fixed" : m?.base_url_env ? "env" : m ? "none" : "fixed",
    base_url: m?.base_url ?? "",
    base_url_env: m?.base_url_env ?? "",
    key_source: m?.credential_ref ? "credential" : m?.api_key_env ? "env" : m ? "none" : "credential",
    api_key_env: m?.api_key_env ?? "",
    credential_ref: m?.credential_ref ?? "",
    enabled: m?.enabled ?? false,
    hidden: m?.hidden ?? false,
    timeout_s: str(m?.timeout_s ?? 120),
    max_retries: str(m?.max_retries ?? 3),
    tags: (m?.tags ?? []).join(", "),
    model_id: s?.model_id ?? "",
    serving_stack: s?.serving_stack ?? "openai_api",
    serving_version: s?.serving_version ?? "",
    quantization: s?.quantization ?? "unknown",
    context_window: str(s?.context_window),
    hardware: s?.hardware ?? "",
    temperature: str(s?.sampling?.temperature ?? 0),
    top_p: str(s?.sampling?.top_p ?? 1),
    max_tokens: str(s?.sampling?.max_tokens ?? 1024),
    seed: str(s?.sampling?.seed),
    cost_in: str(m?.cost?.input_usd_per_mtok ?? 0),
    cost_out: str(m?.cost?.output_usd_per_mtok ?? 0),
  };
}

const KEY_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
const ENV_RE = /^[A-Z][A-Z0-9_]*$/;

/** Convert the form to the API body, or return field issues the person can fix before sending. */
export function toInput(f: ModelFormState, original: AdminModel | null): { input?: AdminModelInput; issues: Issue[] } {
  const issues: Issue[] = [];
  const err = (path: string, message: string) => issues.push({ path, message, severity: "error" });
  const num = (path: string, raw: string, opts: { int?: boolean; min?: number; optional?: boolean } = {}): number | null => {
    if (raw.trim() === "") {
      if (!opts.optional) err(path, "Enter a number.");
      return null;
    }
    const n = Number(raw);
    if (!Number.isFinite(n) || (opts.int && !Number.isInteger(n))) {
      err(path, opts.int ? "Enter a whole number." : "Enter a number.");
      return null;
    }
    if (opts.min !== undefined && n < opts.min) err(path, `Must be at least ${opts.min}.`);
    return n;
  };

  if (!KEY_RE.test(f.key)) err("key", "Use lowercase letters, digits and dashes (for example gpt-5-mini), starting with a letter or digit.");
  if (!f.display_name.trim()) err("display_name", "Give the model a name people will recognise.");
  if (!f.model_id.trim()) err("serving.model_id", "Enter the model id the provider expects.");
  if (f.url_source === "fixed" && !/^https?:\/\/.+/.test(f.base_url.trim())) err("base_url", "Enter a full address starting with https://");
  if (f.url_source === "env" && !ENV_RE.test(f.base_url_env.trim())) err("base_url_env", "Use CAPITALS, digits and underscores, for example OLLAMA_URL.");
  if (f.key_source === "env" && !ENV_RE.test(f.api_key_env.trim())) err("api_key_env", "Use CAPITALS, digits and underscores, for example OPENAI_API_KEY.");
  if (f.key_source === "credential" && !f.credential_ref) err("credential_ref", "Choose a stored API key, or add one on the API keys page first.");

  const display_order = num("display_order", f.display_order, { int: true, optional: true });
  const timeout_s = num("timeout_s", f.timeout_s, { min: 1 });
  const max_retries = num("max_retries", f.max_retries, { int: true, min: 0 });
  const context_window = num("serving.context_window", f.context_window, { int: true, min: 1, optional: true });
  const temperature = num("serving.sampling.temperature", f.temperature, { min: 0 });
  const top_p = num("serving.sampling.top_p", f.top_p, { min: 0 });
  const max_tokens = num("serving.sampling.max_tokens", f.max_tokens, { int: true, min: 1 });
  const seed = num("serving.sampling.seed", f.seed, { int: true, optional: true });
  const cost_in = num("cost.input_usd_per_mtok", f.cost_in, { min: 0 });
  const cost_out = num("cost.output_usd_per_mtok", f.cost_out, { min: 0 });
  if (issues.length) return { issues };

  const orig = original?.serving;
  return {
    issues,
    input: {
      key: f.key,
      display_name: f.display_name.trim(),
      family_key: f.family_key || null,
      display_order,
      base_url: f.url_source === "fixed" ? f.base_url.trim() : null,
      base_url_env: f.url_source === "env" ? f.base_url_env.trim() : null,
      api_key_env: f.key_source === "env" ? f.api_key_env.trim() : null,
      credential_ref: f.key_source === "credential" ? f.credential_ref : null,
      enabled: f.enabled,
      hidden: f.hidden,
      timeout_s: timeout_s!,
      max_retries: max_retries!,
      tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean),
      serving: {
        // Fields this form does not edit are carried over untouched.
        ...(orig ?? {}),
        model_id: f.model_id.trim(),
        serving_stack: f.serving_stack as AdminModelInput["serving"]["serving_stack"],
        serving_version: f.serving_version.trim() || null,
        quantization: f.quantization as AdminModelInput["serving"]["quantization"],
        context_window,
        hardware: f.hardware.trim() || null,
        sampling: { ...(orig?.sampling ?? {}), temperature: temperature!, top_p: top_p!, max_tokens: max_tokens!, seed },
      },
      cost: { input_usd_per_mtok: cost_in!, output_usd_per_mtok: cost_out! },
    },
  };
}

const FIELDS = [
  "key", "display_name", "family_key", "display_order", "base_url", "base_url_env", "api_key_env", "credential_ref",
  "enabled", "hidden", "timeout_s", "max_retries", "tags", "serving.model_id", "serving.serving_stack",
  "serving.serving_version", "serving.quantization", "serving.context_window", "serving.hardware",
  "serving.sampling.temperature", "serving.sampling.top_p", "serving.sampling.max_tokens", "serving.sampling.seed",
  "cost.input_usd_per_mtok", "cost.output_usd_per_mtok",
];

export function ModelForm({
  model,
  families,
  credentials,
}: {
  model: AdminModel | null;
  families: ModelFamily[];
  credentials: Credential[];
}) {
  const router = useRouter();
  const creating = model === null;
  const [f, setF] = useState<ModelFormState>(() => stateFromModel(model));
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  const set = <K extends keyof ModelFormState>(k: K, v: ModelFormState[K]) => {
    setF((prev) => ({ ...prev, [k]: v }));
    setSaved(false);
  };
  const { byField, other } = partitionIssues(issues, FIELDS);
  const invalid = (path: string) => (byField[path]?.length ? true : undefined);
  const text = (k: keyof ModelFormState, path: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <input
      id={`m-${path}`}
      className="adm-input"
      value={f[k] as string}
      onChange={(e) => set(k, e.target.value as never)}
      aria-invalid={invalid(path)}
      aria-describedby={byField[path]?.length ? `m-${path}-error` : undefined}
      {...props}
    />
  );

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const { input, issues: local } = toInput(f, model);
    if (!input) {
      setIssues(local);
      return;
    }
    setBusy(true);
    const res = creating
      ? await adminApi<AdminModel>("POST", "/admin/models", { body: input })
      : await adminApi<AdminModel>("PUT", `/admin/models/${encodeURIComponent(model.key)}`, { body: input, version: model.version });
    setBusy(false);
    if (!res.ok) {
      setIssues(res.error.issues ?? []);
      setError(res.error);
      return;
    }
    setIssues([]);
    if (creating) {
      router.push(`/admin/models/${encodeURIComponent(res.data.key)}?created=1`);
    } else {
      setSaved(true);
      router.refresh();
    }
  }

  return (
    <form className="adm-form" onSubmit={submit} noValidate>
      <FormError error={error} unmatched={other} />
      {!error && other.length ? <FormError error={{ code: "validation_failed", message: "Please fix the following:" }} unmatched={other} /> : null}

      <fieldset className="adm-fieldset">
        <legend>Basics</legend>
        <Field id="m-display_name" label="Name" isPublic hint="How the model is named on the public site, e.g. “GPT-5 mini (OpenAI)”." issues={byField.display_name}>
          {text("display_name", "display_name")}
        </Field>
        <Field
          id="m-key"
          label="Short id"
          hint={creating ? "A permanent id used in links and results. It cannot be changed or reused later." : "This id is permanent."}
          issues={byField.key}
        >
          {text("key", "key", { readOnly: !creating, spellCheck: false, autoCapitalize: "off" })}
        </Field>
        <div className="adm-field-row">
          <Field id="m-family_key" label="Family" hint="Groups versions of the same model into one row." issues={byField.family_key}>
            <select id="m-family_key" className="adm-select" value={f.family_key} onChange={(e) => set("family_key", e.target.value)}>
              <option value="">No family</option>
              {families.map((fam) => (
                <option key={fam.key} value={fam.key}>
                  {fam.display_name}
                </option>
              ))}
            </select>
          </Field>
          <Field id="m-display_order" label="Display order" hint="Lower numbers are listed first. Leave blank to list last." issues={byField.display_order}>
            {text("display_order", "display_order", { inputMode: "numeric" })}
          </Field>
        </div>
        <label className="adm-check">
          <input type="checkbox" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          <span>
            <strong>Enabled</strong>
            <span className="adm-hint">Runs can be launched against this model.</span>
          </span>
        </label>
        <label className="adm-check">
          <input type="checkbox" checked={f.hidden} onChange={(e) => set("hidden", e.target.checked)} />
          <span>
            <strong>Hidden from the public site</strong>
            <span className="adm-hint">Keep its results private while you test it.</span>
          </span>
        </label>
        <Field id="m-tags" label="Tags" hint="Comma-separated, e.g. cloud, openai. The tag testing-only makes every launch ask for confirmation." issues={byField.tags}>
          {text("tags", "tags")}
        </Field>
      </fieldset>

      <fieldset className="adm-fieldset">
        <legend>Connection</legend>
        <Field id="m-url_source" label="Provider address">
          <select id="m-url_source" className="adm-select" value={f.url_source} onChange={(e) => set("url_source", e.target.value as UrlSource)}>
            <option value="fixed">A fixed web address</option>
            <option value="env">Read from a server setting (environment variable)</option>
            <option value="none">The provider&apos;s default</option>
          </select>
        </Field>
        {f.url_source === "fixed" ? (
          <Field id="m-base_url" label="Web address" hint="For example https://api.openai.com/v1" issues={byField.base_url}>
            {text("base_url", "base_url", { type: "url", spellCheck: false })}
          </Field>
        ) : null}
        {f.url_source === "env" ? (
          <Field id="m-base_url_env" label="Server setting name" issues={byField.base_url_env}>
            {text("base_url_env", "base_url_env", { spellCheck: false })}
          </Field>
        ) : null}

        <Field id="m-key_source" label="API key">
          <select id="m-key_source" className="adm-select" value={f.key_source} onChange={(e) => set("key_source", e.target.value as KeySource)}>
            <option value="credential">A key stored in this console</option>
            <option value="env">Read from a server setting (environment variable)</option>
            <option value="none">No key needed</option>
          </select>
        </Field>
        {f.key_source === "credential" ? (
          <Field
            id="m-credential_ref"
            label="Stored key"
            hint={credentials.length ? undefined : <>No keys are stored yet. <Link href="/admin/credentials">Add one on the API keys page</Link>.</>}
            issues={byField.credential_ref}
          >
            <select id="m-credential_ref" className="adm-select" value={f.credential_ref} onChange={(e) => set("credential_ref", e.target.value)} aria-invalid={invalid("credential_ref")}>
              <option value="">Choose a key…</option>
              {credentials.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} ({c.provider})
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        {f.key_source === "env" ? (
          <Field id="m-api_key_env" label="Server setting name" hint="Set by an operator, e.g. OPENAI_API_KEY." issues={byField.api_key_env}>
            {text("api_key_env", "api_key_env", { spellCheck: false })}
          </Field>
        ) : null}
        <div className="adm-field-row">
          <Field id="m-timeout_s" label="Timeout (seconds)" issues={byField.timeout_s}>
            {text("timeout_s", "timeout_s", { inputMode: "decimal" })}
          </Field>
          <Field id="m-max_retries" label="Retries" issues={byField.max_retries}>
            {text("max_retries", "max_retries", { inputMode: "numeric" })}
          </Field>
        </div>
      </fieldset>

      <fieldset className="adm-fieldset">
        <legend>Serving details</legend>
        <div className="adm-field-row">
          <Field id="m-serving.model_id" label="Provider model id" hint="Exactly as the provider spells it." issues={byField["serving.model_id"]}>
            {text("model_id", "serving.model_id", { spellCheck: false })}
          </Field>
          <Field id="m-serving.serving_stack" label="Provider type" issues={byField["serving.serving_stack"]}>
            <select id="m-serving.serving_stack" className="adm-select" value={f.serving_stack} onChange={(e) => set("serving_stack", e.target.value)}>
              {SERVING_STACKS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="adm-field-row">
          <Field id="m-serving.serving_version" label="Version (optional)" issues={byField["serving.serving_version"]}>
            {text("serving_version", "serving.serving_version")}
          </Field>
          <Field id="m-serving.quantization" label="Quantization" issues={byField["serving.quantization"]}>
            <select id="m-serving.quantization" className="adm-select" value={f.quantization} onChange={(e) => set("quantization", e.target.value)}>
              {QUANTIZATIONS.map((q) => (
                <option key={q} value={q}>
                  {q}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="adm-field-row">
          <Field id="m-serving.context_window" label="Context window (tokens, optional)" issues={byField["serving.context_window"]}>
            {text("context_window", "serving.context_window", { inputMode: "numeric" })}
          </Field>
          <Field id="m-serving.hardware" label="Hardware (optional)" issues={byField["serving.hardware"]}>
            {text("hardware", "serving.hardware")}
          </Field>
        </div>
        <div className="adm-field-row">
          <Field id="m-serving.sampling.temperature" label="Temperature" issues={byField["serving.sampling.temperature"]}>
            {text("temperature", "serving.sampling.temperature", { inputMode: "decimal" })}
          </Field>
          <Field id="m-serving.sampling.top_p" label="Top-p" issues={byField["serving.sampling.top_p"]}>
            {text("top_p", "serving.sampling.top_p", { inputMode: "decimal" })}
          </Field>
          <Field id="m-serving.sampling.max_tokens" label="Max answer tokens" issues={byField["serving.sampling.max_tokens"]}>
            {text("max_tokens", "serving.sampling.max_tokens", { inputMode: "numeric" })}
          </Field>
          <Field id="m-serving.sampling.seed" label="Seed (optional)" issues={byField["serving.sampling.seed"]}>
            {text("seed", "serving.sampling.seed", { inputMode: "numeric" })}
          </Field>
        </div>
      </fieldset>

      <fieldset className="adm-fieldset">
        <legend>Pricing</legend>
        <p className="adm-hint">US dollars per million tokens, from the provider&apos;s price list. Used for cost estimates and reports.</p>
        <div className="adm-field-row">
          <Field id="m-cost.input_usd_per_mtok" label="Input" issues={byField["cost.input_usd_per_mtok"]}>
            {text("cost_in", "cost.input_usd_per_mtok", { inputMode: "decimal" })}
          </Field>
          <Field id="m-cost.output_usd_per_mtok" label="Output" issues={byField["cost.output_usd_per_mtok"]}>
            {text("cost_out", "cost.output_usd_per_mtok", { inputMode: "decimal" })}
          </Field>
        </div>
      </fieldset>

      <div className="adm-actions">
        <button type="submit" className="adm-btn adm-btn-primary" disabled={busy}>
          {busy ? "Saving…" : creating ? "Add model" : "Save changes"}
        </button>
        <Link href="/admin/models" className="adm-btn adm-btn-quiet">
          {saved ? "Back to models" : "Cancel"}
        </Link>
        {saved ? (
          <span role="status" className="adm-badge adm-badge-ok">
            Saved
          </span>
        ) : null}
      </div>
    </form>
  );
}
