/**
 * The display ceiling.
 *
 * The landing page's one headline number read "1.00" for a measured 0.9958.
 * On a product whose whole argument is that it distinguishes what it knows from
 * what it does not, a perfect score it did not measure is the most expensive
 * two characters on the site.
 */

import { describe, expect, it } from "vitest";

import { formatScore, formatScoreValue } from "@/lib/format";

describe("formatScoreValue", () => {
  it("NEVER rounds up into a perfect score", () => {
    // The exact value behind the landing page's "1.00".
    expect(formatScoreValue(0.9958)).toBe("0.99");
    expect(formatScoreValue(0.999)).toBe("0.99");
    expect(formatScoreValue(0.99999)).toBe("0.99");
  });

  it("still prints 1.00 for a score that actually is 1", () => {
    // The rule is "do not invent a perfect score", not "never show one". A
    // model that got every answer right has earned the number.
    expect(formatScoreValue(1)).toBe("1.00");
    expect(formatScoreValue(1.0)).toBe("1.00");
  });

  it("rounds normally everywhere else", () => {
    expect(formatScoreValue(0.876)).toBe("0.88");
    expect(formatScoreValue(0.874)).toBe("0.87");
    expect(formatScoreValue(0.5)).toBe("0.50");
    expect(formatScoreValue(0)).toBe("0.00");
  });

  it("does not mirror the rule at the floor", () => {
    // Rendering 0.001 as "0.00" rounds AGAINST the model, which is the
    // conservative direction and the one this file already leans. It is the
    // flattering rounding that has to be refused, not every rounding.
    expect(formatScoreValue(0.001)).toBe("0.00");
  });
});

describe("formatScore", () => {
  it("keeps null as an em-dash rather than a number", () => {
    expect(formatScore(null)).toBe("—");
  });

  it("applies the ceiling rule, so no call site can bypass it", () => {
    expect(formatScore(0.9958)).toBe("0.99");
  });
});
