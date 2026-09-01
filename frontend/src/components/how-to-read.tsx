/**
 * "How to read this page" — the orientation a first-time visitor gets before
 * they meet a single number.
 *
 * ⚠ THE READER THIS IS FOR HAS ALREADY DECIDED TO TRUST US ENOUGH TO CLICK.
 * The landing page did the arguing. What it could not do is explain the SHAPE
 * of the page they land on — and a professor who has never used a chatbot meets
 * a ranked table cold, with no idea whether they are looking at a
 * recommendation, a specification, or an advertisement. Three sentences of
 * "here is what this is, here is what to do with it" is the difference between
 * reading the page and bouncing off it.
 *
 * ⚠ DISMISSIBLE MEANS COLLAPSIBLE HERE, AND THAT IS A DELIBERATE TRADE.
 * Remembering a dismissal across visits needs `localStorage`, which needs a
 * client component, which means either a flash of the panel opening and then
 * closing for returning visitors, or an inline script that a future CSP (the
 * root layout's font comment already anticipates one) would block. A native
 * `<details open>` costs nothing, ships no JavaScript, cannot flash, and is
 * genuinely dismissible in the moment — one click and it is a single quiet
 * line for the rest of the visit. For a panel written for FIRST-time readers,
 * showing it again on a later visit is a very cheap mistake to make.
 *
 * ⚠ IT IS `open`, NOT CLOSED. A collapsed "how to read this" is read by exactly
 * the people who do not need it. The reader it was written for does not know
 * they are the reader it was written for.
 */

export function HowToRead({
  title,
  children,
}: {
  /** Written as a claim about the page, not as a label. */
  title: string;
  children: React.ReactNode;
}) {
  return (
    <details className="how-to-read" open>
      <summary className="how-to-read-summary">
        <span className="how-to-read-eyebrow">How to read this</span>
        <span className="how-to-read-title">{title}</span>
        <span className="how-to-read-toggle muted" aria-hidden="true" />
      </summary>
      <div className="how-to-read-body">{children}</div>
    </details>
  );
}

/**
 * One numbered step of an orientation.
 *
 * Numbered rather than bulleted because these are a reading ORDER — "start
 * here, then this, then that" — and a bullet list says the opposite: that the
 * items are peers you may take in any order.
 */
export function ReadStep({
  n,
  heading,
  children,
}: {
  n: number;
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <div className="read-step">
      <span className="read-step-n" aria-hidden="true">
        {n}
      </span>
      <div>
        <strong className="read-step-heading">{heading}</strong>
        <p className="read-step-body">{children}</p>
      </div>
    </div>
  );
}
