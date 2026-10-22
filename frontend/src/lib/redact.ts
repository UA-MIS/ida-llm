/**
 * Strip question/answer content from a run before the page ever holds it.
 *
 * ⚠ SECURITY-TOUCHING. We cannot publish the benchmark's questions, the models'
 * answers or the answer key. A run's results carry them in places that look
 * harmless: `score.explanation` prints "got 'X', want 'Y'" (the model's answer
 * AND the gold answer), `score.details` stores the normalised target, a judge's
 * `criteria[].explanation` quotes the answer, a sample `error` can echo the
 * request, and `transcript_uri` / `archive_error` point at the archive.
 *
 * The evidence page does not render any of that — but not rendering is one edit
 * away from rendering, and in `next dev` React serialises server-component props
 * into the page payload. So the page redacts at the door: after this, the
 * content is not in memory to leak, whatever a later change renders or whichever
 * component receives it. What survives is exactly what the page shows: the
 * verdict, the score, and the numbers.
 */

import type { ResultRecord, RunDetail } from "./types";

export function redactResult(result: ResultRecord): ResultRecord {
  return {
    ...result,
    score: result.score
      ? { ...result.score, explanation: "", criteria: [], details: {} }
      : null,
    // Kept as a flag, because the outcome classifier reads `error !== null`; the
    // text itself is dropped.
    error: result.error === null ? null : "attempt failed",
    transcript_uri: null,
    archive_error: null,
  };
}

export function redactRun(detail: RunDetail): RunDetail {
  return {
    run: { ...detail.run, error: detail.run.error === null ? null : "run failed" },
    results: detail.results.map(redactResult),
  };
}
