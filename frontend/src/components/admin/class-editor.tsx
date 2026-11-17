"use client";

/**
 * One class: its details, the task families that measure it, and its units.
 *
 * The two unit rules (design §3.1, `unit_families`):
 *  1. a family sits in at most one unit, anywhere;
 *  2. a unit's families must be families of its class.
 * The editor offers only families that satisfy both: a family already in
 * another unit is shown, disabled, with where it lives. The database enforces
 * the same rules, and its refusal is shown if the UI's picture was stale.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { adminApi, partitionIssues } from "@/lib/admin/client";
import type { AdminClass, AdminError, AdminMajor, AdminUnit, Issue, TaskFamily, UnitInput } from "@/lib/admin/types";

import { ConfirmButton } from "./confirm-button";
import { EmptyState, Field, FormError } from "./form-bits";

const COURSE_RE = /^[A-Z]{2,4} \d{3}[A-Z]?$/;
const UNIT_KEY_RE = /^[a-z0-9][a-z0-9-]*$/;
const coursePath = (course: string) => encodeURIComponent(course);

/* ------------------------------------------------------------------ class */

export function ClassForm({ klass, majors, defaultMajor }: { klass: AdminClass | null; majors: AdminMajor[]; defaultMajor?: string }) {
  const router = useRouter();
  const creating = klass === null;
  const [course, setCourse] = useState(klass?.course ?? "");
  const [title, setTitle] = useState(klass?.title ?? "");
  const [credits, setCredits] = useState(klass?.credit_hours?.toString() ?? "");
  const [major, setMajor] = useState(klass ? klass.major_id ?? "" : defaultMajor ?? majors[0]?.id ?? "");
  const [reason, setReason] = useState(klass?.unassigned_reason ?? "");
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const { byField, other } = partitionIssues(issues, ["course", "title", "credit_hours", "major_id", "unassigned_reason"]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const local: Issue[] = [];
    if (creating && !COURSE_RE.test(course.trim())) local.push({ path: "course", message: "Write the course code as subject and number, e.g. MIS 200.", severity: "error" });
    if (credits.trim() && !(Number(credits) > 0)) local.push({ path: "credit_hours", message: "Enter a number of credit hours, e.g. 3.", severity: "error" });
    if (!major && !reason.trim()) local.push({ path: "unassigned_reason", message: "Say why this class is not part of a major, e.g. “Business core”.", severity: "error" });
    setIssues(local);
    if (local.length) return;
    const body = {
      course: creating ? course.trim() : klass.course,
      major_id: major || null,
      unassigned_reason: major ? null : reason.trim(),
      title: title.trim() || null,
      credit_hours: credits.trim() ? Number(credits) : null,
      position: klass?.position ?? 0,
    };
    setBusy(true);
    const res = creating
      ? await adminApi<AdminClass>("POST", "/admin/classes", { body })
      : await adminApi<AdminClass>("PUT", `/admin/classes/${coursePath(klass.course)}`, { body, version: klass.version });
    setBusy(false);
    if (!res.ok) {
      setIssues(res.error.issues ?? []);
      setError(res.error);
      return;
    }
    router.replace(`/admin/classes/${coursePath(res.data.course)}?saved=${creating ? "created" : "1"}`);
    router.refresh();
  }

  return (
    <form className="adm-form" onSubmit={submit} noValidate>
      <FormError error={error} unmatched={other} />
      <div className="adm-field-row">
        <Field id="c-course" label="Course code" hint={creating ? "e.g. MIS 200. Permanent." : "Permanent."} issues={byField.course}>
          <input id="c-course" className="adm-input" value={course} readOnly={!creating} onChange={(e) => setCourse(e.target.value.toUpperCase())} aria-invalid={byField.course ? true : undefined} />
        </Field>
        <Field id="c-credits" label="Credit hours (optional)" issues={byField.credit_hours}>
          <input id="c-credits" className="adm-input" inputMode="decimal" value={credits} onChange={(e) => setCredits(e.target.value)} aria-invalid={byField.credit_hours ? true : undefined} />
        </Field>
      </div>
      <Field id="c-title" label="Title (optional)" isPublic hint={klass?.resolved_title && !klass.title ? `Currently shown as “${klass.resolved_title}” from the catalog.` : "Leave blank to use the catalog title."} issues={byField.title}>
        <input id="c-title" className="adm-input" value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field id="c-major" label="Major" issues={byField.major_id}>
        <select id="c-major" className="adm-select" value={major} onChange={(e) => setMajor(e.target.value)}>
          {majors.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
          <option value="">Not part of a major (for example, the business core)</option>
        </select>
      </Field>
      {!major ? (
        <Field id="c-reason" label="Why it is not in a major" issues={byField.unassigned_reason}>
          <input id="c-reason" className="adm-input" value={reason} onChange={(e) => setReason(e.target.value)} aria-invalid={byField.unassigned_reason ? true : undefined} />
        </Field>
      ) : null}
      <div className="adm-actions">
        <button type="submit" className="adm-btn adm-btn-primary" disabled={busy}>
          {busy ? "Saving…" : creating ? "Add class" : "Save class details"}
        </button>
        <Link href="/admin/classes" className="adm-btn adm-btn-quiet">
          {creating ? "Cancel" : "Back to classes"}
        </Link>
      </div>
      {klass ? (
        <div className="adm-actions">
          <ConfirmButton
            label="Delete this class"
            title={`Delete ${klass.course}?`}
            body={<p>The class and its units leave the public site. Task families and results are not deleted.</p>}
            confirmLabel="Delete class"
            typeToConfirm={klass.course}
            onConfirm={async () => {
              const res = await adminApi("DELETE", `/admin/classes/${coursePath(klass.course)}`, { version: klass.version });
              if (!res.ok) return res.error.message;
              router.push("/admin/classes?deleted=1");
              router.refresh();
            }}
          />
        </div>
      ) : null}
    </form>
  );
}

/* ------------------------------------------------------- class families */

export function ClassFamilies({ klass, families }: { klass: AdminClass; families: TaskFamily[] }) {
  const router = useRouter();
  const [chosen, setChosen] = useState<string[]>(klass.task_families);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const claimedBy = new Map(klass.units.flatMap((u) => u.families.map((f) => [f, u] as const)));
  const available = families.filter((f) => !f.archived_at || klass.task_families.includes(f.key));
  const dirty = chosen.slice().sort().join() !== klass.task_families.slice().sort().join();

  async function save() {
    setBusy(true);
    setError(null);
    const res = await adminApi<AdminClass>("PUT", `/admin/classes/${coursePath(klass.course)}/task-families`, { body: { families: chosen }, version: klass.version });
    setBusy(false);
    if (!res.ok) return setError(res.error);
    router.replace(`/admin/classes/${coursePath(klass.course)}?saved=families`);
    router.refresh();
  }

  return (
    <div className="adm-form" style={{ maxWidth: "none" }}>
      <p className="adm-hint">Which task families measure this class. A family used by one of this class&apos;s units must stay selected.</p>
      <FormError error={error} unmatched={error?.issues ?? []} />
      {available.length ? (
        <div className="adm-checklist">
          {available.map((f) => {
            const unit = claimedBy.get(f.key);
            const locked = !!unit && chosen.includes(f.key);
            return (
              <label key={f.key} className={`adm-check ${locked ? "is-disabled" : ""}`}>
                <input
                  type="checkbox"
                  checked={chosen.includes(f.key)}
                  disabled={locked}
                  onChange={() => setChosen((c) => (c.includes(f.key) ? c.filter((k) => k !== f.key) : [...c, f.key]))}
                />
                <span>
                  {f.title}
                  <span className="mono muted"> {f.key}</span>
                  {unit ? <span className="adm-hint"> In unit {unit.n}: {unit.title}</span> : null}
                </span>
              </label>
            );
          })}
        </div>
      ) : (
        <EmptyState title="No task families exist yet">
          <p>
            <Link href="/admin/material/families/new">Create a task family</Link> first.
          </p>
        </EmptyState>
      )}
      <div className="adm-actions">
        <button type="button" className="adm-btn adm-btn-primary" disabled={!dirty || busy} onClick={save}>
          {busy ? "Saving…" : "Save task families"}
        </button>
        {dirty ? (
          <button type="button" className="adm-btn adm-btn-quiet" onClick={() => setChosen(klass.task_families)}>
            Undo
          </button>
        ) : null}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- units */

interface UnitFields {
  key: string;
  title: string;
  blurb: string;
  covers: string;
  source: string;
  caveat: string;
  families: string[];
}

const fieldsOf = (u: AdminUnit | null): UnitFields => ({
  key: u?.key ?? "",
  title: u?.title ?? "",
  blurb: u?.blurb ?? "",
  covers: (u?.covers ?? []).join("\n"),
  source: u?.source ?? "",
  caveat: u?.caveat ?? "",
  families: u?.families ?? [],
});

const UNIT_FIELDS = ["key", "n", "title", "blurb", "covers", "source", "caveat", "families"];

function UnitForm({
  klass,
  unit,
  familyTitle,
  claimedElsewhere,
  onDone,
}: {
  klass: AdminClass;
  unit: AdminUnit | null;
  familyTitle: Map<string, string>;
  /** family key → where it already lives ("In unit 2: Databases", "In a unit of OM 300"). */
  claimedElsewhere: Map<string, string>;
  onDone: () => void;
}) {
  const router = useRouter();
  const [f, setF] = useState<UnitFields>(() => fieldsOf(unit));
  const [issues, setIssues] = useState<Issue[]>([]);
  const [error, setError] = useState<AdminError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof UnitFields>(k: K, v: UnitFields[K]) => setF((p) => ({ ...p, [k]: v }));
  const { byField, other } = partitionIssues(issues, UNIT_FIELDS);
  const id = unit?.id ?? "new";

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const local: Issue[] = [];
    if (!UNIT_KEY_RE.test(f.key)) local.push({ path: "key", message: "Use lowercase letters, digits and dashes, e.g. databases.", severity: "error" });
    if (!f.title.trim()) local.push({ path: "title", message: "Give the unit a title.", severity: "error" });
    setIssues(local);
    if (local.length) return;
    const nextN = Math.max(0, ...klass.units.map((u) => u.n)) + 1;
    const body: UnitInput = {
      key: f.key,
      n: unit?.n ?? nextN,
      title: f.title.trim(),
      blurb: f.blurb.trim(),
      covers: f.covers.split("\n").map((c) => c.trim()).filter(Boolean),
      source: f.source.trim() || null,
      caveat: f.caveat.trim() || null,
      families: f.families,
    };
    setBusy(true);
    const res = unit
      ? await adminApi<AdminUnit>("PUT", `/admin/units/${encodeURIComponent(unit.id)}`, { body, version: unit.version })
      : await adminApi<AdminUnit>("POST", `/admin/classes/${coursePath(klass.course)}/units`, { body });
    setBusy(false);
    if (!res.ok) {
      setIssues(res.error.issues ?? []);
      setError(res.error);
      return;
    }
    onDone();
    router.replace(`/admin/classes/${coursePath(klass.course)}?saved=unit`);
    router.refresh();
  }

  return (
    <form className="adm-form adm-panel" onSubmit={save} noValidate style={{ maxWidth: "none" }}>
      <h3 style={{ margin: 0 }}>{unit ? `Edit unit ${unit.n}` : "Add a unit"}</h3>
      <FormError error={error} unmatched={other} />
      <div className="adm-field-row">
        <Field id={`u-${id}-title`} label="Title" isPublic issues={byField.title}>
          <input id={`u-${id}-title`} className="adm-input" value={f.title} onChange={(e) => set("title", e.target.value)} aria-invalid={byField.title ? true : undefined} />
        </Field>
        <Field id={`u-${id}-key`} label="Short id" hint="Used in links, e.g. databases." issues={byField.key}>
          <input id={`u-${id}-key`} className="adm-input" value={f.key} spellCheck={false} onChange={(e) => set("key", e.target.value)} aria-invalid={byField.key ? true : undefined} />
        </Field>
      </div>
      <Field id={`u-${id}-blurb`} label="Summary" isPublic hint="One or two sentences on what the unit teaches." issues={byField.blurb}>
        <textarea id={`u-${id}-blurb`} className="adm-textarea" rows={3} value={f.blurb} onChange={(e) => set("blurb", e.target.value)} />
      </Field>
      <Field id={`u-${id}-covers`} label="Topics covered" isPublic hint="One topic per line." issues={byField.covers}>
        <textarea id={`u-${id}-covers`} className="adm-textarea" rows={4} value={f.covers} onChange={(e) => set("covers", e.target.value)} />
      </Field>
      <div className="adm-field-row">
        <Field id={`u-${id}-source`} label="Source (optional)" hint="e.g. the syllabus or textbook chapter." issues={byField.source}>
          <input id={`u-${id}-source`} className="adm-input" value={f.source} onChange={(e) => set("source", e.target.value)} />
        </Field>
        <Field id={`u-${id}-caveat`} label="Caveat (optional)" issues={byField.caveat}>
          <input id={`u-${id}-caveat`} className="adm-input" value={f.caveat} onChange={(e) => set("caveat", e.target.value)} />
        </Field>
      </div>
      <fieldset className="adm-fieldset">
        <legend>Task families in this unit</legend>
        {klass.task_families.length ? (
          <div className="adm-checklist">
            {klass.task_families.map((key) => {
              const other = claimedElsewhere.get(key);
              return (
                <label key={key} className={`adm-check ${other ? "is-disabled" : ""}`}>
                  <input
                    type="checkbox"
                    checked={f.families.includes(key)}
                    disabled={!!other}
                    onChange={() => set("families", f.families.includes(key) ? f.families.filter((k) => k !== key) : [...f.families, key])}
                  />
                  <span>
                    {familyTitle.get(key) ?? key}
                    <span className="adm-hint"> {other ?? (f.families.includes(key) ? "In this unit" : "Free")}</span>
                  </span>
                </label>
              );
            })}
          </div>
        ) : (
          <p className="adm-hint">Choose this class&apos;s task families first (above); a unit can only use those.</p>
        )}
        {byField.families?.map((i, n) => (
          <p key={n} className="adm-field-error" role="alert">
            {i.message}
          </p>
        ))}
      </fieldset>
      <div className="adm-actions" style={{ margin: 0 }}>
        <button type="submit" className="adm-btn adm-btn-primary" disabled={busy}>
          {busy ? "Saving…" : unit ? "Save unit" : "Add unit"}
        </button>
        <button type="button" className="adm-btn adm-btn-quiet" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function UnitEditor({ klass, families }: { klass: AdminClass; families: TaskFamily[] }) {
  const router = useRouter();
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const units = klass.units.slice().sort((a, b) => a.n - b.n);
  const familyTitle = new Map(families.map((f) => [f.key, f.title]));
  /** Families claimed by a unit OTHER than `except`, in this class or any other (invariant 1). */
  const claimedExcept = (except: string | null) => {
    const claimed = new Map<string, string>();
    for (const f of families) if (f.unit && f.unit.course !== klass.course) claimed.set(f.key, `In a unit of ${f.unit.course}`);
    for (const u of units) if (u.id !== except) for (const key of u.families) claimed.set(key, `In unit ${u.n}: ${u.title}`);
    return claimed;
  };

  async function move(index: number, delta: -1 | 1) {
    const order = units.map((u) => u.id);
    const j = index + delta;
    if (j < 0 || j >= order.length) return;
    [order[index], order[j]] = [order[j]!, order[index]!];
    setBusy(true);
    setError(null);
    const res = await adminApi("POST", `/admin/classes/${coursePath(klass.course)}/units/reorder`, { body: { order } });
    setBusy(false);
    if (!res.ok) setError(res.error.message);
    router.refresh();
  }

  return (
    <>
      {error ? (
        <div className="adm-panel adm-panel-error" role="alert">
          {error}
        </div>
      ) : null}
      {units.length ? (
        <ol style={{ listStyle: "none", padding: 0, margin: "0 0 1rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {units.map((u, i) =>
            editing === u.id ? (
              <li key={u.id}>
                <UnitForm klass={klass} unit={u} familyTitle={familyTitle} claimedElsewhere={claimedExcept(u.id)} onDone={() => setEditing(null)} />
              </li>
            ) : (
              <li key={u.id} className="adm-panel">
                <div className="adm-toolbar" style={{ margin: 0 }}>
                  <div>
                    <strong>
                      Unit {u.n}: {u.title}
                    </strong>{" "}
                    <span className="mono muted">{u.key}</span>
                    {u.blurb ? <p style={{ margin: "0.25rem 0 0" }}>{u.blurb}</p> : null}
                    <p className="adm-hint" style={{ marginTop: "0.25rem" }}>
                      {u.families.length ? `Task families: ${u.families.map((k) => familyTitle.get(k) ?? k).join(", ")}` : "No task families yet, so nothing is measured for this unit."}
                    </p>
                  </div>
                  <span className="adm-actions" style={{ margin: 0 }}>
                    <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" aria-label={`Move unit ${u.n} up`} disabled={busy || i === 0} onClick={() => move(i, -1)}>
                      ↑
                    </button>
                    <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" aria-label={`Move unit ${u.n} down`} disabled={busy || i === units.length - 1} onClick={() => move(i, 1)}>
                      ↓
                    </button>
                    <button type="button" className="adm-btn adm-btn-quiet adm-btn-small" onClick={() => setEditing(u.id)}>
                      Edit
                    </button>
                    <ConfirmButton
                      small
                      label="Delete"
                      title={`Delete unit ${u.n}, “${u.title}”?`}
                      body={<p>The unit leaves the public class page. Its task families stay with the class.</p>}
                      confirmLabel="Delete unit"
                      onConfirm={async () => {
                        const res = await adminApi("DELETE", `/admin/units/${encodeURIComponent(u.id)}`, { version: u.version });
                        if (!res.ok) return res.error.message;
                        router.refresh();
                      }}
                    />
                  </span>
                </div>
              </li>
            ),
          )}
        </ol>
      ) : (
        <EmptyState title="This class has no units yet">
          <p>Units split a class into the topics a professor teaches. The public class page lists results unit by unit.</p>
        </EmptyState>
      )}
      {editing === "new" ? (
        <UnitForm klass={klass} unit={null} familyTitle={familyTitle} claimedElsewhere={claimedExcept(null)} onDone={() => setEditing(null)} />
      ) : (
        <button type="button" className="adm-btn adm-btn-secondary" onClick={() => setEditing("new")}>
          Add a unit
        </button>
      )}
    </>
  );
}
