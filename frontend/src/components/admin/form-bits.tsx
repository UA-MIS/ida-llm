"use client";

/**
 * Small, dependency-free building blocks shared by every admin form. A
 * client module because `FormError` offers a reload button; server pages can
 * still render `EmptyState` and `PublicTag` from here.
 */

import type { AdminError, Issue } from "@/lib/admin/types";

/** "Shown on the public site": every field whose text professors will read. */
export function PublicTag() {
  return (
    <span className="adm-badge adm-badge-public" title="This text is shown on the public website">
      Public
    </span>
  );
}

export function Field({
  id,
  label,
  hint,
  isPublic,
  issues,
  children,
}: {
  id: string;
  label: string;
  hint?: React.ReactNode;
  isPublic?: boolean;
  issues?: Issue[];
  children: React.ReactNode;
}) {
  return (
    <div className="adm-field">
      <label className="adm-label" htmlFor={id}>
        {label}
        {isPublic ? <PublicTag /> : null}
      </label>
      {hint ? (
        <p className="adm-hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      {children}
      {issues?.map((issue, i) => (
        <p key={i} className="adm-field-error" id={i === 0 ? `${id}-error` : undefined} role="alert">
          {issue.message}
        </p>
      ))}
    </div>
  );
}

/** Issues that could not be pinned to a field, listed at the top of the form. */
export function IssuesList({ issues, title = "Please fix the following:" }: { issues: Issue[]; title?: string }) {
  if (!issues.length) return null;
  const errors = issues.filter((i) => i.severity !== "warning");
  return (
    <div className={`adm-panel adm-issues ${errors.length ? "adm-panel-error" : "adm-panel-warn"}`} role="alert">
      <strong>{errors.length ? title : "Warnings (you can still save):"}</strong>
      <ul>
        {issues.map((issue, i) => (
          <li key={i}>
            {issue.path ? <span className="mono">{issue.path}: </span> : null}
            {issue.message}
            {issue.severity === "warning" ? <span className="adm-badge adm-badge-warn"> warning</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The form-level error. A `version_conflict` gets its own wording: someone
 * else saved this item since the page loaded, and saving now would overwrite
 * their change.
 */
export function FormError({ error, unmatched = [] }: { error: AdminError | null; unmatched?: Issue[] }) {
  if (!error) return null;
  if (error.code === "version_conflict" || error.code === "precondition_required") {
    const current = (error.current ?? {}) as { updated_by?: string | null; updated_at?: string | null };
    return (
      <div className="adm-panel adm-panel-warn" role="alert">
        <h2 className="adm-panel-title">Someone else changed this while you were editing</h2>
        <p>
          {current.updated_by ? <>It was changed by <strong>@{current.updated_by}</strong>. </> : null}
          To avoid overwriting their work, reload the page to see the latest version, then make your change again.
        </p>
        <button type="button" className="adm-btn adm-btn-secondary" onClick={() => window.location.reload()}>
          Reload the latest version
        </button>
      </div>
    );
  }
  if (error.code === "validation_failed") {
    return <IssuesList issues={unmatched.length ? unmatched : []} title={error.message || "Please fix the highlighted fields."} />;
  }
  return (
    <div className="adm-panel adm-panel-error" role="alert">
      <p style={{ margin: 0 }}>{error.message}</p>
      {unmatched.length ? <IssuesList issues={unmatched} /> : null}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="adm-empty">
      <strong>{title}</strong>
      {children}
    </div>
  );
}
