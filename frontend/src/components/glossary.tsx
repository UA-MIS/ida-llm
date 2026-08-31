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
 * ⚠ `title` IS A BONUS, NOT THE FLOOR. It used to be described here as the
 * floor — announced by screen readers as the button's description, and
 * surviving everywhere the drawn `.term-card` cannot, including inside
 * `.table-scroll`'s `overflow-x: auto`, which clips an absolutely-positioned
 * card. That reasoning has a hole: `title` itself is not exposed to touch
 * screen readers or voice control AT ALL, so it cannot be the only way in —
 * see QA-24. The actual floor is the `.sr-only` span below. It survives
 * `.table-scroll` for the same reason the drawn card does not: an
 * `overflow-x: auto` container clips what is PAINTED, and an `.sr-only`
 * element is never painted in the first place, so it is unaffected either
 * way. `title` stays as the fast path for a sighted mouse user.
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
    >
      <span className="term-word">{children ?? entry.term}</span>
      <span className="term-cue" aria-hidden="true">
        ?
      </span>
      {/* aria-hidden: this is the drawn, `:hover`/`:focus` CSS card. Its text
          is repeated below in `.sr-only` form, which is what AT actually
          reads — announcing both here would read the definition twice. */}
      <span className="term-card" aria-hidden="true">
        <span className="term-card-title">{entry.term}</span>
        <span className="term-card-body">{entry.plain}</span>
        {entry.more ? <span className="term-card-more">{entry.more}</span> : null}
      </span>
      {/* ⚠ NOT `aria-hidden`. This is the one copy of the definition every
          assistive technology can reach — desktop screen readers get it from
          the button's accessible name same as `title` would give them, and
          touch screen readers and voice control, which cannot see `title` at
          all, get it here for the first time. */}
      <span className="sr-only">
        {" "}
        — {entry.plain}
        {entry.more ? ` ${entry.more}` : ""}
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
