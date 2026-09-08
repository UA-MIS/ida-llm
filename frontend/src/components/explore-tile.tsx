/**
 * One cell of a drill-down grid.
 *
 * Every level of `/explore` is the same object drawn three times over: a name,
 * one number, and the honest reason there is or is not a number. Sharing the
 * component is what keeps the three grids reading as one flow rather than three
 * pages that happen to be linked.
 *
 * ⚠ THE STATUS IS NOT DECORATION AND IT IS NEVER INFERRED FROM THE SCORE. A
 * tile with no score is one of two completely different claims — "nothing has
 * been run for this yet" or "the curriculum says a text benchmark cannot measure
 * this at all" — and `lib/explore.ts` decides which. Collapsing them here, or
 * drawing either as a blank, would put a zero in a reader's head where the data
 * has none. That is the failure this whole product is a response to.
 *
 * ⚠ EVERY SCORE KEEPS ITS CONFIDENCE TELL, at every width. `tests/breakpoints.
 * test.ts` pins the rule for the leaderboard's trust column and states the
 * principle: confidence is not detail a narrow screen may drop, it is the
 * difference between a reading and a verdict.
 */

import Link from "next/link";

import { ConfidenceTell } from "@/components/trust-badges";
import { formatScore } from "@/lib/format";
import { NOT_MEASURED, NOT_TEXT_MEASURABLE, type ExploreStatus } from "@/lib/explore";
import { confidenceLabel } from "@/lib/rollup";
import type { ScoreAggregate } from "@/lib/rollup";

export function ExploreTile({
  href,
  eyebrow,
  heading,
  status,
  aggregate,
  reason,
  footnote,
  badges,
}: {
  href: string;
  /** The small line above the name — a course code, an outcome id. */
  eyebrow?: string;
  heading: string;
  status: ExploreStatus;
  aggregate: ScoreAggregate;
  /** Why there is (or is not) a number. Always shown, never a tooltip only. */
  reason: string;
  /** Optional extra line under the reason — coverage, a level, a count. */
  footnote?: React.ReactNode;
  badges?: React.ReactNode;
}) {
  const measured = status === "measured" && aggregate.score !== null;

  return (
    <li className={`xp-tile xp-tile-${status}`}>
      <Link href={href} className="xp-tile-link">
        <span className="xp-tile-head">
          {eyebrow ? <span className="xp-tile-eyebrow">{eyebrow}</span> : null}
          <span className="xp-tile-heading">{heading}</span>
        </span>

        <span className="xp-tile-read">
          {measured ? (
            <>
              <span className="xp-tile-score">{formatScore(aggregate.score)}</span>
              {/* Never optional, never dropped at a breakpoint: the number and
                  how much it can bear travel together or not at all. */}
              <span className="xp-tile-confidence">
                <ConfidenceTell
                  confidence={aggregate.confidence}
                  label={confidenceLabel(aggregate.confidence)}
                  reason={`${confidenceLabel(aggregate.confidence)}. How much weight this number can bear — how it was marked, over how many attempts, and whether anything failed. It is about the measurement, not about the model.`}
                />
              </span>
            </>
          ) : (
            <span className="xp-tile-empty">
              {/* A dash AND the words. The dash alone is a blank; the words
                  alone lose the visual parity with the tiles that do have a
                  number, and a reader scanning a grid reads shape first. */}
              <span className="xp-tile-dash" aria-hidden="true">
                —
              </span>
              <span className="xp-tile-empty-label">
                {status === "not_benchmarkable" ? NOT_TEXT_MEASURABLE : NOT_MEASURED}
              </span>
            </span>
          )}
        </span>

        <span className="xp-tile-reason muted">{reason}</span>
        {footnote ? <span className="xp-tile-foot muted">{footnote}</span> : null}
        {badges ? <span className="xp-tile-badges">{badges}</span> : null}

        <span className="xp-tile-go" aria-hidden="true">
          →
        </span>
      </Link>
    </li>
  );
}
