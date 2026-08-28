/**
 * Making one run's samples navigable instead of scrollable.
 *
 * ⚠ THE OBVIOUS GROUPING IS THE WRONG ONE. "Group the run by learning outcome"
 * sounds right and produces exactly one group: a run is one task × one model,
 * and a task carries a single `slo:` tag. The axis that actually VARIES inside a
 * run is the sample's own `skill` — `break-even-volume` vs `margin-of-safety` —
 * which is precisely the drill-down the task authors wrote the metadata for.
 *
 * So: group on the finest facet that actually splits this run, and SAY which
 * facet was used. A grouping whose basis is invisible is a grouping a reader
 * cannot trust.
 *
 * Errored samples are counted, never scored: a group's mean covers the samples
 * that produced a number, and the failures are reported next to it rather than
 * folded in as zeros.
 */

import { classifySample } from "./outcome";
import type { ResultRecord } from "./types";

/** Finest first. The first one that splits the run into >1 group wins. */
const GROUPING_FACETS = ["skill", "provenance", "slo"] as const;

export type GroupingFacet = (typeof GROUPING_FACETS)[number];

export interface SampleGroup {
  key: string;
  label: string;
  results: ResultRecord[];
  /** Null — never 0 — when nothing in this group produced a score. */
  mean_score: number | null;
  scored_count: number;
  error_count: number;
  sample_count: number;
}

export interface GroupedSamples {
  /** Null when no facet split the run; then there is a single group. */
  facet: GroupingFacet | null;
  groups: SampleGroup[];
}

function facetValue(
  metadata: Record<string, unknown> | undefined,
  facet: GroupingFacet,
): string | null {
  const raw = metadata?.[facet];
  if (raw === undefined || raw === null || raw === "") return null;
  return String(raw);
}

/** Human wording for the "grouped by …" caption. */
export const FACET_CAPTION: Record<GroupingFacet, string> = {
  skill: "skill",
  provenance: "provenance",
  slo: "learning outcome",
};

const UNLABELLED = "Unlabelled";

/**
 * Split a run's samples on the finest facet that produces more than one group.
 *
 * Order within a group is the order the API returned; group order is first
 * appearance, so the reading order of the underlying task file survives. A
 * sample whose author wrote no metadata is not dropped — it lands in an
 * `Unlabelled` group, which is a fact about the task file worth seeing.
 */
export function groupSamples(
  results: ResultRecord[],
  metadata: Record<string, Record<string, unknown>>,
): GroupedSamples {
  for (const facet of GROUPING_FACETS) {
    const buckets = new Map<string, ResultRecord[]>();
    let labelled = 0;
    for (const result of results) {
      const value = facetValue(metadata[result.sample_id], facet);
      if (value !== null) labelled += 1;
      const key = value ?? UNLABELLED;
      const bucket = buckets.get(key);
      if (bucket) bucket.push(result);
      else buckets.set(key, [result]);
    }
    // A facet nobody labelled, or one that puts everything in one bucket, has
    // not made the run navigable — try the next.
    if (labelled === 0 || buckets.size < 2) continue;
    return {
      facet,
      groups: [...buckets].map(([key, rows]) => summarise(key, rows)),
    };
  }
  return { facet: null, groups: [summarise("All samples", results)] };
}

function summarise(key: string, results: ResultRecord[]): SampleGroup {
  let total = 0;
  let scored = 0;
  let errors = 0;
  for (const result of results) {
    if (classifySample(result) === "error") errors += 1;
    const value = result.score?.value;
    if (value !== undefined && value !== null) {
      total += value;
      scored += 1;
    }
  }
  return {
    key,
    label: key,
    results,
    mean_score: scored > 0 ? total / scored : null,
    scored_count: scored,
    error_count: errors,
    sample_count: results.length,
  };
}
