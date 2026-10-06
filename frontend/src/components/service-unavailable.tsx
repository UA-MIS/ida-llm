/**
 * What a professor sees when the API is down.
 *
 * ⚠ AN OUTAGE IS A SOCIAL EVENT ON THIS SITE, NOT JUST A TECHNICAL ONE. The
 * reader this product has to win over is a professor who does not work with AI,
 * has been told to have a position on it, and has agreed — once — to give a
 * benchmark ten minutes. A raw 500 with a stack trace tells that reader "this
 * whole thing is broken, and probably always was". They do not come back, and
 * no amount of correct benchmarking later recovers them. The identical outage
 * behind a calm sentence says "come back in a minute", which is both kinder and
 * more accurate.
 *
 * ⚠ THE HARD PART IS NOT BEING SOOTHING, IT IS NOT OVERCLAIMING WHILE BEING
 * SOOTHING. The obvious copy here is "don't worry, your data is safe" — and we
 * cannot say that. If the API is unreachable we cannot see the database either,
 * so that sentence would be a confident claim made from no evidence, on a site
 * whose entire argument is that it refuses to do exactly that. What we can
 * honestly say is narrower and still reassuring: this is our end, not yours,
 * and it is usually temporary. `tests/unavailable.dom.test.tsx` pins the
 * absence of the reassurance we have not earned.
 *
 * ⚠ IT IS NOT THE EMPTY STATE, AND MUST NEVER LOOK LIKE IT. "Nothing has been
 * measured against this outcome yet" is a FINDING — one this project is proud
 * of publishing. "We cannot reach the results" is a FAULT. Dressing the fault
 * in the finding's clothes would tell a professor the benchmark is emptier than
 * it is: the same class of dishonesty as inventing a number, pointing the other
 * way.
 *
 * ⚠ THE CAUSE IS HIDDEN, NOT DELETED. An operator hitting this page needs the
 * real message, and trading their blindness for the professor's comfort is a
 * bad trade when a closed `<details>` serves both. Native disclosure, no
 * JavaScript — the same reasoning as everything else in this layer.
 */

import Link from "next/link";

/** The technical message, if the thrown thing had one we can trust. */
function causeMessage(cause: unknown): string | null {
  if (cause instanceof Error && cause.message) return cause.message;
  if (typeof cause === "string" && cause.trim()) return cause;
  return null;
}

export function ResultsUnavailable({
  what,
  retryHref,
  cause,
  singular = false,
}: {
  /** What could not be loaded, as a noun phrase: "the benchmark results". */
  what: string;
  /** This page's own path — the retry link, so a reload is one click. */
  retryHref: string;
  cause?: unknown;
  /** True when `what` names one thing ("the comparison grid"), for the verb. */
  singular?: boolean;
}) {
  const detail = causeMessage(cause);

  return (
    <div className="unavailable">
      {/* ⚠ THE VERB IS A PROP BECAUSE IT WAS WRONG HALF THE TIME. The heading
          was built as {what} + " are temporarily unavailable", which works for
          "the benchmark results" and produced "The comparison grid are
          temporarily unavailable" for the other caller. A grammar error is a
          small thing anywhere except here: this is the page whose whole job is
          to look like the site is in careful hands while something is broken. */}
      <h2 className="unavailable-heading">
        {what[0]?.toUpperCase()}
        {what.slice(1)} {singular ? "is" : "are"} temporarily unavailable
      </h2>

      <p className="unavailable-lede">
        We could not load them just now. This is a problem at our end — nothing
        you did caused it, and it is usually short-lived.
      </p>

      {/* ⚠ A PLAIN <a>, NOT `next/link`, AND THAT IS THE WHOLE POINT OF THE
          BUTTON. This link points at the route the reader is already on, so the
          App Router was free to satisfy it from the client cache — serving back
          the same failed render without ever re-hitting the server. A button
          labelled "Try again" that does not try again is worse than no button.
          A full navigation always reaches the server. */}
      <p className="unavailable-next">
        <a href={retryHref} className="cta">
          Try again
        </a>
      </p>

      {/* ⚠ ONLY `/` IS OFFERED, AND THAT IS DELIBERATE. Every other page on this
          site needs the same API this one just failed to reach, so sending a
          reader to `/models` or `/runs` would be sending them to a second
          failure. The landing page catches its own errors and still makes its
          whole argument without them — it is the one honest destination. */}
      <p className="unavailable-alt muted">
        In the meantime, <Link href="/">the introduction</Link> explains what
        this benchmark measures and how it works — that page does not depend on
        anything that is currently down.
      </p>

      {detail ? (
        <details className="unavailable-cause">
          <summary className="muted">Technical detail, for whoever is on call</summary>
          <p className="mono unavailable-detail">{detail}</p>
        </details>
      ) : null}
    </div>
  );
}
