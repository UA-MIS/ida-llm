/**
 * The value axis, and the ways it can lie.
 *
 * ⚠ EVERY TEST HERE GUARDS A SENTENCE THAT WOULD BE EMBARRASSING TO PUBLISH.
 * "Cheap" is a comparative, and this project's whole argument is that it does
 * not make comparatives it has not earned. The specific failures pinned below
 * are the ones the data actively invites:
 *
 *   - our $0 measurement spend read back as "this model is free"
 *   - a deterministic stub, which costs nothing and scores 1.00, crowned the
 *     best value on the benchmark
 *   - a campus model's $0 rate turned into an infinite capability-per-dollar
 *   - a cheaper model called "the smart buy" when it is materially worse
 *   - a single measured model described as "the value pick" of a field of one
 */

import { describe, expect, it } from "vitest";

import {
  priceReadingFor,
  summariseValue,
  usdPerHundredAnswers,
  type PriceReading,
} from "@/lib/value";
import { rollupByModel } from "@/lib/rollup";

import { board, result, task } from "./fixtures";
import type { CostNote, ModelResult, TokenUsage } from "@/lib/types";

/* ------------------------------------------------------------------ helpers */

const PAID: CostNote = {
  tier: "paid",
  label: "$0.20 in / $1.20 out per million tokens",
  detail: "A million tokens is roughly 700,000 words.",
  input_usd_per_mtok: 0.2,
  output_usd_per_mtok: 1.2,
};

const DEAR: CostNote = {
  tier: "paid",
  label: "$5.00 in / $25.00 out per million tokens",
  detail: "A million tokens is roughly 700,000 words.",
  input_usd_per_mtok: 5,
  output_usd_per_mtok: 25,
};

const CAMPUS: CostNote = {
  tier: "campus_hosted",
  label: "Free to you — runs on campus hardware",
  detail: "No per-use charge.",
  input_usd_per_mtok: 0,
  output_usd_per_mtok: 0,
};

const USAGE: TokenUsage = { prompt_tokens: 4200, completion_tokens: 2600 };

/** One model's row on one task, with a rate card and token accounting. */
function priced(overrides: Partial<ModelResult> = {}): ModelResult {
  return result({ price: PAID, usage: USAGE, ...overrides });
}

/** A board with one task and the given model rows on it. */
function withResults(results: ModelResult[]) {
  return board([task({ results, has_results: results.length > 0 })]);
}

function rollupOf(results: ModelResult[], key: string) {
  const found = rollupByModel(withResults(results)).find((r) => r.model_key === key);
  if (!found) throw new Error(`no rollup for ${key}`);
  return found;
}

function reading(results: ModelResult[], key: string): PriceReading {
  return priceReadingFor(rollupOf(results, key));
}

/* ------------------------------------------------------------- the readings */

describe("what one answer costs", () => {
  it("prices an answer from the rate card, not from what we spent", () => {
    // ⚠ THE CENTRAL DISTINCTION. `total_cost_usd` is 0 here — exactly what the
    // dev seeder writes and what a cache hit records. If the reading were
    // derived from it, every model in a seeded environment would render as
    // free, and the page's most persuasive claim would be its most false one.
    const got = reading([priced({ total_cost_usd: 0 })], "luna");

    expect(got.kind).toBe("priced");
    if (got.kind !== "priced") return;
    expect(got.usdPerHundredAnswers).toBeGreaterThan(0);
  });

  it("computes the figure from observed answer length", () => {
    // 4200 prompt + 2600 completion over 10 scored answers = 420/260 per answer.
    // (420 * 0.20 + 260 * 1.20) / 1e6 = $0.0003960 per answer -> $0.0396 per 100.
    expect(usdPerHundredAnswers(USAGE, 10, PAID)).toBeCloseTo(0.0396, 6);
  });

  it("refuses to quote a figure when no tokens were recorded", () => {
    // Zero tokens is not a free answer — it is an unrecorded one. Dividing
    // anyway would print "$0.00 per 100 answers" for a model that bills.
    const got = reading(
      [priced({ usage: { prompt_tokens: 0, completion_tokens: 0 } })],
      "luna",
    );
    expect(got.kind).toBe("priced_unsized");
  });

  it("calls a campus model free rather than infinitely good value", () => {
    const got = reading([priced({ price: CAMPUS, data_residency: "on_campus" })], "luna");

    expect(got.kind).toBe("free_on_campus");
    // The trap: capability ÷ 0. A ratio must never be the thing that carries
    // "this one costs nothing", because that division is not defined.
    expect(JSON.stringify(got)).not.toContain("Infinity");
  });

  it("says an unregistered model has no published price, not a zero one", () => {
    const got = reading([priced({ price: null })], "luna");
    expect(got.kind).toBe("unpriced");
  });
});

/* -------------------------------------------------------------- the summary */

describe("the value reading over a whole board", () => {
  it("names no value pick when only one model has been measured", () => {
    const summary = summariseValue(withResults([priced()]));

    expect(summary.valuePick).toBeNull();
    expect(summary.comparable).toBe(false);
  });

  it("never makes a test stub the value pick", () => {
    // The mock is free and scores perfectly. `recommendable: false` is the only
    // thing between that and "the best value on this benchmark is our own echo
    // server" — the single most embarrassing sentence this project could ship.
    const summary = summariseValue(
      withResults([
        priced({ model_key: "mock", display_name: "Mock", mean_score: 1.0,
                 recommendable: false, data_residency: "not_a_real_model",
                 price: CAMPUS, run_id: "run_mock" }),
        priced({ model_key: "luna", display_name: "Luna", mean_score: 0.8, price: DEAR }),
      ]),
    );

    expect(summary.valuePick?.model_key).not.toBe("mock");
  });

  it("calls a much cheaper, near-as-good model the value pick", () => {
    const summary = summariseValue(
      withResults([
        priced({ model_key: "dear", display_name: "Dear", mean_score: 0.88,
                 price: DEAR, run_id: "run_dear" }),
        priced({ model_key: "thrifty", display_name: "Thrifty", mean_score: 0.86,
                 price: PAID, run_id: "run_thrifty" }),
      ]),
    );

    expect(summary.valuePick?.model_key).toBe("thrifty");
    expect(summary.headline).toContain("Thrifty");
  });

  it("refuses a value pick that is materially worse, however cheap", () => {
    // 0.88 vs 0.55 is far outside the gap this project will call a tie. Cheap
    // and much worse is not a bargain; it is a different product.
    const summary = summariseValue(
      withResults([
        priced({ model_key: "dear", display_name: "Dear", mean_score: 0.88,
                 price: DEAR, run_id: "run_dear" }),
        priced({ model_key: "thrifty", display_name: "Thrifty", mean_score: 0.55,
                 price: PAID, run_id: "run_thrifty" }),
      ]),
    );

    expect(summary.valuePick).toBeNull();
  });

  it("refuses a value pick when the prices are not meaningfully apart", () => {
    const summary = summariseValue(
      withResults([
        priced({ model_key: "a", display_name: "A", mean_score: 0.88, run_id: "run_a" }),
        priced({ model_key: "b", display_name: "B", mean_score: 0.86, run_id: "run_b" }),
      ]),
    );

    expect(summary.valuePick).toBeNull();
  });

  it("says so when the strongest model is also the cheapest", () => {
    const summary = summariseValue(
      withResults([
        priced({ model_key: "thrifty", display_name: "Thrifty", mean_score: 0.9,
                 price: PAID, run_id: "run_thrifty" }),
        priced({ model_key: "dear", display_name: "Dear", mean_score: 0.6,
                 price: DEAR, run_id: "run_dear" }),
      ]),
    );

    expect(summary.leaderIsAlsoCheapest).toBe(true);
    // And it must not then ALSO name a separate "value pick", which would read
    // as two different recommendations.
    expect(summary.valuePick).toBeNull();
  });

  it("carries a caveat with every claim it makes", () => {
    const summary = summariseValue(
      withResults([
        priced({ model_key: "dear", display_name: "Dear", mean_score: 0.88,
                 price: DEAR, run_id: "run_dear" }),
        priced({ model_key: "thrifty", display_name: "Thrifty", mean_score: 0.86,
                 price: PAID, run_id: "run_thrifty" }),
      ]),
    );

    expect(summary.caveats.length).toBeGreaterThan(0);
    // The price is modelled on the answer lengths WE saw. A professor's own
    // prompts will differ, and the page must say so before they budget on it.
    expect(summary.caveats.join(" ")).toMatch(/length|our|typical/i);
  });

  it("survives a board where nothing has been measured", () => {
    const summary = summariseValue(board([task()]));

    expect(summary.valuePick).toBeNull();
    expect(summary.readings).toEqual([]);
    expect(summary.headline).toBeTruthy();
  });
});
