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
 * "You clicked a score, and we kept hold of which model it was."
 *
 * ⚠ THE HALF OF A CELL CLICK THAT WOULD OTHERWISE BE THROWN AWAY. A cell is the
 * crossing of a model and an entity. Its link drills into the entity — and
 * without this, the model half of what the reader just clicked evaporates on
 * arrival, dropping them into the full field they had already narrowed. So the
 * level below opens with that model marked in the grid and says so here, with a
 * way back to the whole field one click away.
 *
 * Rendered only when a `?model=` names a model that is actually on this level.
 * A focus note for a model the grid does not contain would be a caption
 * describing a different page.
 */
export function ModelFocus({
  displayName,
  clearHref,
}: {
  displayName: string;
  clearHref: string;
}) {
  return (
    <p className="xp-focus">
      <span className="xp-focus-mark" aria-hidden="true">
        ●
      </span>{" "}
      Following <strong>{displayName}</strong> down from the level above — its
      row is marked below.{" "}
      <Link href={clearHref}>Show every model equally</Link>
    </p>
  );
}

/**
 * The one-line orientation each level can offer, collapsed by default.
 *
 * ⚠ THE RECOMMENDATION ESCAPE HATCH THAT USED TO LEAD THIS BOX IS GONE. The
 * recommendation feature was removed from the site entirely, so the "just tell
 * me what to use" link that pointed at `/recommend` went with it. What remains
 * is the optional, collapsed explanation — kept because "what am I looking at"
 * is still a fair question on a grid, and this is the only place the drill-down
 * answers it. Without a call to action the box is no longer the second-loudest
 * thing on the page; it is a quiet aside (`.xp-help` in globals.css).
 *
 * `explain` is the one sentence this particular grid would need if a reader
 * asked — passed in per level rather than written once here, because "what am I
 * looking at" has a different answer on a course grid than on an evidence page,
 * and a single generic sentence would be true of neither.
 */
export function ExploreHelp({ explain }: { explain: string }) {
  return (
    <aside className="xp-help">
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
