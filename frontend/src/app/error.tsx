"use client";

/**
 * The error boundary for the whole app — the last thing between a failure and
 * the reader.
 *
 * ⚠ THIS FILE WAS THE RAW 500. `/leaderboard` and `/compare` now catch their
 * own API failures and render `ResultsUnavailable` instead, but every other
 * route still lands here, and what it used to show was `error.message` in
 * monospace above an instruction to run `make dev`. That is a developer's error
 * page, and it was written when the only people loading this site were the
 * people building it. Shown to a history professor who has never used a chatbot,
 * a stack trace over a shell command reads as "this whole thing is broken" —
 * from which they do not return.
 *
 * ⚠ IN PRODUCTION THERE IS USUALLY NOTHING WORTH SHOWING ANYWAY. Next.js
 * replaces a server error's `message` with a generic string plus a `digest` on
 * the client, precisely so internals do not leak. So the old layout gave a
 * professor an alarming monospace block that, in the deployment that matters,
 * did not even contain the information it was alarming about.
 *
 * The register is the same as `components/service-unavailable.tsx`: say what
 * happened in a sentence, say it is our end, give one obvious action, and put
 * the technical detail behind a disclosure for whoever is on call. The `digest`
 * goes in there too — it is the string that finds this in the server logs, and
 * it is useless to everyone else.
 */

import Link from "next/link";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="unavailable">
      <h2 className="unavailable-heading">This page is temporarily unavailable</h2>

      <p className="unavailable-lede">
        Something went wrong at our end while loading it. Nothing you did caused
        this, and it is usually short-lived.
      </p>

      <p className="unavailable-next">
        {/* `reset()` re-renders the segment, which is a truer retry than a
            reload — and it is why this file stays a client component. */}
        <button onClick={reset}>Try again</button>
      </p>

      <p className="unavailable-alt muted">
        If it keeps happening, <Link href="/">the introduction</Link> explains
        what this benchmark measures without needing anything that is currently
        down.
      </p>

      <details className="unavailable-cause">
        <summary className="muted">Technical detail, for whoever is on call</summary>
        <p className="mono unavailable-detail">
          {error.message}
          {error.digest ? ` (digest ${error.digest})` : ""}
        </p>
        <p className="unavailable-detail">
          Running locally? If the API is not reachable, start the stack with{" "}
          <code className="mono">make dev</code> and reload.
        </p>
      </details>
    </div>
  );
}
