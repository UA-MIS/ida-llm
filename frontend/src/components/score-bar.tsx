/**
 * A score, drawn as a number and a bar.
 *
 * The bar is DELIBERATELY NOT COLOUR-CODED by value. A red-to-green ramp would
 * turn a 0.55 into a verdict, and this benchmark's scores are means over small
 * samples with a stated confidence — the confidence meter is where the
 * good/bad-ish signal is allowed to live, and it is about the measurement, not
 * the model. The bar exists only to make two numbers comparable at a glance.
 *
 * ⚠ A NULL SCORE HAS NO BAR AT ALL. A zero-width bar is a bar, and a bar reads
 * as "measured, scored badly". Unmeasured renders as an em-dash and a reason.
 */

import { formatScore } from "@/lib/format";

export function ScoreBar({
  score,
  note,
  size = "normal",
}: {
  score: number | null;
  /** What to say instead of a bar when there is no score. */
  note?: string;
  size?: "normal" | "large";
}) {
  if (score === null) {
    return (
      <div className={`scorebar scorebar-${size}`}>
        <div className="scorebar-value muted">—</div>
        {note ? <div className="scorebar-note muted">{note}</div> : null}
      </div>
    );
  }
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return (
    <div className={`scorebar scorebar-${size}`}>
      <div className="scorebar-value">{formatScore(score)}</div>
      <div
        className="scorebar-track"
        role="img"
        aria-label={`${formatScore(score)} out of 1.00`}
      >
        <div className="scorebar-fill" style={{ width: `${pct}%` }} />
      </div>
      {note ? <div className="scorebar-note muted">{note}</div> : null}
    </div>
  );
}
