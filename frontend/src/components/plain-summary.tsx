/**
 * "What we found" — the human answer, above everything else on the page.
 *
 * ⚠ THE SHAPE IS THE REQUIREMENT: short, then visual, then full detail on
 * demand. A professor who reads only the first paragraph must leave with a true
 * impression; one who wants the picture gets it without a table; one who wants
 * everything scrolls on. Each layer is a superset of the one above, never a
 * different story.
 *
 *   1. ONE paragraph. The honest takeaway, in words, quotable on its own.
 *   2. The caveats, immediately beneath it and never behind a toggle — see
 *      `lib/findings.ts` for why they are part of the claim rather than a
 *      footnote.
 *   3. A compact podium: the top few models as bars. This is the "visual"
 *      layer, and it exists because a bar chart answers "how far apart are
 *      they?" in a way a column of decimals does not.
 *   4. Everything else — the full ranking, the catalogue — below, unchanged.
 *
 * ⚠ THE PODIUM SHOWS RANKED MODELS ONLY. `isRanked` excludes test stubs and
 * unscored models, and this component never looks past it. A stub returns a
 * fixed answer, scores near-perfectly, and would take the tallest bar on the
 * page — a lie told in a chart rather than in a sentence, which is worse
 * because nobody reads a chart sceptically.
 *
 * ⚠ NO COLOUR RAMP ON THE BARS. `components/score-bar.tsx` spells out the
 * reasoning: a red-to-green scale turns a 0.55 into a verdict, and these are
 * small-sample means with a stated confidence. The bars encode length only.
 */

import Link from "next/link";

import { ScoreBar } from "@/components/score-bar";
import { ConfidenceTell } from "@/components/trust-badges";
import type { Findings } from "@/lib/findings";
import { confidenceLabel, isRanked, type ModelRollup } from "@/lib/rollup";

/** How many bars before the picture stops being a picture and becomes a table. */
const PODIUM_SIZE = 5;

function Podium({ rollups }: { rollups: ModelRollup[] }) {
  const ranked = rollups.filter(isRanked).slice(0, PODIUM_SIZE);
  if (ranked.length === 0) return null;

  return (
    <div className="podium">
      {/* ⚠ NO INLINE "?" IN THIS LABEL, DELIBERATELY. The label is set in small
          caps, and a superscript "?" at the end of a line of capitals does not
          read as an affordance — it reads as a question mark, turning a heading
          into a question the page then fails to answer. "Overall score" is
          defined in the panel note above the ranked table and in the glossary;
          it does not need a third, worse, affordance here. */}
      <p className="podium-label muted">Every model we have measured, by overall score</p>
      <ol className="podium-list">
        {ranked.map((rollup, index) => (
          <li key={rollup.model_key} className="podium-row">
            <span className="podium-rank mono muted" aria-hidden="true">
              {index + 1}
            </span>
            <Link
              href={`/models/${encodeURIComponent(rollup.model_key)}`}
              className="podium-name"
            >
              {rollup.display_name}
            </Link>
            <div className="podium-bar">
              <ScoreBar
                score={rollup.overall.score}
                note={`${rollup.overall.scored_samples} scored attempt${
                  rollup.overall.scored_samples === 1 ? "" : "s"
                } · ${rollup.overall.measured_tasks} piece${
                  rollup.overall.measured_tasks === 1 ? "" : "s"
                } of work`}
              />
            </div>
            <div className="podium-confidence">
              <ConfidenceTell
                confidence={rollup.overall.confidence}
                label={confidenceLabel(rollup.overall.confidence)}
                reason="How much weight this number can bear — how it was marked, over how many attempts, and whether anything failed. It is about the measurement, not about the model."
              />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function PlainSummary({
  findings,
  rollups,
}: {
  findings: Findings;
  rollups: ModelRollup[];
}) {
  return (
    <section className="plain-summary" aria-labelledby="what-we-found">
      <h2 id="what-we-found" className="plain-summary-heading">
        What we found so far
      </h2>

      {/* Layer 1: the sentence. Set large, because it is the thing most readers
          will take away and the only thing some of them will read. */}
      <p className="plain-summary-lede">{findings.headline}</p>

      {/* Layer 2: the qualifiers. Quiet, but never collapsed — a headline whose
          caveats are behind a toggle is a headline that will be quoted alone. */}
      <ul className="plain-summary-caveats">
        {findings.caveats.map((caveat) => (
          <li key={caveat}>{caveat}</li>
        ))}
      </ul>

      {/* Layer 3: the picture. */}
      <Podium rollups={rollups} />

      {findings.leader ? (
        <p className="plain-summary-next">
          Want the detail?{" "}
          <Link href={`/models/${encodeURIComponent(findings.leader.model_key)}`}>
            Open {findings.leader.display_name}&rsquo;s report card
          </Link>{" "}
          to see it outcome by outcome, or read the full ranking below.{" "}
          <Link href="/recommend">
            If you would rather just be told what to use, answer a few questions instead
          </Link>
          .
        </p>
      ) : (
        <p className="plain-summary-next">
          <Link href="/recommend">
            The recommendation questions still work
          </Link>{" "}
          — and with nothing measured, they will tell you so honestly rather than
          guess.
        </p>
      )}
    </section>
  );
}
