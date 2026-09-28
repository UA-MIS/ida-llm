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

import { formatScoreValue } from "./format";
import { plainTaskKind } from "./glossary";

import type {
  Confidence,
  CurriculumView,
  DataResidency,
  ModelResult,
  OutcomeView,
  TaskKind,
  TaskLeaderboard,
} from "./types";

/** The two raw `TaskKind` words — never printed on their own; see `plainTags`. */
const TASK_KIND_WORDS: ReadonlySet<TaskKind> = new Set(["verifiable", "subjective"]);

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
    `${result.display_name}: ${formatScoreValue(result.mean_score)} on ` +
    `${result.scored_count} of ${result.sample_count} samples — ` +
    `${plainTaskKind(result.trust.kind)}, ${result.trust.confidence_label.toLowerCase()}`
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
 * A task's descriptive tags — everything the SLO axes have not already claimed.
 *
 * `slo:` / `use-mode:` / `slo-benchmark` arrive on the row already parsed
 * (`task.slo`, `task.use_mode`, `task.in_benchmark`), so printing them again as
 * raw tags would show `slo:SLO2` next to the outcome's real title. The filter
 * matches the API's parse rule: a prefixed tag is a claim, not a description.
 *
 * Also drops a bare `verifiable`/`subjective` tag — many task families carry
 * one (see tasks/slo3-global-knowledge/*) — because `FacetRow` already draws
 * `TrustBadge` on the same row, in `plainTaskKind`'s words. Printing the raw
 * `TaskKind` word too would be the exact jargon leak `lib/glossary.ts` exists
 * to keep off the page (see the big comment on `TrustBadge` in
 * `components/trust-badges.tsx`), just via a second, unguarded path.
 */
export function plainTags(tags: string[]): string[] {
  return tags.filter(
    (tag) => !tag.includes(":") && tag !== BENCHMARK_TAG && !TASK_KIND_WORDS.has(tag as TaskKind),
  );
}

export const BENCHMARK_TAG = "slo-benchmark";

/**
 * The title for a use mode, from the curriculum — never a table in this file.
 *
 * ⚠ THERE IS NO HARDCODED LABEL MAP HERE, and that is deliberate. An earlier
 * version of this file carried one, invented before the vocabulary existed, and
 * every entry in it was wrong (`professor-assist` for what the curriculum calls
 * `assistive`). `curriculum/slo.yaml` is the authority for both the spelling and
 * the wording; a component that captions it from memory is a component that
 * disagrees with the programme.
 *
 * Falls back to the raw id when the curriculum is unavailable — an id is honest,
 * an invented caption is not.
 *
 * ⚠ NOT `useModeTitle`. A `use`-prefixed export is read as a React hook by
 * `react-hooks/rules-of-hooks`, which then fails the build the first time it is
 * called inside a conditional — which this legitimately is.
 */
export function titleForUseMode(
  curriculum: CurriculumView | undefined,
  modeId: string,
): string {
  return curriculum?.use_modes.find((mode) => mode.id === modeId)?.title ?? modeId;
}

/** The outcome record for an id, or undefined when the curriculum is unavailable. */
export function outcomeOf(
  curriculum: CurriculumView | undefined,
  outcomeId: string | null,
): OutcomeView | undefined {
  if (!outcomeId) return undefined;
  return curriculum?.outcomes.find((outcome) => outcome.id === outcomeId);
}

/**
 * Heading for an outcome group.
 *
 * `SLO2 · Quantitative Literacy` when the curriculum is loaded, bare `SLO2`
 * when it is not. Never a guess at the title.
 */
export function outcomeHeading(
  curriculum: CurriculumView | undefined,
  outcomeId: string,
): string {
  const outcome = outcomeOf(curriculum, outcomeId);
  return outcome ? `${outcome.id} · ${outcome.title}` : outcomeId;
}

/**
 * Group task boards by outcome, in the order the API returned the ids.
 *
 * The API orders them by the curriculum's own sequence (SLO10 must not sort
 * before SLO2). Tasks with no outcome go last under a null key — the exemplar
 * and demo families predate the benchmark and are not errors.
 */
export function groupByOutcome(
  tasks: TaskLeaderboard[],
  slos: string[],
): { slo: string | null; tasks: TaskLeaderboard[] }[] {
  const groups: { slo: string | null; tasks: TaskLeaderboard[] }[] = [];
  for (const slo of slos) {
    const inGroup = tasks.filter((task) => task.slo === slo);
    if (inGroup.length > 0) groups.push({ slo, tasks: inGroup });
  }
  const untagged = tasks.filter((task) => !task.slo);
  if (untagged.length > 0) groups.push({ slo: null, tasks: untagged });
  return groups;
}

/**
 * The per-sample drill-down keys, in a fixed reading order.
 *
 * `slo` and `use_mode` repeat the task's tags (the validator requires them to
 * agree, so they are context rather than news); `skill` and `provenance` are the
 * sample's own and are the reason to drill in at all. Everything else the author
 * put in `metadata` is left alone — a dashboard that decided which of an
 * author's keys were interesting would eventually hide the one that mattered.
 */
const SAMPLE_FACET_ORDER = ["slo", "use_mode", "skill", "provenance"] as const;

export const SAMPLE_FACET_LABEL: Record<string, string> = {
  slo: "Learning outcome",
  use_mode: "Use mode",
  skill: "Skill",
  provenance: "Provenance",
};

export function sampleFacets(
  metadata: Record<string, unknown> | undefined,
): [string, string][] {
  if (!metadata) return [];
  return SAMPLE_FACET_ORDER.filter(
    (key) => metadata[key] !== undefined && metadata[key] !== null && metadata[key] !== "",
  ).map((key) => [key, String(metadata[key])]);
}
