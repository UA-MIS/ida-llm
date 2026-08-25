/**
 * How to read a run's outcome — the single place that logic lives.
 *
 * This module exists because of a specific, reproduced failure. The run detail
 * page decided whether to show "Not yet scorable. This is a subjective task…"
 * by testing `score === null`. But `score` is null for **two** completely
 * different reasons:
 *
 *   - the task is subjective and the LLM judge is not implemented yet, or
 *   - the sample errored and nothing was measured at all.
 *
 * So a `verifiable` arithmetic task whose four API calls all failed rendered,
 * live, as *"This is a subjective task… the model was still called and every
 * transcript below was captured, so these samples can be graded retroactively"*.
 * Every clause of that was false, under a green `succeeded` badge.
 *
 * The fix is not a better condition inline — it is refusing to derive the
 * outcome from score nullity at all. Classify from the taxonomy (`scorable`)
 * and the failure signal (`error`), which the API reports separately and
 * precisely so that this distinction survives to the UI.
 */

import type { ResultRecord, RunRecord } from "./types";

export type RunOutcome =
  /** Still queued or running. */
  | "pending"
  /** Setup failed, or every sample errored. Nothing was measured. */
  | "all-errored"
  /** Some samples errored, some completed. */
  | "partial"
  /** Completed, but this task cannot be scored yet (subjective + no judge). */
  | "not-yet-scorable"
  /** Completed and scored. */
  | "scored";

export function classifyRun(
  run: RunRecord,
  results: ResultRecord[],
): RunOutcome {
  if (run.status === "queued" || run.status === "running") return "pending";

  // A setup failure produces a failed run with no results at all.
  if (run.status === "failed") return "all-errored";
  if (results.length === 0) return "all-errored";

  if (run.status === "partial" || run.error_count > 0) return "partial";

  // Not-yet-scorable is a property of the TASK, never of a missing score.
  if (results.every((r) => !r.scorable)) return "not-yet-scorable";

  return "scored";
}

/** How a single sample turned out. Same rule, one row down. */
export type SampleOutcome = "error" | "not-yet-scorable" | "pass" | "fail" | "unscored";

export function classifySample(result: ResultRecord): SampleOutcome {
  if (result.error !== null) return "error";
  if (!result.scorable) return "not-yet-scorable";
  if (result.score === null) return "unscored";
  if (result.score.passed === null) return "unscored";
  return result.score.passed ? "pass" : "fail";
}

/**
 * Why a run has no mean score. Returns null when it has one, or is still going.
 *
 * The strings are user-facing and deliberately claim nothing that is not true:
 * an errored run does not promise retroactive grading, because there is nothing
 * to grade.
 */
export function noScoreReason(outcome: RunOutcome): string | null {
  switch (outcome) {
    case "all-errored":
      return "No samples completed — every call to the model failed. This run measured nothing.";
    case "not-yet-scorable":
      return "Not yet scorable — this task needs LLM-as-judge grading.";
    default:
      return null;
  }
}
