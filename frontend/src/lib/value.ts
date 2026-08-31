/**
 * The value axis: capability set against what a reader would actually pay.
 *
 * ⚠ THIS MODULE EXISTS BECAUSE "AFFORDABLE" IS THE SECOND QUESTION EVERY READER
 * ASKS AND THE ONE THE BENCHMARK HAS NEVER ANSWERED. A professor deciding
 * whether to use a model, or to let students use one, is not choosing between
 * research budgets — they are asking whether this is a few dollars a semester or
 * a line item they have to defend. A results page that reports only capability
 * has answered half the question and left the half that decides the outcome.
 *
 * ⚠ THE FIELD IT MUST NOT USE IS THE OBVIOUS ONE. `ModelResult.total_cost_usd`
 * is OUR measurement spend: it scales with how many samples we chose to run, it
 * is `0` on a cache hit, and it is `0` for every row `tools/seed_dev_benchmark.py`
 * writes. Dividing it by the scored count and calling the answer "cost per
 * answer" describes our benchmark rather than the model — and in any seeded
 * environment it renders EVERY model as free, which is both the most persuasive
 * and the most false sentence this page could print. The price here comes from
 * `ModelResult.price`, the registry's published rate card, which is what the
 * provider actually bills.
 *
 * ⚠ THE FOUR READINGS ARE NOT INTERCHANGEABLE, AND COLLAPSING ANY TWO IS A LIE:
 *
 *   `free_on_campus`  — costs nothing BECAUSE the university owns the hardware.
 *                       Genuinely free to the reader. Never expressed as a
 *                       capability-per-dollar ratio: that division is undefined,
 *                       and "infinitely good value" is not a finding.
 *   `priced`          — a rate card AND enough token accounting to turn it into
 *                       a figure a person can hold.
 *   `priced_unsized`  — a rate card but no recorded tokens. We know it bills and
 *                       cannot say how much. Saying "$0.00" here would be the
 *                       zero-spend bug wearing a different hat.
 *   `unpriced`        — not in the registry at all. `null` price is not a zero
 *                       price; we simply have nothing to quote.
 *
 * ⚠ EVERY COMPARATIVE IS EARNED, ON THE SAME TERMS AS `lib/findings.ts`. A
 * "value pick" requires two ranked models, a price gap wide enough to matter,
 * AND capability close enough that the cheaper one is genuinely an alternative
 * rather than a worse product. Cheap-and-much-worse is not a bargain. And a test
 * stub — free, deterministic, scores 1.00 — can never be named, which is what
 * `isRanked` is doing in the one filter below.
 *
 * Pure functions, no React, no fetch: every rule above is testable without
 * rendering anything.
 */

import { formatScoreValue } from "./format";
import { isRanked, rollupByModel, type ModelRollup } from "./rollup";
import type { CostNote, LeaderboardResponse, TokenUsage } from "./types";

/**
 * How many times cheaper one model must be before we will call it cheaper.
 *
 * ⚠ A RATIO, NOT A DIFFERENCE, and deliberately blunt. These figures are
 * fractions of a cent; an absolute threshold would either fire on everything or
 * on nothing depending on the tier of model in the field. 2× is wide enough that
 * it survives the modelling assumptions underneath it — a different mix of
 * prompt lengths would not flip a 2× gap, and might easily flip a 1.2× one.
 */
const MEANINGFUL_PRICE_RATIO = 2;

/**
 * How far behind on capability a cheaper model may be and still be a "buy".
 *
 * Deliberately the SAME 0.05 `lib/findings.ts` uses to decide two models are
 * level. Two thresholds for "is this difference real?" on one page would let the
 * value panel call a gap meaningful while the summary above it called the same
 * gap a tie.
 */
const MEANINGFUL_GAP = 0.05;

/** The unit a reader can actually picture. A hundred marked answers is a class. */
export const ANSWERS_PER_QUOTE = 100;

export type PriceReading =
  | {
      kind: "free_on_campus";
      note: CostNote;
      /** Reader-facing, already a sentence. */
      label: string;
    }
  | {
      kind: "priced";
      note: CostNote;
      label: string;
      /** USD for `ANSWERS_PER_QUOTE` answers of the length we actually observed. */
      usdPerHundredAnswers: number;
      /** Mean tokens in one answer, prompt + completion. The modelling input. */
      tokensPerAnswer: number;
    }
  | { kind: "priced_unsized"; note: CostNote; label: string }
  | { kind: "unpriced"; label: string };

/**
 * What `ANSWERS_PER_QUOTE` answers cost under a rate card.
 *
 * `usage` is the model's TOTAL token accounting across everything it was
 * measured on and `scoredSamples` is how many answers produced that total, so
 * the division is an observed average rather than an assumed answer length.
 * Rates are per MILLION tokens, which is where the 1e6 goes.
 */
export function usdPerHundredAnswers(
  usage: TokenUsage,
  scoredSamples: number,
  note: CostNote,
): number {
  if (scoredSamples <= 0) return 0;
  const promptPer = usage.prompt_tokens / scoredSamples;
  const completionPer = usage.completion_tokens / scoredSamples;
  const perAnswer =
    (promptPer * note.input_usd_per_mtok + completionPer * note.output_usd_per_mtok) / 1_000_000;
  return perAnswer * ANSWERS_PER_QUOTE;
}

/** Total tokens a model accumulated across every task it was measured on. */
function usageOf(rollup: ModelRollup): TokenUsage {
  let prompt = 0;
  let completion = 0;
  for (const entry of rollup.entries) {
    // A row that produced no score contributed no answer, so its tokens must
    // not enter an average whose denominator is scored answers.
    if (entry.result.mean_score === null || entry.result.scored_count <= 0) continue;
    prompt += entry.result.usage.prompt_tokens;
    completion += entry.result.usage.completion_tokens;
  }
  return { prompt_tokens: prompt, completion_tokens: completion };
}

/**
 * The rate card to quote for a model.
 *
 * Taken from the model's NEWEST row, matching how `rollupByModel` picks every
 * other identity field: the registry can be edited between runs, and the newest
 * row reflects the registry a reader would see today.
 */
function priceOf(rollup: ModelRollup): CostNote | null {
  if (rollup.entries.length === 0) return null;
  const newest = rollup.entries.reduce((best, entry) =>
    (entry.result.measured_at ?? "") > (best.result.measured_at ?? "") ? entry : best,
  );
  return newest.result.price;
}

/** Money, at the scale these figures actually live on. */
export function formatQuote(usd: number): string {
  if (usd <= 0) return "$0.00";
  if (usd < 0.01) return "less than a cent";
  if (usd < 1) return `${(usd * 100).toFixed(0)}¢`;
  return `$${usd.toFixed(2)}`;
}

/** How one model's cost should be described, and whether it can be at all. */
export function priceReadingFor(rollup: ModelRollup): PriceReading {
  const note = priceOf(rollup);

  if (note === null) {
    return {
      kind: "unpriced",
      label: "No published price — this model is not in our registry.",
    };
  }

  if (note.tier === "campus_hosted") {
    return { kind: "free_on_campus", note, label: note.label };
  }

  // A third-party model with no rates recorded is NOT free; nobody filled the
  // field in. `tier: "free"` is the registry saying it has no figure, and the
  // honest rendering of that is silence about the price, not a zero.
  if (note.tier === "free") {
    return {
      kind: "unpriced",
      label: "No per-token price is recorded for this model.",
    };
  }

  const usage = usageOf(rollup);
  const scored = rollup.overall.scored_samples;
  if (scored <= 0 || usage.prompt_tokens + usage.completion_tokens === 0) {
    return {
      kind: "priced_unsized",
      note,
      label: `${note.label} — we have not recorded enough usage to turn that into a per-answer figure.`,
    };
  }

  return {
    kind: "priced",
    note,
    label: note.label,
    usdPerHundredAnswers: usdPerHundredAnswers(usage, scored, note),
    tokensPerAnswer: (usage.prompt_tokens + usage.completion_tokens) / scored,
  };
}

/** One model, read on both axes at once. This is the unit the page renders. */
export interface ValueReading {
  model_key: string;
  display_name: string;
  score: number;
  /** The weakest tier behind `score` — carried so no figure travels bare. */
  confidence: ModelRollup["overall"]["confidence"];
  scored_samples: number;
  price: PriceReading;
  rollup: ModelRollup;
}

export interface ValueSummary {
  /** One quotable sentence about cost. Always finished, always safe alone. */
  headline: string;
  /** The qualifiers that travel with it. Never empty when there is a claim. */
  caveats: string[];
  /** Every ranked model on both axes, best capability first. */
  readings: ValueReading[];
  /** The "smart buy", or null when naming one would not be honest. */
  valuePick: ValueReading | null;
  /** True when the strongest model is also the cheapest — no trade-off to make. */
  leaderIsAlsoCheapest: boolean;
  /** True when two or more ranked models can actually be set against each other. */
  comparable: boolean;
}

/** The comparable cost of a reading, or null when it has no quotable figure. */
function quoteOf(reading: ValueReading): number | null {
  if (reading.price.kind === "priced") return reading.price.usdPerHundredAnswers;
  if (reading.price.kind === "free_on_campus") return 0;
  return null;
}

/**
 * Read a leaderboard response for what it says about money.
 *
 * Driven entirely by `rollupByModel`, so it can never disagree with the
 * capability figures rendered beside it.
 */
export function summariseValue(board: LeaderboardResponse): ValueSummary {
  // ⚠ `isRanked` IS THE STUB FILTER. It is the only thing standing between this
  // function and "the best value model we measured is our own echo server",
  // which is free and scores 1.00 by construction.
  const ranked = rollupByModel(board).filter(isRanked);

  const readings: ValueReading[] = ranked.map((rollup) => ({
    model_key: rollup.model_key,
    display_name: rollup.display_name,
    // `isRanked` guarantees a non-null score; re-reading it proves that to the
    // compiler under `noUncheckedIndexedAccess`.
    score: rollup.overall.score ?? 0,
    confidence: rollup.overall.confidence,
    scored_samples: rollup.overall.scored_samples,
    price: priceReadingFor(rollup),
    rollup,
  }));

  const caveats: string[] = [];
  const comparable = readings.length > 1;

  if (readings.length === 0) {
    return {
      headline:
        "We cannot say anything about cost yet, because nothing has been measured that we would stand behind.",
      caveats: [
        "When results land, every price here will come from the provider's own published rates rather than from what our testing happened to spend.",
      ],
      readings: [],
      valuePick: null,
      leaderIsAlsoCheapest: false,
      comparable: false,
    };
  }

  // Sorted best-capability-first by `rollupByModel`, so the head is the leader.
  const [leader] = readings;
  if (!leader) {
    // Unreachable given the length check above; present so the type is a fact.
    return {
      headline: "We cannot say anything about cost yet.",
      caveats: [],
      readings,
      valuePick: null,
      leaderIsAlsoCheapest: false,
      comparable,
    };
  }

  // ⚠ THE MODELLING ASSUMPTION, STATED BEFORE ANY FIGURE IS READ. It is the
  // first caveat because it qualifies every number this module produces.
  const anyQuoted = readings.some((r) => r.price.kind === "priced");
  if (anyQuoted) {
    caveats.push(
      "These prices use each provider's published rates and the answer lengths we actually saw in our own testing. " +
        "Your prompts and your answers will be a different length, so treat these as the right order of magnitude rather than a quote.",
    );
  }

  const quotable = readings.filter((r) => quoteOf(r) !== null);
  const cheapest = quotable.reduce<ValueReading | null>((best, candidate) => {
    if (best === null) return candidate;
    return (quoteOf(candidate) ?? Infinity) < (quoteOf(best) ?? Infinity) ? candidate : best;
  }, null);

  const leaderQuote = quoteOf(leader);
  const cheapestQuote = cheapest === null ? null : quoteOf(cheapest);

  const leaderIsAlsoCheapest =
    cheapest !== null && cheapest.model_key === leader.model_key && comparable;

  /* --------------------------------------------------------- the value pick */
  //
  // Earned on three conditions, all of which must hold:
  //   1. it is not already the capability leader (that is a different sentence),
  //   2. it is MEANINGFUL_PRICE_RATIO times cheaper — a real gap, not noise in
  //      our answer-length modelling, and
  //   3. its capability is within MEANINGFUL_GAP of the leader, so it is a
  //      genuine alternative rather than a cheaper, worse product.
  let valuePick: ValueReading | null = null;
  if (
    comparable &&
    !leaderIsAlsoCheapest &&
    cheapest !== null &&
    cheapestQuote !== null &&
    leaderQuote !== null &&
    cheapestQuote > 0 &&
    leaderQuote >= cheapestQuote * MEANINGFUL_PRICE_RATIO &&
    leader.score - cheapest.score < MEANINGFUL_GAP
  ) {
    valuePick = cheapest;
  }

  // A free campus model that keeps up with the leader is the strongest version
  // of this finding, and the ratio test above cannot express it (its quote is
  // 0, and nothing is "2× cheaper than free").
  if (
    valuePick === null &&
    comparable &&
    !leaderIsAlsoCheapest &&
    cheapest !== null &&
    cheapestQuote === 0 &&
    leaderQuote !== null &&
    leaderQuote > 0 &&
    leader.score - cheapest.score < MEANINGFUL_GAP
  ) {
    valuePick = cheapest;
  }

  /* ---------------------------------------------------------- the sentence */
  let headline: string;

  if (!comparable) {
    const only = leader.price;
    headline =
      only.kind === "priced"
        ? `We have only priced one model so far. ${leader.display_name} works out at about ` +
          `${formatQuote(only.usdPerHundredAnswers)} for ${ANSWERS_PER_QUOTE} answers of the length we measured — ` +
          `a figure to sanity-check against, not a comparison.`
        : only.kind === "free_on_campus"
          ? `The one model we have measured, ${leader.display_name}, runs on campus hardware and costs you nothing per use. ` +
            `With nothing to compare it against, that is a fact rather than a recommendation.`
          : `We have measured one model, ${leader.display_name}, but cannot yet put a per-answer price on it.`;
    caveats.push(
      "Only one model has been measured, so there is no cheaper or dearer alternative to set it against yet.",
    );
  } else if (leaderIsAlsoCheapest) {
    headline =
      `${leader.display_name} is both the strongest of the ${readings.length} models we measured ` +
      `(${formatScoreValue(leader.score)} out of 1.00) and the cheapest to run. ` +
      `On this evidence there is no trade-off to make between the two.`;
  } else if (valuePick !== null && leaderQuote !== null) {
    const pickQuote = quoteOf(valuePick) ?? 0;
    const times = pickQuote > 0 ? Math.round(leaderQuote / pickQuote) : null;
    headline =
      `${leader.display_name} scores highest of the ${readings.length} models we measured ` +
      `(${formatScoreValue(leader.score)} out of 1.00), but ${valuePick.display_name} is within a whisker of it ` +
      `at ${formatScoreValue(valuePick.score)} ` +
      (pickQuote === 0
        ? "and costs nothing per use, because it runs on campus hardware. "
        : `for about ${times !== null && times > 1 ? `a ${times}th of ` : "a fraction of "}the price. `) +
      `If cost matters at all, ${valuePick.display_name} is the one to look at first.`;
  } else {
    headline =
      `${leader.display_name} scores highest of the ${readings.length} models we measured ` +
      `(${formatScoreValue(leader.score)} out of 1.00). ` +
      `Nothing else we have priced is both cheaper and close enough on quality for us to call it a better buy.`;
  }

  /* ----------------------------------------------------------- the caveats */
  const unpriced = readings.filter(
    (r) => r.price.kind === "unpriced" || r.price.kind === "priced_unsized",
  );
  if (unpriced.length > 0) {
    caveats.push(
      `${unpriced.length === 1 ? "One model has" : `${unpriced.length} models have`} no per-answer price here — ` +
        `either the registry records no rates for ${unpriced.length === 1 ? "it" : "them"}, or we have not run ` +
        `${unpriced.length === 1 ? "it" : "them"} enough to know what an answer costs. That is a gap in what we know, not a zero.`,
    );
  }

  caveats.push(
    "Price is only half of the decision. A cheaper model that gets your subject wrong is not a saving — " +
      "check how each one does on the outcomes you actually teach before choosing on cost.",
  );

  return { headline, caveats, readings, valuePick, leaderIsAlsoCheapest, comparable };
}
