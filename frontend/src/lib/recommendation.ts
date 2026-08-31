/**
 * What a recommendation is allowed to say without a caveat: nothing.
 *
 * ⚠ THE RULE THE REST OF THE PRODUCT ALREADY KEEPS. `lib/findings.ts` returns
 * its headline and its caveats together and the summary renders them together,
 * so there is no code path that produces a bare claim. The recommendation card
 * was the exception: it gated its entire "what to know before you rely on this"
 * panel on `caveats.length > 0`, and the API only appends caveats for
 * unscorable tasks, errored samples and partial scoring.
 *
 * ⚠ SO THE FAILURE LANDED AT THE WORST POSSIBLE MOMENT. A verifiable result
 * with four scored samples is assigned *low* confidence by the API and no
 * caveat at all — the tier is lowered but the reason is never written down. The
 * card then rendered a confident headline, a clean score, and no qualification
 * whatsoever. The strongest-looking output in the product, produced by the
 * weakest evidence in it.
 *
 * ⚠ THIS FILE DOES NOT SOFTEN THE ANSWER, IT NAMES ITS EVIDENCE. Every caveat
 * added below is computed from the receipts the API already returned — how many
 * attempts were scored, and the weakest confidence among them. Nothing is
 * invented, and a genuinely well-evidenced recommendation gets exactly one
 * closing line rather than a wall of hedging.
 */

import type { Confidence, Recommendation, Receipt } from "./types";
import { plainCaveats } from "./plain";

/**
 * Below this many scored attempts behind an answer, it is a hint rather than a
 * finding.
 *
 * Five is the API's own threshold for lifting a verifiable measurement out of
 * "low confidence — thin evidence" (`VERIFIABLE_HIGH_CONFIDENCE_SAMPLES` in
 * services/api/ida_api/trust.py). Matching it means the card and the badge
 * never disagree about whether the evidence was thin.
 */
export const THIN_EVIDENCE_SAMPLES = 5;

const WEAKEST_FIRST: Confidence[] = ["none", "low", "moderate", "high"];

/** The weakest confidence behind an answer — never the average, never the best. */
export function weakestConfidence(receipts: readonly Receipt[]): Confidence | null {
  if (receipts.length === 0) return null;
  for (const tier of WEAKEST_FIRST) {
    if (receipts.some((receipt) => receipt.confidence === tier)) return tier;
  }
  return null;
}

/** Total scored attempts behind an answer, across every receipt. */
export function scoredAttempts(receipts: readonly Receipt[]): number {
  return receipts.reduce((total, receipt) => total + receipt.scored_count, 0);
}

export interface EvidenceStanding {
  receiptCount: number;
  scoredAttempts: number;
  confidence: Confidence | null;
  /** True when the answer rests on too little to be treated as a finding. */
  thin: boolean;
}

export function evidenceStanding(recommendation: Recommendation): EvidenceStanding {
  const receipts = recommendation.receipts;
  const attempts = scoredAttempts(receipts);
  const confidence = weakestConfidence(receipts);
  return {
    receiptCount: receipts.length,
    scoredAttempts: attempts,
    confidence,
    thin:
      receipts.length === 0 ||
      attempts < THIN_EVIDENCE_SAMPLES ||
      confidence === "low" ||
      confidence === "none",
  };
}

/** Whether an existing caveat already makes the thin-evidence point. */
function alreadySaysThin(caveats: readonly string[]): boolean {
  return caveats.some((caveat) => /thin|hold (?:it|them|these) loosely|too few/i.test(caveat));
}

/**
 * The caveats a recommendation card must render — **never an empty list.**
 *
 * The closing line is unconditional on purpose. It is the honest floor of what
 * a benchmark average can promise about one professor's next assignment, and
 * making it unconditional is what lets the card render the panel unconditionally
 * — which is the actual fix. A panel that can disappear is a panel that will
 * disappear exactly when the evidence is thinnest.
 */
export function displayCaveats(recommendation: Recommendation): string[] {
  const caveats = plainCaveats(recommendation.caveats);
  const standing = evidenceStanding(recommendation);

  if (standing.receiptCount === 0) {
    caveats.unshift(
      "There is no measured run behind this answer — it follows from what you told us " +
        "and from what the registry says about the models, not from anything we have " +
        "graded. Treat it as a starting point, not a finding.",
    );
  } else if (standing.thin && !alreadySaysThin(caveats)) {
    caveats.unshift(
      `This rests on thin evidence — ${plural(standing.scoredAttempts, "scored attempt")} ` +
        `across ${plural(standing.receiptCount, "piece", "pieces")} of work. ` +
        `A few more attempts could move it, so treat it as a hint rather than a verdict.`,
    );
  }

  caveats.push(
    "These are averages over the work we have measured, not a guarantee on any single " +
      "assignment of yours. The runs behind them are linked above — the point of them " +
      "is that you can check.",
  );

  return caveats;
}

function plural(count: number, one: string, many?: string): string {
  return `${count} ${count === 1 ? one : (many ?? `${one}s`)}`;
}
