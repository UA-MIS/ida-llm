/**
 * The model-first rollup — where "null is not zero" is easiest to break.
 *
 * Every test here exists because an aggregate can launder a missing measurement
 * into a real-looking number, and the whole credibility argument of this project
 * is that it does not.
 */

import { describe, expect, it } from "vitest";

import {
  aggregate,
  filterTasks,
  findRollup,
  isRanked,
  isSeeded,
  podiumLabel,
  rollupByModel,
  rollupByOutcome,
  summariseDemonstration,
  weakestConfidence,
  type ModelTaskEntry,
} from "@/lib/rollup";
import type {
  CurriculumView,
  LeaderboardResponse,
  ModelResult,
  TaskLeaderboard,
  TrustTell,
} from "@/lib/types";

function trust(overrides: Partial<TrustTell> = {}): TrustTell {
  return {
    kind: "verifiable",
    scorer: "numeric_match",
    tier_label: "Verifiable",
    headline: "A program compared the answer to a known correct one.",
    confidence: "high",
    confidence_label: "High confidence",
    confidence_reason: "A program checked the answers against a gold key.",
    caveats: [],
    ...overrides,
  };
}

function result(overrides: Partial<ModelResult> = {}): ModelResult {
  return {
    model_key: "luna",
    display_name: "Luna",
    model_tags: ["cloud"],
    data_residency: "third_party",
    data_residency_label: "Sends data to a third party",
    enabled: true,
    recommendable: true,
    mean_score: 0.8,
    scored_count: 10,
    sample_count: 10,
    error_count: 0,
    total_cost_usd: 0.5,
    // ⚠ Present so `ModelResult` type-checks; this file's subject is not the
    // value axis. The default mirrors tests/fixtures.ts: PRICED but unsized, so
    // a value bug can never pass by a fixture quietly defaulting to "free".
    price: {
      tier: "paid",
      label: "$0.20 in / $1.20 out per million tokens",
      detail: "A million tokens is roughly 700,000 words.",
      input_usd_per_mtok: 0.2,
      output_usd_per_mtok: 1.2,
    },
    usage: { prompt_tokens: 0, completion_tokens: 0 },
    demonstration: false,
    trust: trust(),
    run_id: "run_1",
    run_status: "succeeded",
    task_content_sha: null,
    measured_at: "2026-08-01T12:00:00Z",
    ...overrides,
  };
}

function task(overrides: Partial<TaskLeaderboard> = {}): TaskLeaderboard {
  return {
    task_id: "fam/t1",
    title: "T1",
    description: "d",
    kind: "verifiable",
    domain: "business-analytics",
    scorer: "numeric_match",
    family: "fam",
    tags: [],
    slo: "SLO2",
    use_mode: "capability",
    in_benchmark: true,
    sample_count: 10,
    scorable: true,
    unscorable_reason: null,
    results: [],
    has_results: true,
    best_model_key: "luna",
    ...overrides,
  };
}

const CURRICULUM: CurriculumView = {
  available: true,
  unavailable_reason: null,
  program: "BScBA General Business (core)",
  source: null,
  outcomes: [
    { id: "SLO2", title: "Quantitative Literacy", statement: "…", text_benchmarkable: true, benchmark_note: "…" },
    { id: "SLO5", title: "Teamwork", statement: "…", text_benchmarkable: false, benchmark_note: "not text-benchmarkable" },
    { id: "SLO9", title: "General Business Knowledge", statement: "…", text_benchmarkable: true, benchmark_note: "…" },
  ],
  use_modes: [{ id: "capability", title: "Capability", statement: "Can it do this?", in_use: true }],
};

function board(tasks: TaskLeaderboard[], overrides: Partial<LeaderboardResponse> = {}): LeaderboardResponse {
  return {
    tasks,
    task_count: tasks.length,
    measured_task_count: tasks.filter((t) => t.has_results).length,
    runs_considered: tasks.reduce((n, t) => n + t.results.length, 0),
    has_any_results: tasks.some((t) => t.has_results),
    curriculum: CURRICULUM,
    benchmark_task_count: tasks.filter((t) => t.in_benchmark).length,
    slos: ["SLO2", "SLO9"],
    use_modes: ["capability"],
    families: ["fam"],
    domains: ["business-analytics"],
    ...overrides,
  };
}

function entry(overrides: Partial<ModelTaskEntry> = {}): ModelTaskEntry {
  return {
    task_id: "fam/t1",
    task_title: "T1",
    task_description: "d",
    slo: "SLO2",
    family: "fam",
    domain: "business-analytics",
    kind: "verifiable",
    in_benchmark: true,
    result: result(),
    ...overrides,
  };
}

describe("weakestConfidence", () => {
  it("returns the weakest tier, never an average", () => {
    // The trap: averaging high+low would produce a "moderate" that no single
    // measurement supports.
    expect(weakestConfidence(["high", "low"])).toBe("low");
    expect(weakestConfidence(["high", "moderate", "high"])).toBe("moderate");
    expect(weakestConfidence(["high", "high"])).toBe("high");
  });

  it("is 'none' when nothing contributed", () => {
    expect(weakestConfidence([])).toBe("none");
  });
});

describe("aggregate", () => {
  it("weights each task by the samples it actually scored", () => {
    const agg = aggregate([
      entry({ result: result({ mean_score: 1.0, scored_count: 3, sample_count: 3 }) }),
      entry({ task_id: "fam/t2", result: result({ mean_score: 0.5, scored_count: 60, sample_count: 60 }) }),
    ]);
    // Mean-of-means would be 0.75 and would let the 3-sample task nearly halve
    // the verdict of a 60-sample one.
    expect(agg.score).toBeCloseTo((1.0 * 3 + 0.5 * 60) / 63, 10);
    expect(agg.score).not.toBeCloseTo(0.75, 3);
    expect(agg.scored_samples).toBe(63);
    expect(agg.measured_tasks).toBe(2);
  });

  it("EXCLUDES an unmeasured task rather than scoring it zero", () => {
    const withGap = aggregate([
      entry({ result: result({ mean_score: 0.9, scored_count: 10 }) }),
      entry({
        task_id: "fam/t2",
        result: result({ mean_score: null, scored_count: 0, sample_count: 5, trust: trust({ confidence: "none" }) }),
      }),
    ]);
    expect(withGap.score).toBe(0.9);
    expect(withGap.measured_tasks).toBe(1);
    // Coverage is reported separately — that is how the gap stays visible.
    expect(withGap.covered_tasks).toBe(2);
  });

  it("returns null, not 0, when nothing was measured at all", () => {
    const agg = aggregate([
      entry({ result: result({ mean_score: null, scored_count: 0, trust: trust({ confidence: "none" }) }) }),
    ]);
    expect(agg.score).toBeNull();
    expect(agg.confidence).toBe("none");
  });

  it("is empty — not zero — for no entries", () => {
    expect(aggregate([]).score).toBeNull();
    expect(aggregate([]).covered_tasks).toBe(0);
  });

  it("takes the weakest confidence among the measurements that fed the score", () => {
    const agg = aggregate([
      entry({ result: result({ trust: trust({ confidence: "high" }) }) }),
      entry({ task_id: "fam/t2", result: result({ trust: trust({ kind: "subjective", confidence: "low" }) }) }),
    ]);
    expect(agg.confidence).toBe("low");
  });

  it("ignores the confidence of a row that contributed no score", () => {
    const agg = aggregate([
      entry({ result: result({ trust: trust({ confidence: "high" }) }) }),
      entry({
        task_id: "fam/t2",
        result: result({ mean_score: null, scored_count: 0, trust: trust({ confidence: "none" }) }),
      }),
    ]);
    expect(agg.confidence).toBe("high");
  });

  it("reports how much of the weight was programmatically checked", () => {
    const agg = aggregate([
      entry({ kind: "verifiable", result: result({ scored_count: 30, mean_score: 0.5 }) }),
      entry({ task_id: "fam/t2", kind: "subjective", result: result({ scored_count: 10, mean_score: 0.5 }) }),
    ]);
    expect(agg.verifiable_share).toBeCloseTo(0.75, 10);
  });

  it("sums cost and errors over every covered task, measured or not", () => {
    const agg = aggregate([
      entry({ result: result({ total_cost_usd: 1.5, error_count: 2, sample_count: 10 }) }),
      entry({
        task_id: "fam/t2",
        result: result({ mean_score: null, scored_count: 0, total_cost_usd: 0.5, error_count: 5, sample_count: 5 }),
      }),
    ]);
    expect(agg.total_cost_usd).toBeCloseTo(2.0, 10);
    expect(agg.error_count).toBe(7);
    expect(agg.sample_count).toBe(15);
  });

  it("links the newest contributing run as the receipt", () => {
    const agg = aggregate([
      entry({ result: result({ run_id: "run_old", measured_at: "2026-01-01T00:00:00Z" }) }),
      entry({ task_id: "fam/t2", result: result({ run_id: "run_new", measured_at: "2026-07-01T00:00:00Z" }) }),
    ]);
    expect(agg.latest_run_id).toBe("run_new");
    expect(agg.latest_measured_at).toBe("2026-07-01T00:00:00Z");
  });
});

describe("rollupByModel", () => {
  const two = board([
    task({
      task_id: "fam/t1",
      slo: "SLO2",
      results: [
        result({ model_key: "luna", display_name: "Luna", mean_score: 0.9, scored_count: 10 }),
        result({ model_key: "sol", display_name: "Sol", mean_score: 0.4, scored_count: 10 }),
      ],
    }),
    task({
      task_id: "fam/t2",
      slo: "SLO9",
      results: [result({ model_key: "luna", display_name: "Luna", mean_score: 0.7, scored_count: 10 })],
    }),
  ]);

  it("regroups every task x model pairing by model", () => {
    const rollups = rollupByModel(two);
    expect(rollups.map((r) => r.model_key)).toEqual(["luna", "sol"]);
    expect(rollups[0]?.entries).toHaveLength(2);
    expect(rollups[1]?.entries).toHaveLength(1);
  });

  it("ranks by the sample-weighted overall score, best first", () => {
    const rollups = rollupByModel(two);
    expect(rollups[0]?.overall.score).toBeCloseTo(0.8, 10);
    expect(rollups[1]?.overall.score).toBeCloseTo(0.4, 10);
  });

  it("lists the outcomes a model actually has a score under, in board order", () => {
    const rollups = rollupByModel(two);
    expect(rollups[0]?.slos_measured).toEqual(["SLO2", "SLO9"]);
    expect(rollups[1]?.slos_measured).toEqual(["SLO2"]);
  });

  it("sorts a test stub BELOW every real measured model, however well it scored", () => {
    const withStub = board([
      task({
        results: [
          result({ model_key: "luna", display_name: "Luna", mean_score: 0.4 }),
          result({
            model_key: "mock",
            display_name: "Mock",
            recommendable: false,
            data_residency: "not_a_real_model",
            mean_score: 1.0,
          }),
        ],
      }),
    ]);
    const rollups = rollupByModel(withStub);
    expect(rollups.map((r) => r.model_key)).toEqual(["luna", "mock"]);
    // Shown, never hidden — and never ranked.
    expect(isRanked(rollups[0]!)).toBe(true);
    expect(isRanked(rollups[1]!)).toBe(false);
  });

  it("sorts a model with nothing measured last, and does not rank it", () => {
    const withGap = board([
      task({
        results: [
          result({ model_key: "luna", mean_score: 0.4 }),
          result({
            model_key: "aria",
            display_name: "Aria",
            mean_score: null,
            scored_count: 0,
            trust: trust({ confidence: "none" }),
          }),
        ],
      }),
    ]);
    const rollups = rollupByModel(withGap);
    expect(rollups.map((r) => r.model_key)).toEqual(["luna", "aria"]);
    expect(isRanked(rollups[1]!)).toBe(false);
  });

  it("breaks a tie on the mean with the model that measured more samples", () => {
    const tied = board([
      task({
        results: [
          result({ model_key: "thin", display_name: "Thin", mean_score: 0.5, scored_count: 4 }),
          result({ model_key: "thick", display_name: "Thick", mean_score: 0.5, scored_count: 40 }),
        ],
      }),
    ]);
    expect(rollupByModel(tied).map((r) => r.model_key)).toEqual(["thick", "thin"]);
  });

  it("takes identity from the model's newest row, so a registry edit is reflected", () => {
    const renamed = board([
      task({
        task_id: "fam/t1",
        results: [result({ model_key: "luna", display_name: "Luna (old)", enabled: true, measured_at: "2026-01-01T00:00:00Z" })],
      }),
      task({
        task_id: "fam/t2",
        results: [result({ model_key: "luna", display_name: "Luna", enabled: false, measured_at: "2026-07-01T00:00:00Z" })],
      }),
    ]);
    const rollup = rollupByModel(renamed)[0];
    expect(rollup?.display_name).toBe("Luna");
    expect(rollup?.enabled).toBe(false);
  });

  it("finds one model by key, and returns undefined for an unknown one", () => {
    expect(findRollup(two, "sol")?.display_name).toBe("Sol");
    expect(findRollup(two, "nope")).toBeUndefined();
  });

  it("is empty for a board with no results at all", () => {
    expect(rollupByModel(board([task({ results: [], has_results: false })]))).toEqual([]);
  });
});

describe("rollupByOutcome", () => {
  const partial = board([
    task({ task_id: "fam/t1", slo: "SLO2", results: [result({ mean_score: 0.9, scored_count: 10 })] }),
    task({ task_id: "fam/t2", slo: "SLO2", results: [] , has_results: false }),
    task({
      task_id: "fam/t3",
      slo: null,
      in_benchmark: false,
      results: [result({ mean_score: 0.2, scored_count: 5 })],
    }),
  ]);

  it("gives EVERY curriculum outcome a row, including ones never measured", () => {
    const rows = rollupByOutcome(findRollup(partial, "luna")!, partial);
    // Nine-in-the-programme means nine rows, not "the ones with data".
    expect(rows.filter((r) => r.slo !== null).map((r) => r.slo)).toEqual([
      "SLO2",
      "SLO5",
      "SLO9",
    ]);
  });

  it("says an unmeasured outcome is null, never zero", () => {
    const rows = rollupByOutcome(findRollup(partial, "luna")!, partial);
    const slo9 = rows.find((r) => r.slo === "SLO9");
    expect(slo9?.aggregate.score).toBeNull();
    expect(slo9?.aggregate.covered_tasks).toBe(0);
  });

  it("shows partial coverage as measured-of-available", () => {
    const rows = rollupByOutcome(findRollup(partial, "luna")!, partial);
    const slo2 = rows.find((r) => r.slo === "SLO2");
    expect(slo2?.aggregate.measured_tasks).toBe(1);
    // Two SLO2 tasks exist in the catalogue; this model has one measured.
    expect(slo2?.tasks_available).toBe(2);
  });

  it("carries the curriculum's own wording, never a paraphrase", () => {
    const rows = rollupByOutcome(findRollup(partial, "luna")!, partial);
    expect(rows.find((r) => r.slo === "SLO2")?.heading).toBe("SLO2 · Quantitative Literacy");
    expect(rows.find((r) => r.slo === "SLO5")?.outcome?.text_benchmarkable).toBe(false);
  });

  it("files non-benchmark tasks in their own row rather than under an outcome", () => {
    const rows = rollupByOutcome(findRollup(partial, "luna")!, partial);
    const unfiled = rows.find((r) => r.slo === null);
    expect(unfiled?.aggregate.score).toBeCloseTo(0.2, 10);
    expect(unfiled?.heading).toBe("Outside the SLO benchmark");
  });

  it("omits the unfiled row entirely when every task is in the benchmark", () => {
    const all = board([task({ results: [result()] })]);
    const rows = rollupByOutcome(findRollup(all, "luna")!, all);
    expect(rows.some((r) => r.slo === null)).toBe(false);
  });

  it("falls back to the ids present when the curriculum is unavailable", () => {
    const noCurriculum = board([task({ results: [result()] })], {
      curriculum: {
        available: false,
        unavailable_reason: "No curriculum/slo.yaml in this deployment.",
        program: null,
        source: null,
        outcomes: [],
        use_modes: [],
      },
    });
    const rows = rollupByOutcome(findRollup(noCurriculum, "luna")!, noCurriculum);
    // Bare ids — honest — rather than nine invented titles.
    expect(rows.map((r) => r.heading)).toEqual(["SLO2", "SLO9"]);
  });
});

describe("filterTasks", () => {
  const tasks = [
    task({ task_id: "fam/break-even", title: "Break-even chains", slo: "SLO2", has_results: true }),
    task({ task_id: "fam/ethics", title: "Ethical reasoning", slo: "SLO6", has_results: true, in_benchmark: true }),
    task({ task_id: "demo/quiz", title: "Demo quiz", slo: null, in_benchmark: false, has_results: false }),
  ];

  it("shows only measured tasks by default", () => {
    expect(filterTasks(tasks, {}).map((t) => t.task_id)).toEqual(["fam/break-even", "fam/ethics"]);
  });

  it("includes unmeasured tasks on request — they are a fact, not noise", () => {
    expect(filterTasks(tasks, { includeUnmeasured: true })).toHaveLength(3);
  });

  it("narrows to one outcome", () => {
    expect(filterTasks(tasks, { slo: "SLO2" }).map((t) => t.task_id)).toEqual(["fam/break-even"]);
  });

  it("searches title, id and description case-insensitively", () => {
    expect(filterTasks(tasks, { query: "BREAK" }).map((t) => t.task_id)).toEqual(["fam/break-even"]);
    expect(filterTasks(tasks, { query: "ethic" }).map((t) => t.task_id)).toEqual(["fam/ethics"]);
    expect(filterTasks(tasks, { query: "   " })).toHaveLength(2);
  });

  it("narrows to the benchmark", () => {
    expect(filterTasks(tasks, { benchmark: true, includeUnmeasured: true }).map((t) => t.task_id)).toEqual([
      "fam/break-even",
      "fam/ethics",
    ]);
  });

  it("returns nothing rather than everything when nothing matches", () => {
    expect(filterTasks(tasks, { query: "zzzz" })).toEqual([]);
  });
});

/**
 * The podium's label, which has to describe the list it sits above.
 *
 * It was the literal "Every model we have measured, by overall score", printed
 * over `filter(isRanked).slice(0, 5)`. Live that was two rows drawn from six
 * measured models, so both halves of the sentence were false — and it got worse
 * with every model added.
 */
describe("podiumLabel", () => {
  it("claims 'every model' ONLY when the list really is every measured model", () => {
    expect(podiumLabel(3, 3, 3)).toBe("Every model we have measured, by overall score");
  });

  it("does not claim 'every model' when measured models are missing from it", () => {
    // The live shape: six measured, two rankable, two shown.
    const label = podiumLabel(2, 2, 6);
    expect(label).not.toMatch(/every model/i);
    expect(label).toContain("4 more were measured");
  });

  it("says so when the list is truncated", () => {
    const label = podiumLabel(5, 9, 9);
    expect(label).toContain("top 5 of 9");
  });

  it("does not pluralise a single model into a ranking", () => {
    expect(podiumLabel(1, 1, 3)).toContain("one model");
  });

  it("says nothing rankable rather than labelling an empty list", () => {
    expect(podiumLabel(0, 0, 0)).toMatch(/no model has a rankable score/i);
  });
});

/**
 * ⚠ D-92: `isSeeded` AND `summariseDemonstration` USED TO LIVE ONLY IN
 * `lib/overview.ts`, PRIVATE TO THAT PAGE. `/leaderboard`, `/compare` and
 * `/models/[key]` regroup the exact same `ModelResult.demonstration` flag
 * through this same rollup and had no way to ask the same question — so they
 * rendered every seeded row as a flat, unqualified finding. These now live
 * beside the rollup every page reads, so the four pages cannot disagree about
 * what is real.
 */
describe("isSeeded", () => {
  it("is true when every scored row behind a model was seeded", () => {
    const [rollup] = rollupByModel(
      board([task({ results: [result({ demonstration: true })] })]),
    );
    expect(isSeeded(rollup!)).toBe(true);
  });

  it("is false when even one scored row was a real measurement", () => {
    const [rollup] = rollupByModel(
      board([
        task({
          task_id: "fam/t1",
          results: [result({ demonstration: true })],
        }),
        task({
          task_id: "fam/t2",
          results: [result({ demonstration: false })],
        }),
      ]),
    );
    // ⚠ THE CASE A MODEL-LEVEL BADGE MUST NOT MISS. A model with one real
    // task and one seeded one is not "illustrative" — labelling its whole row
    // that way would be its own dishonesty in the other direction.
    expect(isSeeded(rollup!)).toBe(false);
  });

  it("is false for a model with nothing scored at all", () => {
    const [rollup] = rollupByModel(
      board([task({ results: [result({ mean_score: null, scored_count: 0 })] })]),
    );
    expect(isSeeded(rollup!)).toBe(false);
  });
});

describe("summariseDemonstration", () => {
  function rollupsFor(results: ModelResult[]): ReturnType<typeof rollupByModel> {
    return rollupByModel(
      board(
        results.map((r, index) =>
          task({ task_id: `fam/t${index}`, best_model_key: r.model_key, results: [r] }),
        ),
      ),
    );
  }

  it("reports a wholly seeded set as illustrative", () => {
    const tell = summariseDemonstration(
      rollupsFor([result({ model_key: "luna", demonstration: true })]),
    );
    expect(tell.any).toBe(true);
    expect(tell.all).toBe(true);
    expect(tell.notice.toLowerCase()).toMatch(/illustrat/);
  });

  it("distinguishes a partly seeded set from a wholly seeded one", () => {
    const tell = summariseDemonstration(
      rollupsFor([
        result({ model_key: "luna", demonstration: true }),
        result({ model_key: "vega", demonstration: false }),
      ]),
    );
    expect(tell.any).toBe(true);
    expect(tell.all).toBe(false);
    expect(tell.notice).toContain("1 of the 2 models here has been");
    expect(tell.notice).not.toMatch(/models here have been/);
  });

  it("says nothing when nothing was seeded", () => {
    const tell = summariseDemonstration(rollupsFor([result({ model_key: "luna" })]));
    expect(tell.any).toBe(false);
    expect(tell.all).toBe(false);
    expect(tell.notice).toBe("");
  });

  it("names the unit ('row' vs 'card') in the mixed-set sentence, for the page reading it", () => {
    const mixed = [
      result({ model_key: "luna", demonstration: true }),
      result({ model_key: "vega", demonstration: false }),
    ];
    expect(summariseDemonstration(rollupsFor(mixed), "row").notice).toContain(
      "Each row says which.",
    );
    expect(summariseDemonstration(rollupsFor(mixed), "card").notice).toContain(
      "Each card says which.",
    );
  });
});
