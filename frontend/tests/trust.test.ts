/**
 * How the trust tell is drawn.
 *
 * The classification lives in the API; what is pinned here is that the drawing
 * never contradicts it — in particular that a missing score never acquires a
 * number on its way to the screen.
 */

import { describe, expect, it } from "vitest";

import {
  confidenceColorVar,
  confidencePips,
  facetValueLabel,
  isDeEmphasised,
  plainTags,
  residencyGlyph,
  summariseResult,
  trustGlyph,
} from "@/lib/trust";
import type { ModelResult, TrustTell } from "@/lib/types";

const VERIFIABLE_TRUST: TrustTell = {
  kind: "verifiable",
  scorer: "numeric_match",
  tier_label: "Verifiable",
  headline: "Verifiable — a program compared the answer to a known correct one.",
  confidence: "high",
  confidence_label: "High confidence",
  confidence_reason: "A program checked 5 answers against a gold key.",
  caveats: [],
};

function result(overrides: Partial<ModelResult> = {}): ModelResult {
  return {
    model_key: "luna",
    display_name: "Luna",
    model_tags: ["cloud"],
    data_residency: "third_party",
    data_residency_label: "Sends data to a third party",
    enabled: true,
    recommendable: true,
    mean_score: 0.91,
    scored_count: 5,
    sample_count: 5,
    error_count: 0,
    total_cost_usd: 0,
    trust: VERIFIABLE_TRUST,
    run_id: "run_abc",
    run_status: "succeeded",
    task_content_sha: null,
    measured_at: "2026-08-01T12:00:00Z",
    ...overrides,
  };
}

describe("confidence rendering", () => {
  it("maps each tier to a distinct number of filled pips", () => {
    expect(confidencePips("high")).toEqual({ filled: 3, total: 3 });
    expect(confidencePips("moderate")).toEqual({ filled: 2, total: 3 });
    expect(confidencePips("low")).toEqual({ filled: 1, total: 3 });
    expect(confidencePips("none")).toEqual({ filled: 0, total: 3 });
  });

  it("gives every tier a colour, and 'none' a neutral one", () => {
    expect(confidenceColorVar("high")).toBe("var(--pass)");
    expect(confidenceColorVar("low")).toBe("var(--fail)");
    // Not-measured is not a failure, so it is muted rather than red.
    expect(confidenceColorVar("none")).toBe("var(--muted)");
  });
});

describe("glyphs", () => {
  it("distinguishes a checked score from a judged one", () => {
    expect(trustGlyph("verifiable")).toBe("✓");
    expect(trustGlyph("subjective")).toBe("⚖");
    expect(trustGlyph("verifiable")).not.toBe(trustGlyph("subjective"));
  });

  it("marks a campus-hosted model with a lock", () => {
    expect(residencyGlyph("on_campus")).toBe("🔒");
    expect(residencyGlyph("third_party")).not.toBe(residencyGlyph("on_campus"));
  });
});

describe("summariseResult", () => {
  it("states the score with what it was measured on", () => {
    expect(summariseResult(result())).toBe(
      "Luna: 0.91 on 5 of 5 samples — Verifiable, high confidence",
    );
  });

  it("NEVER turns a missing score into a number", () => {
    const summary = summariseResult(
      result({
        mean_score: null,
        trust: {
          ...VERIFIABLE_TRUST,
          confidence: "none",
          confidence_label: "Not scored",
          confidence_reason: "Every one of the 5 attempted samples failed.",
        },
      }),
    );
    expect(summary).not.toContain("0.00");
    expect(summary).toContain("failed");
  });
});

describe("isDeEmphasised", () => {
  it("de-emphasises a test stub and an unmeasured pair", () => {
    expect(isDeEmphasised(result({ recommendable: false }))).toBe(true);
    expect(isDeEmphasised(result({ mean_score: null }))).toBe(true);
  });

  it("leaves a real, measured result at full weight", () => {
    expect(isDeEmphasised(result())).toBe(false);
  });
});

describe("tags and facets", () => {
  it("separates prefixed facet tags from plain descriptive ones", () => {
    expect(
      plainTags(["quantitative-quiz", "slo:mis200-3", "use-mode:professor-assist"]),
    ).toEqual(["quantitative-quiz"]);
  });

  it("gives use-modes the wording from the project direction", () => {
    expect(facetValueLabel("use_mode", "student-learning-aid")).toBe(
      "Can it help a student learn?",
    );
    // An unknown value passes through rather than rendering as blank.
    expect(facetValueLabel("use_mode", "brand-new-mode")).toBe("brand-new-mode");
    expect(facetValueLabel("slo", "mis200-3")).toBe("mis200-3");
  });
});
