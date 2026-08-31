/**
 * The front door's reading of the board, and the claims it must refuse to make.
 *
 * ⚠ THE PAGE THIS DRIVES IS THE MOST DANGEROUS ONE IN THE PRODUCT. Everywhere
 * else a reader meets a number welded to its trust tell. Here they meet an
 * INTERPRETATION — "this one leads, this one is the buy" — in a few seconds, and
 * most of them will never click through. Whatever this module says is, for the
 * majority of visitors, the entire product.
 *
 * So the tests below are mostly about what it must NOT say:
 *
 *   - no universal "#1", because the ranking is an average across outcomes and a
 *     marketing professor's answer is not an accounting professor's
 *   - no standout drawn from a test stub
 *   - no silent presentation of seeded rows as measurements
 *   - no claim that outlives the evidence behind it
 */

import { describe, expect, it } from "vitest";

import { buildOverview } from "@/lib/overview";

import { board, result, task } from "./fixtures";
import type { ModelResult } from "@/lib/types";

/* ------------------------------------------------------------------ helpers */

const USAGE = { prompt_tokens: 4200, completion_tokens: 2600 };

function model(key: string, score: number, overrides: Partial<ModelResult> = {}): ModelResult {
  return result({
    model_key: key,
    display_name: key.toUpperCase(),
    mean_score: score,
    run_id: `run_${key}`,
    usage: USAGE,
    ...overrides,
  });
}

/** A two-outcome board so "best at" has something to choose between. */
function twoOutcomeBoard(results: ModelResult[]) {
  return board([
    task({ task_id: "slo2/a", slo: "SLO2", results, has_results: results.length > 0 }),
    task({
      task_id: "slo4/a",
      slo: "SLO4",
      family: "slo4",
      kind: "subjective",
      results: results.map((r) => ({ ...r, mean_score: (r.mean_score ?? 0) - 0.2 })),
      has_results: results.length > 0,
    }),
  ]);
}

/* ------------------------------------------------------------- the standouts */

describe("the standouts", () => {
  it("never crowns a universal number one", () => {
    const overview = buildOverview(twoOutcomeBoard([model("luna", 0.9), model("vega", 0.7)]));

    const strongest = overview.standouts.find((s) => s.role === "strongest");
    expect(strongest).toBeDefined();
    // The claim must be scoped to what was measured. An unqualified "the best
    // AI model" is a claim about every field at once, and this benchmark covers
    // a handful of outcomes in one programme.
    expect(strongest!.roleLabel.toLowerCase()).toMatch(/measured|so far|tested/);
    expect(strongest!.roleLabel.toLowerCase()).not.toBe("best model");
  });

  it("carries the nudge that a reader's own field may differ", () => {
    const overview = buildOverview(twoOutcomeBoard([model("luna", 0.9), model("vega", 0.7)]));
    expect(overview.scopeNudge.toLowerCase()).toMatch(/your|field|subject|course/);
  });

  it("never draws a standout from a test stub", () => {
    const overview = buildOverview(
      twoOutcomeBoard([
        model("mock", 1.0, {
          recommendable: false,
          data_residency: "not_a_real_model",
          display_name: "Mock",
        }),
        model("luna", 0.8),
      ]),
    );

    expect(overview.standouts.map((s) => s.model_key)).not.toContain("mock");
  });

  it("says what each standout is actually strongest at", () => {
    // The hook is meant to be EXPLANATIVE, not a rank. "Leads on quantitative
    // work" is a reason; "#1" is a number with no content.
    const overview = buildOverview(twoOutcomeBoard([model("luna", 0.9), model("vega", 0.7)]));
    const strongest = overview.standouts.find((s) => s.role === "strongest")!;

    expect(strongest.bestAt).not.toBeNull();
    expect(strongest.bestAt!.heading).toContain("SLO2");
  });

  it("ships every standout with its confidence, never a bare score", () => {
    const overview = buildOverview(twoOutcomeBoard([model("luna", 0.9), model("vega", 0.7)]));
    for (const standout of overview.standouts) {
      expect(standout.confidenceLabel, `${standout.model_key} has no confidence`).toBeTruthy();
    }
  });

  it("shows at most three, so the page stays a read rather than a table", () => {
    const overview = buildOverview(
      twoOutcomeBoard([
        model("a", 0.95),
        model("b", 0.9),
        model("c", 0.85),
        model("d", 0.8),
        model("e", 0.75),
      ]),
    );
    expect(overview.standouts.length).toBeLessThanOrEqual(3);
  });

  it("gives every standout a receipt", () => {
    const overview = buildOverview(twoOutcomeBoard([model("luna", 0.9)]));
    for (const standout of overview.standouts) {
      expect(standout.reportHref).toContain(standout.model_key);
    }
  });
});

/* ------------------------------------------------------- demonstration data */

describe("the demonstration-data tell", () => {
  it("reports a wholly seeded board as illustrative", () => {
    const overview = buildOverview(
      twoOutcomeBoard([model("luna", 0.9, { demonstration: true })]),
    );

    expect(overview.demonstration.any).toBe(true);
    expect(overview.demonstration.all).toBe(true);
    expect(overview.demonstration.notice.toLowerCase()).toMatch(/illustrat|demonstration|example/);
  });

  it("distinguishes a partly seeded board from a wholly seeded one", () => {
    // ⚠ THE CASE A PAGE-LEVEL BANNER CANNOT EXPRESS, and the reason the flag is
    // per row. Labelling a real measurement "illustrative" is its own dishonesty.
    const overview = buildOverview(
      twoOutcomeBoard([
        model("luna", 0.9, { demonstration: true }),
        model("vega", 0.7, { demonstration: false }),
      ]),
    );

    expect(overview.demonstration.any).toBe(true);
    expect(overview.demonstration.all).toBe(false);
    expect(overview.demonstration.notice.toLowerCase()).toMatch(/some|part|mix/);
    // ⚠ AGREEMENT, CHECKED, because the broken version shipped to a live render:
    // "1 of the 2 models here have been genuinely measured". A grammatical slip
    // in the disclosure paragraph undercuts the one thing it exists to do.
    expect(overview.demonstration.notice).toContain("1 of the 2 models here has been");
    expect(overview.demonstration.notice).not.toMatch(/models here have been/);
  });

  it("keeps that sentence grammatical when several models are real", () => {
    const overview = buildOverview(
      twoOutcomeBoard([
        model("a", 0.9, { demonstration: true }),
        model("b", 0.8),
        model("c", 0.7),
      ]),
    );
    expect(overview.demonstration.notice).toContain("2 of the 3 models here have been");
    expect(overview.demonstration.notice).toContain("the other is an example result");
  });

  it("stays silent on a board with no seeded rows", () => {
    const overview = buildOverview(twoOutcomeBoard([model("luna", 0.9)]));
    expect(overview.demonstration.any).toBe(false);
    expect(overview.demonstration.notice).toBe("");
  });
});

/* -------------------------------------------------------------- degradation */

describe("degrading honestly", () => {
  it("renders a board with a single measured model without inventing a field", () => {
    const overview = buildOverview(twoOutcomeBoard([model("luna", 0.9)]));

    expect(overview.standouts).toHaveLength(1);
    // With one model there is nothing to lead, so the label must not imply a
    // contest was held.
    expect(overview.standouts[0]!.roleLabel.toLowerCase()).not.toMatch(/ahead|leads|beats|best/);
    expect(overview.headline.toLowerCase()).toMatch(/one|single/);
  });

  it("says nothing has been measured rather than showing an empty frame", () => {
    const overview = buildOverview(board([task()]));

    expect(overview.standouts).toEqual([]);
    expect(overview.headline).toBeTruthy();
    expect(overview.anyMeasured).toBe(false);
  });

  it("never contradicts the plain-language findings it sits beside", () => {
    // Both readings come from `rollupByModel`. This pins that they still agree
    // on the one fact a visitor would notice them disagreeing about.
    const overview = buildOverview(twoOutcomeBoard([model("luna", 0.9), model("vega", 0.7)]));

    expect(overview.findings.leader?.model_key).toBe(
      overview.standouts.find((s) => s.role === "strongest")?.model_key,
    );
  });
});
