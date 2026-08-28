/**
 * Rendering the trust tell — how a professor is told what a number is worth.
 *
 * The classification itself lives in the API (`ida_api/trust.py`), on purpose:
 * "is this verifiable or AI-judged, and how confident are we" is a claim about
 * the data, and a claim about the data belongs where the data is. What lives
 * here is only how that claim is *drawn* — which CSS variable, which glyph,
 * which one-line summary — so a second consumer of the API gets the same
 * verdict without reimplementing the rule.
 *
 * Pure functions, no React: that is what makes them testable, and it is why the
 * badge components below take a `TrustTell` rather than a score.
 */

import type { Confidence, DataResidency, ModelResult } from "./types";

/** Which colour a confidence tier is drawn in. */
export function confidenceColorVar(confidence: Confidence): string {
  switch (confidence) {
    case "high":
      return "var(--pass)";
    case "moderate":
      return "var(--pending)";
    case "low":
      return "var(--fail)";
    case "none":
      return "var(--muted)";
  }
}

/**
 * The confidence meter, as filled/empty pips.
 *
 * A meter rather than a word alone because "moderate" reads as an opinion,
 * while three pips with one filled reads as a scale — and a scale is what makes
 * a reader compare two numbers correctly.
 */
export function confidencePips(confidence: Confidence): {
  filled: number;
  total: number;
} {
  const total = 3;
  switch (confidence) {
    case "high":
      return { filled: 3, total };
    case "moderate":
      return { filled: 2, total };
    case "low":
      return { filled: 1, total };
    case "none":
      return { filled: 0, total };
  }
}

/** The short glyph that fronts a trust badge. Verifiable is a check; judged is a scale. */
export function trustGlyph(kind: "verifiable" | "subjective"): string {
  return kind === "verifiable" ? "✓" : "⚖";
}

export function residencyGlyph(residency: DataResidency): string {
  switch (residency) {
    case "on_campus":
      return "🔒";
    case "third_party":
      return "☁";
    case "not_a_real_model":
      return "🧪";
    case "unknown":
      return "?";
  }
}

/**
 * One line summarising a model's standing on a task, for a heading or a title
 * attribute. Never invents a number: a null score produces a sentence about
 * *why* there is no number, taken from the trust tell.
 */
export function summariseResult(result: ModelResult): string {
  if (result.mean_score === null) {
    return `${result.display_name}: ${result.trust.confidence_reason}`;
  }
  return (
    `${result.display_name}: ${result.mean_score.toFixed(2)} on ` +
    `${result.scored_count} of ${result.sample_count} samples — ` +
    `${result.trust.tier_label}, ${result.trust.confidence_label.toLowerCase()}`
  );
}

/**
 * Whether a row should be visually de-emphasised.
 *
 * De-emphasised, never hidden. A test stub and an unmeasured pair are real
 * facts about the benchmark, and a results page that quietly drops rows it
 * finds inconvenient is the kind of page this project exists to replace.
 */
export function isDeEmphasised(result: ModelResult): boolean {
  return !result.recommendable || result.mean_score === null;
}

/**
 * Group a task's tags into the facets that mean something.
 *
 * `slo:`/`use-mode:`/`audience:` come back from the API already parsed into
 * `facets`; this turns the remainder into plain descriptive tags so the UI can
 * show both without printing `slo:mis200-3` twice.
 */
export function plainTags(tags: string[]): string[] {
  return tags.filter((tag) => !tag.includes(":"));
}

export const FACET_LABEL: Record<string, string> = {
  slo: "Learning outcome",
  use_mode: "Use mode",
  audience: "Audience",
};

/** Human label for a `use-mode:` value, per the project-direction dimensions. */
export const USE_MODE_LABEL: Record<string, string> = {
  "capability": "Can a model just do this? (integrity risk)",
  "integrity-risk": "Can a model just do this? (integrity risk)",
  "professor-assist": "Can it help the professor?",
  "student-learning-aid": "Can it help a student learn?",
  "researcher-assist": "Can it help with research?",
};

export function facetValueLabel(facet: string, value: string): string {
  if (facet === "use_mode") return USE_MODE_LABEL[value] ?? value;
  return value;
}
