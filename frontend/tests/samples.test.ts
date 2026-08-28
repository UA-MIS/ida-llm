/**
 * Grouping a run's samples.
 *
 * The failure mode this pins: grouping on the task-level outcome, which is
 * constant within a run and therefore produces one group and no navigation at
 * all — the flat table with extra chrome.
 */

import { describe, expect, it } from "vitest";

import { groupSamples } from "@/lib/samples";
import type { ResultRecord, Score } from "@/lib/types";

function score(value: number, passed: boolean | null = true): Score {
  return {
    scorer: "numeric_match",
    value,
    passed,
    explanation: "…",
    criteria: [],
    details: {},
  };
}

let seq = 0;
function record(overrides: Partial<ResultRecord> = {}): ResultRecord {
  seq += 1;
  return {
    id: `r${seq}`,
    run_id: "run_1",
    task_id: "fam/t1",
    sample_id: `s${seq}`,
    repeat_index: 0,
    model_key: "luna",
    serving_config: null as never,
    judge_serving_config: null,
    task_content_sha: null,
    score: score(1),
    scorable: true,
    cached: false,
    usage: { prompt_tokens: 1, completion_tokens: 1 },
    cost_usd: 0,
    latency_ms: 10,
    transcript_uri: "s3://b/k",
    archive_error: null,
    error: null,
    created_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

describe("groupSamples", () => {
  it("splits on the sample's own skill — the axis that actually varies", () => {
    const a = record({ sample_id: "a", score: score(1) });
    const b = record({ sample_id: "b", score: score(0) });
    const c = record({ sample_id: "c", score: score(1) });
    const grouped = groupSamples([a, b, c], {
      a: { skill: "break-even-volume", slo: "SLO2" },
      b: { skill: "break-even-volume", slo: "SLO2" },
      c: { skill: "margin-of-safety", slo: "SLO2" },
    });
    expect(grouped.facet).toBe("skill");
    expect(grouped.groups.map((g) => g.label)).toEqual([
      "break-even-volume",
      "margin-of-safety",
    ]);
    expect(grouped.groups[0]?.mean_score).toBeCloseTo(0.5, 10);
    expect(grouped.groups[1]?.mean_score).toBe(1);
  });

  it("does NOT group on the outcome, which is constant inside one run", () => {
    // Every sample shares slo: SLO2 — grouping there is one group and no
    // navigation, which is the flat table this change exists to replace.
    const grouped = groupSamples([record({ sample_id: "a" }), record({ sample_id: "b" })], {
      a: { slo: "SLO2" },
      b: { slo: "SLO2" },
    });
    expect(grouped.facet).toBeNull();
    expect(grouped.groups).toHaveLength(1);
    expect(grouped.groups[0]?.label).toBe("All samples");
  });

  it("falls back to a coarser facet when the finest one is absent", () => {
    const grouped = groupSamples([record({ sample_id: "a" }), record({ sample_id: "b" })], {
      a: { provenance: "synthetic" },
      b: { provenance: "adapted" },
    });
    expect(grouped.facet).toBe("provenance");
    expect(grouped.groups).toHaveLength(2);
  });

  it("keeps a sample whose author wrote no metadata, in a named bucket", () => {
    const grouped = groupSamples([record({ sample_id: "a" }), record({ sample_id: "b" })], {
      a: { skill: "break-even-volume" },
    });
    expect(grouped.facet).toBe("skill");
    expect(grouped.groups.map((g) => g.label)).toEqual([
      "break-even-volume",
      "Unlabelled",
    ]);
    expect(grouped.groups[1]?.sample_count).toBe(1);
  });

  it("counts errored samples without scoring them zero", () => {
    const grouped = groupSamples(
      [
        record({ sample_id: "a", score: score(1) }),
        record({ sample_id: "b", score: null, error: "connection refused" }),
        record({ sample_id: "c", score: score(1) }),
      ],
      { a: { skill: "x" }, b: { skill: "x" }, c: { skill: "y" } },
    );
    const first = grouped.groups[0];
    // A mean of 1.0 over the one sample that scored — NOT 0.5 over two.
    expect(first?.mean_score).toBe(1);
    expect(first?.scored_count).toBe(1);
    expect(first?.error_count).toBe(1);
    expect(first?.sample_count).toBe(2);
  });

  it("reports null, not zero, for a group nothing scored", () => {
    const grouped = groupSamples(
      [
        record({ sample_id: "a", score: null, scorable: false }),
        record({ sample_id: "b", score: score(1) }),
      ],
      { a: { skill: "x" }, b: { skill: "y" } },
    );
    expect(grouped.groups[0]?.mean_score).toBeNull();
  });

  it("handles a run with no results at all", () => {
    const grouped = groupSamples([], {});
    expect(grouped.groups).toHaveLength(1);
    expect(grouped.groups[0]?.sample_count).toBe(0);
    expect(grouped.groups[0]?.mean_score).toBeNull();
  });
});
