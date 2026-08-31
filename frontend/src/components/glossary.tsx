/**
 * The "?" that makes every invented word decodable in one move.
 *
 * ⚠ SERVER COMPONENTS, NO CLIENT JS — and that is a hard constraint here rather
 * than a preference. `components/trust-badges.tsx` already states the house
 * rule: "a results page should not need a bundle to explain itself". A glossary
 * is the single most obvious place to reach for a popover library, and the
 * single worst place to make comprehension depend on hydration finishing.
 *
 * ⚠ WHY A `<button>` AND NOT `<details>`, WHICH IS THE OBVIOUS CHOICE.
 * `<details>` is FLOW content. Most of the words needing a definition live
 * inside `<p className="muted">…`, and a `<p>` may contain only PHRASING
 * content — so a browser parsing `<p><details>` silently closes the paragraph
 * first. Server-rendered HTML and the client's DOM then disagree, which React
 * reports as a hydration error and which no amount of CSS fixes. A `<button>`
 * is phrasing content and nests legally wherever a word does.
 *
 * The disclosure is therefore pure CSS: `:hover` for a mouse, `:focus` for a
 * keyboard, and — the one that matters on a tablet — a tap, which focuses the
 * button and shows the card with no script running. Blur closes it.
 *
 * ⚠ THE `title` IS THE FLOOR, NOT THE DECORATION. Native `title` is what every
 * existing badge on this site uses, it is announced by screen readers as the
 * button's description, and it survives everywhere the drawn card cannot — most
 * importantly inside `.table-scroll`, whose `overflow-x: auto` would clip an
 * absolutely-positioned card. Inside a scrolling table, use the `title` alone
 * (that is what `plain` is sized for); the card is the enhancement.
 */

import { glossaryFor, lookup, tooltip } from "@/lib/glossary";

/**
 * One term, inline in prose, with its definition one hover or one tap away.
 *
 * `children` overrides the displayed word so the sentence can keep its own
 * grammar — `<Term id="judged">marked by an AI</Term>` reads naturally where
 * the glossary's own heading would not.
 *
 * ⚠ RENDERS THE WORD PLAIN, NEVER NOTHING, for an id with no entry. A missing
 * definition must cost the reader an affordance, not a word out of the middle
 * of a sentence. `tests/glossary.test.ts` proves the shipped lists all resolve.
 */
export function Term({
  id,
  children,
  className,
}: {
  id: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const entry = lookup(id);
  if (!entry) return <>{children}</>;

  return (
    <button
      type="button"
      className={`term${className ? ` ${className}` : ""}`}
      title={tooltip(id)}
      // The button opens a definition and changes nothing. Saying so keeps a
      // screen-reader user from expecting a navigation or a submit.
      aria-haspopup="true"
    >
      <span className="term-word">{children ?? entry.term}</span>
      <span className="term-cue" aria-hidden="true">
        ?
      </span>
      {/* aria-hidden because the `title` already carries this text as the
          button's description; announcing both reads the definition twice. */}
      <span className="term-card" aria-hidden="true">
        <span className="term-card-title">{entry.term}</span>
        <span className="term-card-body">{entry.plain}</span>
        {entry.more ? <span className="term-card-more">{entry.more}</span> : null}
      </span>
    </button>
  );
}

/**
 * The whole vocabulary of a page, in one collapsed panel.
 *
 * ⚠ THE INLINE "?" AND THIS PANEL ARE NOT REDUNDANT, and dropping either one
 * loses a different reader. The "?" answers a word you have already tripped
 * over — it needs you to notice the word first. The panel answers the reader
 * who does not yet know WHICH word is the one confusing them, and the reader
 * who wants to read the vocabulary through once before starting. That second
 * reader is a large share of the audience this layer was built for.
 *
 * Collapsed by default because an open glossary above a leaderboard buries the
 * leaderboard; a `<summary>` written as a question is the affordance.
 */
export function GlossaryPanel({
  terms,
  title = "What do these words mean?",
  intro,
}: {
  terms: readonly string[];
  title?: string;
  intro?: string;
}) {
  const entries = glossaryFor(terms);
  if (entries.length === 0) return null;

  return (
    <details className="glossary">
      <summary className="glossary-summary">
        <span className="glossary-summary-icon" aria-hidden="true">
          ?
        </span>
        {title}
        <span className="glossary-summary-hint muted">
          {" "}
          — {entries.length} terms, in plain English
        </span>
      </summary>
      <div className="glossary-body">
        <p className="glossary-intro muted">
          {intro ??
            "This project had to invent some vocabulary. None of it is difficult, and none of it is meant to keep anyone out — here is all of it in one place."}
        </p>
        <dl className="glossary-list">
          {entries.map((entry) => (
            <div key={entry.id} className="glossary-item">
              <dt>{entry.term}</dt>
              <dd>
                {entry.plain}
                {entry.more ? <span className="glossary-more">{entry.more}</span> : null}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </details>
  );
}
