"use client";

/**
 * The expander for a collapsed model family.
 *
 * ⚠ HOLDS NO DATA. It receives a label, a count and pre-rendered table cells —
 * the already-aggregated numbers the server drew — and nothing about runs,
 * tasks or transcripts. All it owns is whether the member rows are showing.
 */

import { useState, type ReactNode } from "react";

export function FamilyGroup({
  label,
  summary,
  defaultOpen,
  children,
}: {
  /** "Claude Opus · 6 versions". */
  label: string;
  /** The family row's score cells. */
  summary: ReactNode;
  /** Open on first paint, e.g. when the focused model is one of the members. */
  defaultOpen?: boolean;
  /** The per-version rows, newest first. */
  children: ReactNode;
}) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  return (
    <>
      <tr className={`xp-family${open ? " xp-family-open" : ""}`}>
        <th scope="row" className="cg-model xp-model">
          <button
            type="button"
            className="xp-family-toggle"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <span className="xp-family-caret" aria-hidden="true">
              {open ? "▾" : "▸"}
            </span>
            {label}
          </button>
        </th>
        {summary}
      </tr>
      {open ? children : null}
    </>
  );
}
