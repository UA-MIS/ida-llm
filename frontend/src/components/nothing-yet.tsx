import type { ReactNode } from "react";

/**
 * The friendly zero-data screen: shown when a drill-down level resolves to
 * LITERALLY nothing to measure — a major with no classes, a class with no
 * units. It is deliberately NOT the same as a grid full of "not measured yet"
 * cells: when there ARE entities, the grid still renders and each empty cell
 * says so in place. This is the other case — there is no grid to render at all —
 * and a bare empty table reads as a rendering bug, so we say it in warm, honest
 * words instead.
 *
 * ⚠ HONEST, NOT APOLOGETIC. The wording stays consistent with the rest of the
 * product's "not measured yet" voice: forward-looking, and clear that the gap is
 * in what has been published and run, never a reading of any model. No fake
 * progress bar, no "coming soon!" marketing.
 *
 * Accessibility: the decorative mark is aria-hidden; the message is a real
 * heading and paragraphs, and colour is carried entirely by the palette tokens
 * so it holds its contrast in both themes.
 */
export function NothingYet({
  title,
  lead,
  detail,
  children,
}: {
  /** The headline — what is empty, in plain words. */
  title: string;
  /** One warm, forward-looking sentence. */
  lead: string;
  /** The honest reason, optional — why it is empty and whose gap it is. */
  detail?: ReactNode;
  /** Optional footer, e.g. a link back up a level. */
  children?: ReactNode;
}) {
  return (
    <section className="nothing-yet" aria-live="polite">
      <svg
        className="nothing-yet-mark"
        viewBox="0 0 48 48"
        width="48"
        height="48"
        aria-hidden="true"
        focusable="false"
      >
        {/* A small seedling — "growing", on-brand with the Organic palette.
            Stroke uses currentColor so it follows the accent in both themes. */}
        <path
          d="M24 42V22"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          d="M24 26C24 19 19 14 11 14c0 7 5 12 13 12Z"
          fill="currentColor"
          opacity="0.28"
        />
        <path
          d="M24 24C24 17 29 11 38 11c0 7-6 13-14 13Z"
          fill="currentColor"
          opacity="0.5"
        />
      </svg>
      <h2 className="nothing-yet-title">{title}</h2>
      <p className="nothing-yet-lead">{lead}</p>
      {detail ? <p className="muted nothing-yet-detail">{detail}</p> : null}
      {children ? <div className="nothing-yet-foot">{children}</div> : null}
    </section>
  );
}
