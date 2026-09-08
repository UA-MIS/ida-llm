/**
 * The two things every level of the drill-down carries: the way back up, and
 * the way out.
 *
 * ⚠ THE WAY OUT IS A REQUIREMENT, NOT A CONVENIENCE. The client's verdict on the
 * previous shape was "too much information, too many clicks, and you shouldn't
 * have to explain what's on the screen", and the fix they prescribed has a
 * standing escape hatch at every level: a reader who does not want to drill can
 * say so and be handed an answer instead. So `ExploreHelp` renders at the top of
 * all four levels, above the grid it belongs to — not in a footer, not behind a
 * menu, and not only on the first screen.
 *
 * ⚠ WHAT IT IS NOT: a `HowToRead` panel. Those exist on `/compare` and
 * `/leaderboard` and earn their place there, on pages dense enough to need an
 * orientation. This flow's whole premise is that a grid which needs explaining
 * has failed, so the explanation is one line, collapsed, and optional — and the
 * primary control beside it is the one that skips the reading entirely.
 */

import Link from "next/link";

export interface Crumb {
  label: string;
  href: string;
}

/**
 * Where you are, and every level above you.
 *
 * The last crumb is the current page and is NOT a link — a link to the page you
 * are on is a dead control, and on a drill-down it reads as another level.
 */
export function Breadcrumbs({ trail, here }: { trail: Crumb[]; here: string }) {
  return (
    <nav className="xp-crumbs" aria-label="Breadcrumb">
      <ol>
        {trail.map((crumb) => (
          <li key={crumb.href}>
            <Link href={crumb.href}>{crumb.label}</Link>
            <span className="xp-crumb-sep" aria-hidden="true">
              /
            </span>
          </li>
        ))}
        <li aria-current="page">{here}</li>
      </ol>
    </nav>
  );
}

/**
 * The escape hatch, on every level.
 *
 * `explain` is the one sentence this particular grid would need if a reader
 * asked — passed in per level rather than written once here, because "what am I
 * looking at" has a different answer on a course grid than on an evidence page,
 * and a single generic sentence would be true of neither.
 */
export function ExploreHelp({ explain }: { explain: string }) {
  return (
    <aside className="xp-help">
      <Link href="/recommend" className="xp-help-cta">
        Just tell me what to use
        <span className="xp-help-arrow" aria-hidden="true">
          →
        </span>
      </Link>
      <details className="xp-help-more">
        {/* "page", not "grid": three of the four levels are grids and the fourth
            is not, and a control that misnames what it is about to explain is
            a small lie on the one affordance whose job is to be trusted. */}
        <summary className="xp-help-summary">What this page shows</summary>
        <p className="xp-help-body">{explain}</p>
      </details>
    </aside>
  );
}
