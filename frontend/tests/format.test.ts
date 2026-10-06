/**
 * The display ceiling, under the whole-number-percent convention.
 *
 * Scores render as a whole number out of 100 with a percent sign ("72%",
 * "100%"), everywhere, through one function. The one asymmetry is the ceiling:
 * a measured 0.9958 must not print as "100%", a perfect score the benchmark did
 * not get. On a product whose whole argument is that it distinguishes what it
 * knows from what it does not, an invented perfect score is the most expensive
 * thing on the page.
 */

import { describe, expect, it } from "vitest";

import { formatScore, formatScoreValue } from "@/lib/format";

describe("formatScoreValue", () => {
  it("NEVER rounds up into a perfect score", () => {
    // The exact value behind the old landing page's "1.00".
    expect(formatScoreValue(0.9958)).toBe("99%");
    expect(formatScoreValue(0.999)).toBe("99%");
    expect(formatScoreValue(0.99999)).toBe("99%");
  });

  it("still prints 100% for a score that actually is 1", () => {
    // The rule is "do not invent a perfect score", not "never show one". A
    // model that got every answer right has earned the number.
    expect(formatScoreValue(1)).toBe("100%");
    expect(formatScoreValue(1.0)).toBe("100%");
  });

  it("rounds normally everywhere else, to a whole-number percent", () => {
    expect(formatScoreValue(0.876)).toBe("88%");
    expect(formatScoreValue(0.874)).toBe("87%");
    expect(formatScoreValue(0.5)).toBe("50%");
    expect(formatScoreValue(0.93)).toBe("93%");
    expect(formatScoreValue(0)).toBe("0%");
  });

  it("does not mirror the rule at the floor", () => {
    // Rendering 0.001 as "0%" rounds AGAINST the model, which is the
    // conservative direction and the one this file already leans. It is the
    // flattering rounding that has to be refused, not every rounding.
    expect(formatScoreValue(0.001)).toBe("0%");
  });
});

describe("formatScore", () => {
  it("keeps null as an em-dash rather than a number", () => {
    expect(formatScore(null)).toBe("—");
  });

  it("applies the ceiling rule, so no call site can bypass it", () => {
    expect(formatScore(0.9958)).toBe("99%");
  });
});
