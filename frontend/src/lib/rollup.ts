/**
 * Per-MODEL rollups, computed from the task-first leaderboard.
 *
 * ⚠ WHY THIS IS CLIENT-OF-THE-API ARITHMETIC AND NOT A NEW ENDPOINT.
 * `GET /leaderboard` with no filters already returns every task × model pairing
 * in one response. A model-first view is the same facts read down the other
 * axis, so regrouping here costs one pass over data we already fetched, and it
 * cannot disagree with the task view the way a second server-side aggregation
 * eventually would.
 *
 * ⚠ THE TWO HONESTY RULES THE REST OF THIS APP LIVES BY APPLY HERE TOO, and an
 * aggregate is where they are easiest to break:
 *
 *   1. **Null is not zero.** A task a model was never measured on contributes
 *      NOTHING — it is not a 0.0 dragging the mean down. Coverage is reported
 *      as its own number (`measured_tasks` of `covered_tasks`) so a model that
 *      scored well on two tasks cannot be mistaken for one that scored well on
 *      twenty.
 *   2. **An aggregate is only as good as its weakest constituent.** Confidence
 *      is the WEAKEST tier among the measurements that actually fed the number,
 *      never an average — averaging "high" with "low" would manufacture a
 *      "moderate" nobody measured.
 *
 * The mean itself is SAMPLE-WEIGHTED: `Σ(mean_score × scored_count) / Σ
 * scored_count`. A mean-of-means lets a 3-sample task outvote a 60-sample one,
 * which is how a model wins a benchmark on its smallest evidence.
 *
 * Pure functions, no React, no fetch — which is what makes every rule above
 * testable without rendering anything.
 */

import type {
  Confidence,
  DataResidency,
  LeaderboardResponse,
  ModelResult,
  OutcomeView,
  TaskLeaderboard,
} from "./types";

/** One model's standing on one task, with the task context it needs to group. */
export interface ModelTaskEntry {
  task_id: string;
  task_title: string;
  task_description: string;
  slo: string | null;
  family: string;
  domain: string;
  kind: TaskLeaderboard["kind"];
  in_benchmark: boolean;
  result: ModelResult;
}

/** Weakest-first. `indexOf` on this is the comparison. */
export const CONFIDENCE_ORDER: Confidence[] = ["none", "low", "moderate", "high"];

/**
 * The weakest tier in a set.
 *
 * Not an average, deliberately: an overall number is exactly as trustworthy as
 * the shakiest measurement inside it, and averaging tiers would invent a
 * confidence level that no measurement supports.
 */
export function weakestConfidence(tiers: Confidence[]): Confidence {
  if (tiers.length === 0) return "none";
  return tiers.reduce((worst, tier) =>
    CONFIDENCE_ORDER.indexOf(tier) < CONFIDENCE_ORDER.indexOf(worst) ? tier : worst,
  );
}

export function confidenceLabel(confidence: Confidence): string {
  switch (confidence) {
    case "high":
      return "High confidence";
    case "moderate":
      return "Moderate confidence";
    case "low":
      return "Low confidence";
    case "none":
      return "Not scored";
  }
}

/** A score plus everything needed to say what it is made of. */
export interface ScoreAggregate {
  /** Null — never 0 — when nothing under this heading was measured. */
  score: number | null;
  /** Samples that actually produced a score. The weight behind `score`. */
  scored_samples: number;
  /** Samples attempted across every covered task. */
  sample_count: number;
  error_count: number;
  /** Tasks that produced a score. */
  measured_tasks: number;
  /** Tasks this model has a row for at all, measured or not. */
  covered_tasks: number;
  /** The weakest tier among the measurements that fed `score`. */
  confidence: Confidence;
  /** Share of the weight that came from programmatically-checked tasks, 0..1. */
  verifiable_share: number;
  total_cost_usd: number;
  /** The newest contributing measurement — the receipt worth linking. */
  latest_measured_at: string | null;
  latest_run_id: string | null;
}

const EMPTY_AGGREGATE: ScoreAggregate = {
  score: null,
  scored_samples: 0,
  sample_count: 0,
  error_count: 0,
  measured_tasks: 0,
  covered_tasks: 0,
  confidence: "none",
  verifiable_share: 0,
  total_cost_usd: 0,
  latest_measured_at: null,
  latest_run_id: null,
};

/**
 * Reduce a model's task rows to one honest number plus its provenance.
 *
 * A row with `mean_score: null` or `scored_count: 0` is counted for COVERAGE
 * and cost and nothing else. It never enters the numerator, and it never enters
 * the denominator — which is the difference between "not measured" and "scored
 * zero", and the whole reason this project exists.
 */
export function aggregate(entries: ModelTaskEntry[]): ScoreAggregate {
  if (entries.length === 0) return { ...EMPTY_AGGREGATE };

  let weightedTotal = 0;
  let weight = 0;
  let verifiableWeight = 0;
  let sampleCount = 0;
  let errorCount = 0;
  let measuredTasks = 0;
  let cost = 0;
  const tiers: Confidence[] = [];
  let latestAt: string | null = null;
  let latestRun: string | null = null;

  for (const entry of entries) {
    const { result } = entry;
    sampleCount += result.sample_count;
    errorCount += result.error_count;
    cost += result.total_cost_usd;

    if (result.mean_score === null || result.scored_count <= 0) continue;

    measuredTasks += 1;
    weightedTotal += result.mean_score * result.scored_count;
    weight += result.scored_count;
    if (entry.kind === "verifiable") verifiableWeight += result.scored_count;
    tiers.push(result.trust.confidence);

    // Newest contributing measurement. A row with no timestamp still counts as
    // evidence; it just cannot win the "most recent" comparison.
    if (
      result.measured_at !== null &&
      (latestAt === null || result.measured_at > latestAt)
    ) {
      latestAt = result.measured_at;
      latestRun = result.run_id;
    } else if (latestRun === null) {
      latestRun = result.run_id;
    }
  }

  return {
    score: weight > 0 ? weightedTotal / weight : null,
    scored_samples: weight,
    sample_count: sampleCount,
    error_count: errorCount,
    measured_tasks: measuredTasks,
    covered_tasks: entries.length,
    confidence: weakestConfidence(tiers),
    verifiable_share: weight > 0 ? verifiableWeight / weight : 0,
    total_cost_usd: cost,
    latest_measured_at: latestAt,
    latest_run_id: latestRun,
  };
}

/** One model, read across the whole benchmark. */
export interface ModelRollup {
  model_key: string;
  display_name: string;
  model_tags: string[];
  data_residency: DataResidency;
  data_residency_label: string;
  enabled: boolean;
  /** False for test stubs. They are shown, never ranked — see `isRanked`. */
  recommendable: boolean;
  overall: ScoreAggregate;
  /** Outcome ids this model has a real score under, in board order. */
  slos_measured: string[];
  entries: ModelTaskEntry[];
}

/**
 * Whether a model belongs in the numbered ranking.
 *
 * A test stub is real data and is shown — but `best_model_key` already excludes
 * stubs "so the winner is never a fixture", and a leaderboard whose #1 is a
 * deterministic mock is the same lie one row higher.
 */
export function isRanked(rollup: ModelRollup): boolean {
  return rollup.recommendable && rollup.overall.score !== null;
}

function tierOf(rollup: ModelRollup): number {
  if (isRanked(rollup)) return 0;
  if (rollup.overall.score !== null) return 1; // measured, but a stub
  return 2; // nothing measured
}

/**
 * Regroup the task-first board by model.
 *
 * Identity fields (display name, residency, whether it is still runnable) are
 * taken from the model's most recent row rather than its first: the registry
 * can be edited between runs, and the newest row is the one that reflects the
 * registry a reader would see today.
 */
export function rollupByModel(board: LeaderboardResponse): ModelRollup[] {
  const byKey = new Map<string, ModelTaskEntry[]>();

  for (const task of board.tasks) {
    for (const result of task.results) {
      const entry: ModelTaskEntry = {
        task_id: task.task_id,
        task_title: task.title,
        task_description: task.description,
        slo: task.slo,
        family: task.family,
        domain: task.domain,
        kind: task.kind,
        in_benchmark: task.in_benchmark,
        result,
      };
      const bucket = byKey.get(result.model_key);
      if (bucket) bucket.push(entry);
      else byKey.set(result.model_key, [entry]);
    }
  }

  const rollups: ModelRollup[] = [];
  for (const [modelKey, entries] of byKey) {
    const newest = entries.reduce((best, entry) =>
      (entry.result.measured_at ?? "") > (best.result.measured_at ?? "") ? entry : best,
    );
    const identity = newest.result;
    const measuredSlos = new Set(
      entries
        .filter((e) => e.result.mean_score !== null && e.result.scored_count > 0)
        .map((e) => e.slo)
        .filter((slo): slo is string => slo !== null),
    );
    rollups.push({
      model_key: modelKey,
      display_name: identity.display_name,
      model_tags: identity.model_tags,
      data_residency: identity.data_residency,
      data_residency_label: identity.data_residency_label,
      enabled: identity.enabled,
      recommendable: identity.recommendable,
      overall: aggregate(entries),
      slos_measured: board.slos.filter((slo) => measuredSlos.has(slo)),
      entries,
    });
  }

  return rollups.sort((a, b) => {
    const tier = tierOf(a) - tierOf(b);
    if (tier !== 0) return tier;
    if (a.overall.score !== null && b.overall.score !== null) {
      if (b.overall.score !== a.overall.score) return b.overall.score - a.overall.score;
      // A tie on the mean goes to the model that backed it with more evidence.
      if (b.overall.scored_samples !== a.overall.scored_samples) {
        return b.overall.scored_samples - a.overall.scored_samples;
      }
    }
    return a.display_name.localeCompare(b.display_name);
  });
}

export function findRollup(
  board: LeaderboardResponse,
  modelKey: string,
): ModelRollup | undefined {
  return rollupByModel(board).find((rollup) => rollup.model_key === modelKey);
}

/** One outcome row on a model's report card. */
export interface OutcomeRollup {
  /** Null is the "outside the benchmark" row, not a missing value. */
  slo: string | null;
  outcome: OutcomeView | undefined;
  heading: string;
  aggregate: ScoreAggregate;
  entries: ModelTaskEntry[];
  /** Tasks the catalogue files under this outcome, whoever measured them. */
  tasks_available: number;
}

/**
 * A model against every outcome the programme publishes — including the ones it
 * has never been measured on.
 *
 * ⚠ THE UNCOVERED ROWS ARE THE POINT. Listing only the outcomes a model happens
 * to have data for turns a report card into a highlight reel: seven strong rows
 * read as full coverage when the model was only ever run on seven of nine. Every
 * outcome in the curriculum gets a row, and an unmeasured one says so in words
 * rather than rendering a 0.
 */
export function rollupByOutcome(
  rollup: ModelRollup,
  board: LeaderboardResponse,
): OutcomeRollup[] {
  // The curriculum is the row set when it is loaded — all nine outcomes, in the
  // programme's order. Without it, fall back to the ids the API found present:
  // an id is honest, and a made-up list of nine is not.
  const outcomes = board.curriculum.available ? board.curriculum.outcomes : [];
  const ids = board.curriculum.available ? outcomes.map((o) => o.id) : board.slos;

  const available = new Map<string | null, number>();
  for (const task of board.tasks) {
    available.set(task.slo, (available.get(task.slo) ?? 0) + 1);
  }

  const rows: OutcomeRollup[] = ids.map((id, index) => {
    const outcome = outcomes[index];
    const entries = rollup.entries.filter((entry) => entry.slo === id);
    return {
      slo: id,
      outcome,
      heading: outcome ? `${outcome.id} · ${outcome.title}` : id,
      aggregate: aggregate(entries),
      entries,
      tasks_available: available.get(id) ?? 0,
    };
  });

  // Everything the benchmark does not file under an outcome — the demo and
  // exemplar families. Real measurements; just not part of the SLO claim, so
  // they get their own row instead of being folded into one.
  const unfiled = rollup.entries.filter((entry) => entry.slo === null);
  if (unfiled.length > 0) {
    rows.push({
      slo: null,
      outcome: undefined,
      heading: "Outside the SLO benchmark",
      aggregate: aggregate(unfiled),
      entries: unfiled,
      tasks_available: available.get(null) ?? 0,
    });
  }
  return rows;
}

// ---------------------------------------------------------------------------
// The compact filter that replaced the chip wall
// ---------------------------------------------------------------------------

export interface TaskFilter {
  slo?: string;
  useMode?: string;
  benchmark?: boolean;
  /** Free text over title, description, id and plain tags. */
  query?: string;
  /** Show tasks nothing has been measured on yet. Off by default. */
  includeUnmeasured?: boolean;
}

/**
 * Narrow the catalogue in one pass, in the page.
 *
 * Filtering used to be a round trip per chip. The whole board arrives in one
 * response anyway (the model rollup needs all of it), and these predicates are
 * the same field equality the API applies — so a second fetch would buy nothing
 * but latency and a chance to disagree with itself.
 */
export function filterTasks(
  tasks: TaskLeaderboard[],
  filter: TaskFilter,
): TaskLeaderboard[] {
  const needle = filter.query?.trim().toLowerCase() ?? "";
  return tasks.filter((task) => {
    if (filter.slo && task.slo !== filter.slo) return false;
    if (filter.useMode && task.use_mode !== filter.useMode) return false;
    if (filter.benchmark && !task.in_benchmark) return false;
    if (!filter.includeUnmeasured && !task.has_results) return false;
    if (needle) {
      const haystack = [task.title, task.description, task.task_id, ...task.tags]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}

/** How `score` was computed, in one sentence, wherever an overall number shows. */
export const WEIGHTING_NOTE =
  "Sample-weighted mean across the tasks this model was measured on: each task " +
  "counts for as many samples as it actually scored, so a six-sample task cannot " +
  "outweigh a sixty-sample one. Tasks with no measurement are excluded, never " +
  "counted as zero.";

/**
 * The podium's own label, which must describe the list it actually sits above.
 *
 * ⚠ IT USED TO BE THE LITERAL "Every model we have measured, by overall score",
 * and both halves were false. The podium is `filter(isRanked).slice(0, 5)`, so
 * it shows neither *every* model (unranked models were measured too — that is
 * how we know they are unranked) nor necessarily every *ranked* one. Live it
 * read "every model" above two rows drawn from six measured models, and it got
 * worse with each model added.
 *
 * Two separate counts, because they answer two separate questions: how many
 * models have a number at all, and how many of those this list is showing.
 */
export function podiumLabel(shown: number, ranked: number, measured: number): string {
  if (shown === 0) return "No model has a rankable score yet";
  if (shown === measured) return "Every model we have measured, by overall score";
  if (shown < ranked) {
    return `The top ${shown} of ${ranked} ranked models, by overall score`;
  }
  // Every ranked model is shown, but some measured models are not ranked at all.
  const unranked = measured - shown;
  return (
    `The ${shown === 1 ? "one model" : `${shown} models`} we can rank, by overall score` +
    ` — ${unranked} more ${unranked === 1 ? "was" : "were"} measured but cannot be ranked`
  );
}
