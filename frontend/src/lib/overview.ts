/**
 * The front door's reading: capability and cost, in a few seconds, honestly.
 *
 * ⚠ THIS IS THE MOST DANGEROUS MODULE IN THE PRODUCT, AND IT IS WORTH SAYING
 * WHY BEFORE READING THE CODE. Everywhere else in this app a reader meets a
 * number welded to its trust tell — you cannot see the score without seeing what
 * kind of evidence it is. This module deliberately hands them an INTERPRETATION
 * instead: "this one leads, this one is the buy." Most visitors will read that
 * and never click anything. For them, whatever these sentences say IS the
 * product, and it will be repeated in a department meeting without any of the
 * qualification that surrounds it here.
 *
 * Four rules follow from that, and every one of them is a test in
 * `tests/overview.test.ts`:
 *
 *   1. **NO UNIVERSAL "#1".** The overall score is an average across the
 *      outcomes we happen to have measured. A marketing professor and an
 *      accounting professor are not asking the same question, and a bare "best
 *      model" answers neither of them honestly. Every strength claim is scoped
 *      in its own label, and `scopeNudge` sends a reader who cares about their
 *      own field to the door that actually answers that.
 *   2. **THE HOOK IS EXPLANATIVE, NOT A RANK.** `bestAt` names the outcome a
 *      model is actually strongest on. "Leads on quantitative work" is a reason
 *      a reader can act on; "#1" is a number with no content in it.
 *   3. **NOTHING IS COMPUTED HERE.** Capability comes from `rollupByModel`, the
 *      plain sentence from `summariseBoard`, the money from `summariseValue`.
 *      This module arranges; it does not measure. A front door that disagreed
 *      with the leaderboard it links to would be the worst possible bug, so it
 *      is made structurally impossible rather than merely avoided.
 *   4. **SEEDED ROWS SAY SO.** `demonstration` is per row, so a board holding
 *      both seeded and measured results can describe itself accurately instead
 *      of picking one banner and being wrong about half the page.
 *
 * Pure functions, no React, no fetch.
 */

import { summariseBoard, type Findings } from "./findings";
import { formatScoreValue } from "./format";
import {
  confidenceLabel,
  isRanked,
  rollupByModel,
  rollupByOutcome,
  type ModelRollup,
} from "./rollup";
import type { Confidence, LeaderboardResponse } from "./types";
import { priceReadingFor, summariseValue, type PriceReading, type ValueSummary } from "./value";

/**
 * How many models the front door will introduce.
 *
 * Three is a read; six is a table, and a table is the page this one exists to
 * sit in front of. The rest are one click away and always were.
 */
const MAX_STANDOUTS = 3;

/**
 * The role a standout plays in the reader's decision.
 *
 * Deliberately about the READER's question ("what would I pick?") rather than
 * about position in a list. `only_measured` exists because a field of one is
 * not a contest, and labelling a lone model "strongest" implies we held one.
 */
export type StandoutRole = "strongest" | "value" | "free_on_campus" | "only_measured";

/** The outcome a model is actually best at, which is the interesting half. */
export interface BestAt {
  slo: string;
  /** `SLO2 · Quantitative Literacy` — matches how the tool pages head this row. */
  heading: string;
  /**
   * `Quantitative Literacy` — the outcome's own words, with the id stripped.
   *
   * ⚠ THE SENTENCE USES THIS, NOT `heading`, AND THAT IS THE WHOLE POINT OF THE
   * FIELD. "Strongest on SLO2 · Quantitative Literacy" opens the one sentence a
   * non-technical reader will actually read with an internal identifier. The id
   * is real and stays available for the tool pages that need it to line up with
   * a table; it just does not belong in prose aimed at someone who has never
   * heard the phrase "SLO".
   */
  title: string;
  score: number;
  confidence: Confidence;
}

export interface Standout {
  model_key: string;
  display_name: string;
  role: StandoutRole;
  /** The badge over the card. Always scoped — never a bare superlative. */
  roleLabel: string;
  /** One sentence a reader can act on, naming the strength AND the cost. */
  reading: string;
  score: number;
  confidence: Confidence;
  confidenceLabel: string;
  /**
   * Why that tier — always about the MEASUREMENT, never about the model.
   *
   * Carried so the card can never render a score without the sentence that
   * qualifies it; see `tests/overview.dom.test.tsx`.
   */
  confidenceReason: string;
  scored_samples: number;
  price: PriceReading;
  /** Null when nothing this model was measured on has an outcome attached. */
  bestAt: BestAt | null;
  /** The receipt: this model's full report card. */
  reportHref: string;
  /** True when every measurement behind this card was seeded, not measured. */
  demonstration: boolean;
}

export interface DemonstrationTell {
  /** At least one measurement on this board was seeded rather than measured. */
  any: boolean;
  /** EVERY measurement on this board was seeded. */
  all: boolean;
  seededModels: number;
  measuredModels: number;
  /** Reader-facing; empty string when there is nothing to disclose. */
  notice: string;
}

export interface Overview {
  /** The one sentence at the top. Always finished, always safe to quote alone. */
  headline: string;
  /** Up to three models, introduced by what they are good for. */
  standouts: Standout[];
  /** The "your field may differ" line. Always present; never optional. */
  scopeNudge: string;
  demonstration: DemonstrationTell;
  /** The plain-language findings this page must never contradict. */
  findings: Findings;
  value: ValueSummary;
  anyMeasured: boolean;
  /** How much of the programme this reading actually speaks to. */
  outcomesMeasured: number;
  outcomeCount: number;
}

/**
 * The outcome a model scored highest on, with the tell that qualifies it.
 *
 * ⚠ THE UNFILED ROW IS SKIPPED, AND IT SHIPPED ONCE WITHOUT BEING. `rollupByOutcome`
 * ends with an "Outside the SLO benchmark" bucket for the demo and exemplar
 * families — real measurements, correctly grouped, and a perfectly good row on a
 * report card. Fed into this page's one sentence it produced, live: "Luna is at
 * its strongest on Outside the SLO benchmark", which names no subject, reads as
 * a rendering fault, and is the first thing a professor would see.
 *
 * Returning `null` there is the honest answer: we cannot name a subject this
 * model is strongest at, because everything it was measured on sits outside the
 * outcome map. The caller falls back to a sentence that claims only what we have
 * — a score across the work we set it.
 *
 * ⚠ NOT CAUGHT BY ANY UNIT TEST, BECAUSE THE FIXTURES ALL TAG THEIR TASKS. It
 * took rendering the real page against the real API to see it, which is the
 * argument for doing that before calling a page finished.
 */
function bestOutcomeFor(rollup: ModelRollup, board: LeaderboardResponse): BestAt | null {
  let best: BestAt | null = null;
  for (const row of rollupByOutcome(rollup, board)) {
    if (row.slo === null) continue;
    // An unmeasured outcome contributes nothing. It is not a zero, and it is
    // certainly not a candidate for "what this model is best at".
    if (row.aggregate.score === null || row.aggregate.measured_tasks === 0) continue;
    if (best === null || row.aggregate.score > best.score) {
      best = {
        slo: row.slo,
        heading: row.heading,
        // The curriculum's own title when it is loaded; otherwise the id, which
        // is at least true. Never the heading, which carries the id as a prefix.
        title: row.outcome?.title ?? row.slo,
        score: row.aggregate.score,
        confidence: row.aggregate.confidence,
      };
    }
  }
  return best;
}

/** Whether every scored row behind a model was seeded. */
function isSeeded(rollup: ModelRollup): boolean {
  const scored = rollup.entries.filter(
    (e) => e.result.mean_score !== null && e.result.scored_count > 0,
  );
  return scored.length > 0 && scored.every((e) => e.result.demonstration);
}

/** How a model's cost reads in a sentence, without ever inventing a figure. */
function costClause(price: PriceReading): string {
  switch (price.kind) {
    case "free_on_campus":
      return "and it costs you nothing per use, because it runs on campus hardware";
    case "priced":
      return `and running a hundred answers through it costs about ${formatQuoteInline(price.usdPerHundredAnswers)}`;
    case "priced_unsized":
      return "though we have not run it enough to say what an answer costs";
    case "unpriced":
      return "though we have no published price for it";
  }
}

function formatQuoteInline(usd: number): string {
  if (usd <= 0) return "nothing";
  if (usd < 0.01) return "less than a cent";
  if (usd < 1) return `${(usd * 100).toFixed(0)}¢`;
  return `$${usd.toFixed(2)}`;
}

/**
 * Read a leaderboard response as a front door.
 *
 * Every figure below is lifted from `rollupByModel`, `summariseBoard` or
 * `summariseValue`. Nothing is measured here.
 */
export function buildOverview(board: LeaderboardResponse): Overview {
  const findings = summariseBoard(board);
  const value = summariseValue(board);

  const rollups = rollupByModel(board);
  // ⚠ `isRanked` IS THE STUB FILTER, and it is the only one. A deterministic
  // mock scores 1.00 by construction; a front door whose headline card is an
  // echo server is the most embarrassing thing this project could publish.
  const ranked = rollups.filter(isRanked);

  const outcomeCount = board.curriculum.available
    ? board.curriculum.outcomes.length
    : board.slos.length;

  /* ------------------------------------------------- the demonstration tell */
  const seededModels = ranked.filter(isSeeded).length;
  const measuredModels = ranked.length - seededModels;
  const anySeeded = seededModels > 0;
  const allSeeded = anySeeded && measuredModels === 0;

  let notice = "";
  if (allSeeded) {
    notice =
      "Everything on this page is illustrative. These results were generated to show what the " +
      "finished benchmark looks like — no model has actually been measured in this deployment yet. " +
      "The full benchmark is in progress, and these numbers will be replaced by real ones.";
  } else if (anySeeded) {
    // ⚠ AGREEMENT, NOT PEDANTRY. "1 of the 2 models here have been measured"
    // is the sentence that shipped, and it reads as machine-generated on the one
    // paragraph whose entire job is to be believed.
    const verb = measuredModels === 1 ? "has" : "have";
    const rest = ranked.length - measuredModels === 1 ? "the other is an" : "the rest are";
    notice =
      `Some of this is illustrative. ${measuredModels} of the ${ranked.length} models here ${verb} been ` +
      `genuinely measured; ${rest} example ${rest.endsWith("an") ? "result" : "results"}, generated to show the shape of ` +
      `the finished benchmark. Each card says which kind it is.`;
  }

  const demonstration: DemonstrationTell = {
    any: anySeeded,
    all: allSeeded,
    seededModels,
    measuredModels,
    notice,
  };

  /* ------------------------------------------------------------- no data yet */
  if (ranked.length === 0) {
    return {
      headline:
        "We have not measured anything we would stand behind yet — so rather than fill this page " +
        "with a placeholder, it says so.",
      standouts: [],
      scopeNudge:
        "When results do land, they will be an average across the outcomes we tested. Your own " +
        "subject may look different, which is what the recommendation walkthrough is for.",
      demonstration,
      findings,
      value,
      anyMeasured: false,
      outcomesMeasured: findings.coverage.outcomesMeasured,
      outcomeCount,
    };
  }

  /* ------------------------------------------------------------- standouts */
  const [leader] = ranked;
  const picked: Standout[] = [];
  const seen = new Set<string>();

  function push(rollup: ModelRollup, role: StandoutRole, roleLabel: string) {
    if (seen.has(rollup.model_key) || picked.length >= MAX_STANDOUTS) return;
    seen.add(rollup.model_key);

    const price = priceReadingFor(rollup);
    const bestAt = bestOutcomeFor(rollup, board);
    const score = rollup.overall.score ?? 0;

    const strengthClause =
      bestAt === null
        ? `scores ${formatScoreValue(score)} out of 1.00 across the work we set it`
        : `is at its strongest on ${bestAt.title} (${formatScoreValue(bestAt.score)} out of 1.00)`;

    picked.push({
      model_key: rollup.model_key,
      display_name: rollup.display_name,
      role,
      roleLabel,
      reading: `${rollup.display_name} ${strengthClause}, ${costClause(price)}.`,
      score,
      confidence: rollup.overall.confidence,
      confidenceLabel: confidenceLabel(rollup.overall.confidence),
      confidenceReason:
        `Based on ${rollup.overall.scored_samples} scored ` +
        `${rollup.overall.scored_samples === 1 ? "answer" : "answers"} across ` +
        `${rollup.overall.measured_tasks} of the ${rollup.overall.covered_tasks} ` +
        `${rollup.overall.covered_tasks === 1 ? "task" : "tasks"} we set it. ` +
        (rollup.overall.verifiable_share < 0.5
          ? "Most of it was marked by another AI against a written guide, not checked by a program."
          : "Most of it was checked by a program against a known answer."),
      scored_samples: rollup.overall.scored_samples,
      price,
      bestAt,
      reportHref: `/models/${encodeURIComponent(rollup.model_key)}`,
      demonstration: isSeeded(rollup),
    });
  }

  if (leader) {
    // ⚠ THE LABEL IS SCOPED IN BOTH BRANCHES. With one model there was no
    // contest, so nothing may imply one was won; with several, the claim is
    // still only about the outcomes we measured.
    if (ranked.length === 1) {
      push(leader, "only_measured", "The one model we have measured so far");
    } else {
      push(leader, "strongest", "Strongest overall on what we have measured");
    }
  }

  // The value pick, when `summariseValue` was willing to name one. It applies
  // its own three tests (cheap enough, close enough, not a stub) and returns
  // null rather than reaching — so this trusts it and never second-guesses.
  const pick = value.valuePick;
  if (pick) {
    const pickRollup = ranked.find((r) => r.model_key === pick.model_key);
    if (pickRollup) {
      const free = priceReadingFor(pickRollup).kind === "free_on_campus";
      push(
        pickRollup,
        free ? "free_on_campus" : "value",
        free ? "Free to you, and keeps up" : "The better buy, if cost matters",
      );
    }
  }

  // Fill any remaining slot with the next-strongest model, so a reader sees the
  // shape of the field rather than only its extremes.
  for (const rollup of ranked) {
    if (picked.length >= MAX_STANDOUTS) break;
    push(rollup, "strongest", "Also measured");
  }

  /* -------------------------------------------------------------- headline */
  // ⚠ THE VALUE SENTENCE IS THE HEADLINE WHEN THERE IS ONE, because the cost
  // half is the part no other page in the product answers, and it is the half
  // that decides whether a professor can actually act on any of this.
  const headline = value.headline;

  const scopeNudge =
    ranked.length === 1
      ? "This is an average across the outcomes we have tested so far, in one programme. Your own " +
        "course may look very different — the recommendation walkthrough asks what you teach before it answers."
      : "These are averages across the outcomes we have tested. A model that leads overall can still be " +
        "the wrong pick for your subject — a strong result in accounting says nothing about marketing. " +
        "If your own field is what you care about, start there instead.";

  return {
    headline,
    standouts: picked,
    scopeNudge,
    demonstration,
    findings,
    value,
    anyMeasured: true,
    outcomesMeasured: findings.coverage.outcomesMeasured,
    outcomeCount,
  };
}
