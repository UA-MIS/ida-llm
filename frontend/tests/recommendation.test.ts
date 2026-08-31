/**
 * The rule the recommendation card was the one exception to.
 *
 * `lib/findings.ts` states it: "there is no code path that produces a bare
 * headline." True of the findings paragraph, false of this card — which gated
 * its whole caveat panel on `caveats.length > 0` while the API only appends
 * caveats for unscorable tasks, errored samples and partial scoring. A
 * verifiable result with four scored samples is marked LOW confidence and
 * given no caveat at all, so the panel vanished exactly when it was needed.
 */

import { describe, expect, it } from "vitest";

import {
  displayCaveats,
  evidenceStanding,
  scoredAttempts,
  weakestConfidence,
} from "@/lib/recommendation";
import type { Recommendation, Receipt } from "@/lib/types";

function receipt(overrides: Partial<Receipt> = {}): Receipt {
  return {
    task_id: "slo2/l3-break-even",
    task_title: "Break-even volume",
    task_kind: "verifiable",
    model_key: "luna",
    run_id: "run_1",
    mean_score: 0.83,
    scored_count: 2,
    sample_count: 2,
    confidence: "low",
    trust_label: "Verifiable",
    ...overrides,
  };
}

function recommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    model_key: "luna",
    display_name: "Luna",
    headline: "Use Luna for writing feedback to students",
    why: ["It scored 0.83 on 'Undergraduate essay feedback'"],
    surface: "chat",
    surface_label: "In a chat window",
    surface_rationale: "Nothing to install.",
    cost: {
      tier: "paid",
      label: "About $2 a month",
      detail: "At your stated volume.",
      input_usd_per_mtok: 0.2,
      output_usd_per_mtok: 1.2,
    },
    data_residency: "third_party",
    data_residency_label: "Sends data to a third party",
    prompt_template: "…",
    guardrails: [],
    caveats: [],
    receipts: [receipt()],
    evidence_score: 0.83,
    verifiable_evidence: true,
    ...overrides,
  };
}

describe("weakestConfidence", () => {
  it("takes the weakest, never the best or the average", () => {
    expect(
      weakestConfidence([receipt({ confidence: "moderate" }), receipt({ confidence: "low" })]),
    ).toBe("low");
  });

  it("is null when there is nothing behind the answer", () => {
    expect(weakestConfidence([])).toBeNull();
  });
});

describe("scoredAttempts", () => {
  it("sums what was actually scored, not what was attempted", () => {
    expect(
      scoredAttempts([receipt({ scored_count: 2 }), receipt({ scored_count: 4 })]),
    ).toBe(6);
  });
});

describe("evidenceStanding", () => {
  it("calls the live two-sample recommendation thin", () => {
    expect(evidenceStanding(recommendation()).thin).toBe(true);
  });

  it("calls a low-confidence answer thin however many samples it has", () => {
    const standing = evidenceStanding(
      recommendation({
        receipts: [receipt({ scored_count: 51, sample_count: 51, confidence: "low" })],
      }),
    );
    expect(standing.thin).toBe(true);
  });

  it("does not call a well-evidenced answer thin", () => {
    const standing = evidenceStanding(
      recommendation({
        receipts: [receipt({ scored_count: 51, sample_count: 51, confidence: "moderate" })],
      }),
    );
    expect(standing.thin).toBe(false);
  });
});

describe("displayCaveats", () => {
  it("NEVER returns an empty list — the panel can no longer disappear", () => {
    // The exact shape of the bug: a strong-looking recommendation whose API
    // caveats are empty.
    const bare = recommendation({
      caveats: [],
      receipts: [receipt({ scored_count: 51, sample_count: 51, confidence: "moderate" })],
    });
    expect(displayCaveats(bare).length).toBeGreaterThan(0);
  });

  it("surfaces a thin-evidence caveat when the API supplied none", () => {
    const caveats = displayCaveats(recommendation({ caveats: [] }));
    expect(caveats.join(" ")).toMatch(/thin evidence/i);
    expect(caveats.join(" ")).toMatch(/hint rather than a verdict/i);
  });

  it("names the actual counts rather than hedging vaguely", () => {
    const caveats = displayCaveats(recommendation({ caveats: [] }));
    expect(caveats.join(" ")).toContain("2 scored attempts");
    expect(caveats.join(" ")).toContain("1 piece of work");
  });

  it("says so plainly when nothing measured stands behind the answer", () => {
    const caveats = displayCaveats(recommendation({ receipts: [], evidence_score: null }));
    expect(caveats.join(" ")).toMatch(/no measured run behind this/i);
  });

  it("does not stack a second thin-evidence caveat on top of the API's own", () => {
    const caveats = displayCaveats(
      recommendation({ caveats: ["The evidence here is thin — hold it loosely."] }),
    );
    expect(caveats.filter((c) => /thin/i.test(c))).toHaveLength(1);
  });

  it("translates the API's caveats on the way through", () => {
    const caveats = displayCaveats(
      recommendation({
        caveats: ["No judge model is configured (set IDA_JUDGE_MODEL_KEY to a key in models.yaml)."],
      }),
    );
    expect(caveats.join(" ")).not.toContain("IDA_JUDGE_MODEL_KEY");
    expect(caveats.join(" ")).not.toContain("models.yaml");
  });
});
