"use client";

/**
 * The expander for a collapsed model family.
 *
 * ⚠ HOLDS NO DATA. The collapsed row IS the family's newest model; the server
 * hands it the model's name link and its ordinary score cells, plus the count of
 * earlier versions. All this owns is whether the earlier-version rows are showing.
 */

import { useState, type ReactNode } from "react";

export function FamilyGroup({
  name,
  earlierCount,
  cells,
  defaultOpen,
  rowClassName,
  children,
}: {
  /** The newest model's own name, already a link to its page. */
  name: ReactNode;
  /** How many older versions the expander reveals. */
  earlierCount: number;
  /** The newest model's score cells, drawn exactly as a normal model row's. */
  cells: ReactNode;
  /** Open on first paint, e.g. when the focused model is one of the earlier versions. */
  defaultOpen?: boolean;
  rowClassName?: string;
  /** The earlier-version rows, newest first. */
  children: ReactNode;
}) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  return (
    <>
      <tr className={["xp-family", open ? "xp-family-open" : "", rowClassName].filter(Boolean).join(" ")}>
        <th scope="row" className="cg-model xp-model">
          <button
            type="button"
            className="xp-family-toggle"
            aria-expanded={open}
            aria-label={`${open ? "Hide" : "Show"} ${earlierCount} earlier versions`}
            onClick={() => setOpen((v) => !v)}
          >
            <span className="xp-family-caret" aria-hidden="true">
              {open ? "▾" : "▸"}
            </span>
          </button>
          {name}
          <span className="xp-family-count muted"> · +{earlierCount} earlier</span>
        </th>
        {cells}
      </tr>
      {open ? children : null}
    </>
  );
}
