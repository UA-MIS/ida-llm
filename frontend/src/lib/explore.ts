/**
 * The guided drill-down: programme → course → outcome → evidence.
 *
 * ⚠ WHY THIS EXISTS ALONGSIDE `lib/matrix.ts` RATHER THAN INSTEAD OF IT. The
 * comparison grid answers "which model is best at what" and shows every model
 * against every outcome at once — which is the right shape for a reader who
 * already knows what they are looking at, and the wrong shape for the one the
 * client described: a professor who teaches MIS 200, wants to know how the
 * models do on the outcomes MIS 200 is responsible for, and should not have to
 * read a nine-column matrix to find out. That reader drills; they do not scan.
 *
 * So this module regroups the SAME response along the axis the curriculum
 * already publishes: the coverage grid. One level per question:
 *
 *   1. programme   which programmes are on this platform, and how do they read
 *   2. course      which courses does this programme have, and how do they read
 *   3. outcome     which outcomes does this course teach, and how do they read
 *   4. evidence    for one (course, outcome) pair: which model, on what, from
 *                  which run — the receipts
 *
 * ⚠ THIS FILE INVENTS NO NUMBER. Every score comes from `aggregate()` in
 * lib/rollup.ts — the sample-weighted mean, with the weakest-constituent
 * confidence rule and the null-is-not-zero rule already in it. What this module
 * adds is grouping and four honest empty states, not arithmetic.
 *
 * ⚠ THE THREE EMPTIES ARE THREE DIFFERENT CLAIMS, and a grid is where they are
 * easiest to confuse:
 *
 *   measured           a real score, from finished, scored runs
 *   not_measured       the pair is in scope and nothing has been run — "not
 *                      measured yet", never a number and never a blank
 *   not_benchmarkable  the curriculum says a text benchmark CANNOT measure the
 *                      outcome (SLO5 Teamwork, SLO8 Oral Communication)
 *
 * The third is the one that has to survive every refactor. `curriculum/slo.yaml`
 * calls scoring SLO5 from a single-turn prompt "the most misleading thing in
 * this repository"; a course tile that showed MIS 200 or GBA 300 as simply
 * *empty* on teamwork would be making that claim with whitespace.
 */

import {
  aggregate,
  summariseDemonstration,
  isSeeded,
  rollupByModel,
  type DemonstrationTell,
  type ModelRollup,
  type ModelTaskEntry,
  type ScoreAggregate,
} from "./rollup";
import type {
  CourseCoverageView,
  LeaderboardResponse,
  OutcomeView,
  TaskLeaderboard,
} from "./types";

// ---------------------------------------------------------------------------
// Slugs
// ---------------------------------------------------------------------------

/**
 * A URL segment for a name the curriculum owns.
 *
 * ⚠ DERIVED, NOT STORED, AND THAT IS A DELIBERATE TRADE. `curriculum/slo.yaml`
 * has no id for a programme or a course — it has the registrar's display
 * strings — and adding one would mean editing the published map to serve a
 * route. So the slug is computed, and every lookup goes back through the same
 * function rather than comparing a slug to a slug stored somewhere else. The
 * cost is that renaming a course in the map changes its URL; the alternative
 * was a second spelling of the course code that could disagree with the first.
 */
export function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// ---------------------------------------------------------------------------
// Coverage levels
// ---------------------------------------------------------------------------

/**
 * The published map's legend, spelled out.
 *
 * ⚠ NOT AN ORDERING. `M+A` is not "more than" `A`: they are a different pair of
 * claims (this course masters the outcome, AND the programme measures it here).
 * `ida_core.curriculum` says so about the enum and it stays true on the wire, so
 * nothing here sorts on these.
 */
const LEVEL_LABELS: Record<string, string> = {
  I: "Introduced",
  R: "Reinforced",
  M: "Mastered",
  A: "Assessment point",
  "M+A": "Mastered · assessment point",
};

export function levelLabel(level: string): string {
  return LEVEL_LABELS[level] ?? level;
}

/** The levels at which the programme actually reports on an outcome. */
const ASSESSMENT_LEVELS = new Set(["A", "M+A"]);

export function isAssessmentPoint(level: string): boolean {
  return ASSESSMENT_LEVELS.has(level);
}

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

export type ExploreStatus = "measured" | "not_measured" | "not_benchmarkable";

/** The wording for an unmeasured pair. One string, so four surfaces agree. */
export const NOT_MEASURED = "Not measured yet";

/** The wording for an outcome a text benchmark cannot reach at all. */
export const NOT_TEXT_MEASURABLE = "Not text-measurable";

/** One outcome as one course teaches it. Level 3's tile, and level 4's subject. */
export interface OutcomeTile {
  slo: string;
  title: string;
  statement: string;
  /** The curriculum's own words on how (or whether) this outcome is scored. */
  note: string;
  /** The published level for THIS course. */
  level: string;
  level_label: string;
  assessment_point: boolean;
  benchmarkable: boolean;
  status: ExploreStatus;
  aggregate: ScoreAggregate;
  /** Tasks the catalogue files under this outcome, whoever has run them. */
  tasks_available: number;
  /** How many models have a real score here. Coverage, stated not implied. */
  models_measured: number;
  /** Always populated, always specific — the tile's own caption. */
  reason: string;
}

/** One course of a programme. Level 2's tile, and level 3's subject. */
export interface CourseTile {
  slug: string;
  code: string;
  title: string;
  /** Every outcome this course teaches, in curriculum order. */
  outcomes: OutcomeTile[];
  /** Outcomes this course teaches that a text benchmark can reach. */
  benchmarkable_count: number;
  /** Of those, how many have a score. */
  measured_count: number;
  /** Outcomes this course is an assessment point for — what the department grades. */
  assessment_count: number;
  status: ExploreStatus;
  aggregate: ScoreAggregate;
  reason: string;
}

/** One programme. Level 1's tile, and level 2's subject. */
export interface MajorTile {
  slug: string;
  name: string;
  source: string | null;
  course_count: number;
  outcome_count: number;
  benchmarkable_count: number;
  measured_count: number;
  models_measured: number;
  status: ExploreStatus;
  aggregate: ScoreAggregate;
  reason: string;
}

/** What every level needs to render, plus the honest reason it might be empty. */
export interface ExploreIndex {
  available: boolean;
  unavailable_reason: string | null;
  majors: MajorTile[];
  demonstration: DemonstrationTell;
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

/**
 * Every (model, task) row the benchmark is entitled to average.
 *
 * ⚠ TEST STUBS ARE EXCLUDED, AS THEY ARE EVERYWHERE ELSE. `isRanked` keeps a
 * deterministic mock off the leaderboard's podium for the reason `best_model_key`
 * gives — "so the winner is never a fixture" — and a mock folded into a course's
 * headline number is the same lie with fewer places to notice it. They are still
 * reachable: level 4 lists every model that has a row, stub or not.
 */
function benchmarkEntries(models: ModelRollup[]): ModelTaskEntry[] {
  return models.filter((m) => m.recommendable).flatMap((m) => m.entries);
}

function outcomeIndex(board: LeaderboardResponse): Map<string, OutcomeView> {
  return new Map(board.curriculum.outcomes.map((o) => [o.id, o]));
}

/** How many tasks the catalogue files under each outcome, measured or not. */
function tasksPerOutcome(board: LeaderboardResponse): Map<string, number> {
  const counts = new Map<string, number>();
  for (const task of board.tasks) {
    if (task.slo === null) continue;
    counts.set(task.slo, (counts.get(task.slo) ?? 0) + 1);
  }
  return counts;
}

function sampleWord(n: number): string {
  return n === 1 ? "sample" : "samples";
}

/**
 * The caption under a score, or in place of one.
 *
 * ⚠ A TILE WITH NO NUMBER STILL SAYS SOMETHING. A blank tile in a grid reads as
 * zero to almost everybody, and this whole flow exists to be read at a glance by
 * someone who will not hover anything.
 */
function measuredReason(agg: ScoreAggregate, unit: string): string {
  return (
    `${agg.scored_samples} scored ${sampleWord(agg.scored_samples)} ` +
    `across ${agg.measured_tasks} ${agg.measured_tasks === 1 ? "task" : "tasks"}${unit}`
  );
}

// ---------------------------------------------------------------------------
// Level 3 — the outcomes one course teaches
// ---------------------------------------------------------------------------

function buildOutcomeTile(
  slo: string,
  level: string,
  outcome: OutcomeView | undefined,
  entries: ModelTaskEntry[],
  tasksAvailable: number,
): OutcomeTile {
  const mine = entries.filter((entry) => entry.slo === slo);
  const agg = aggregate(mine);
  const modelsMeasured = new Set(
    mine
      .filter((e) => e.result.mean_score !== null && e.result.scored_count > 0)
      .map((e) => e.result.model_key),
  ).size;

  const base = {
    slo,
    title: outcome?.title ?? slo,
    statement: outcome?.statement ?? "",
    note: outcome?.benchmark_note ?? "",
    level,
    level_label: levelLabel(level),
    assessment_point: isAssessmentPoint(level),
    // Absent from the curriculum means we have an outcome id and no statement.
    // Assume it IS reachable rather than silently declaring it out of scope:
    // "we cannot measure this" is a claim the curriculum makes, not a default.
    benchmarkable: outcome ? outcome.text_benchmarkable : true,
    aggregate: agg,
    tasks_available: tasksAvailable,
    models_measured: modelsMeasured,
  };

  // Checked FIRST, and before any score: an outcome the curriculum says a text
  // benchmark cannot reach is a boundary we published, never a gap in coverage
  // and never a model's failure.
  if (!base.benchmarkable) {
    return {
      ...base,
      status: "not_benchmarkable",
      // ⚠ A CAPTION, NOT THE WHOLE ARGUMENT. The curriculum's note runs to
      // sixty words and, rendered on a tile, it buried the five other outcomes
      // in the grid beside it -- which is the "too much information" this flow
      // is a response to. The note is still carried, on `note`, and level 4
      // prints it in full under "How this outcome is scored", where a reader
      // who wants the reasoning has asked for it.
      reason: "A single-turn text benchmark cannot measure this outcome, so nothing was run.",
    };
  }

  if (agg.score === null) {
    return {
      ...base,
      status: "not_measured",
      reason:
        tasksAvailable === 0
          ? "No task in the catalogue measures this outcome yet."
          : `${tasksAvailable} ${tasksAvailable === 1 ? "task measures" : "tasks measure"} ` +
            "this outcome; none has a finished, scored run.",
    };
  }

  return {
    ...base,
    status: "measured",
    reason: measuredReason(
      agg,
      `, ${modelsMeasured} ${modelsMeasured === 1 ? "model" : "models"}`,
    ),
  };
}

// ---------------------------------------------------------------------------
// Level 2 — the courses of one programme
// ---------------------------------------------------------------------------

function buildCourseTile(
  row: CourseCoverageView,
  outcomes: Map<string, OutcomeView>,
  order: string[],
  entries: ModelTaskEntry[],
  taskCounts: Map<string, number>,
): CourseTile {
  // Curriculum order, not the YAML mapping's insertion order: SLO10 must not
  // sort before SLO2, and a course page that ordered outcomes differently from
  // every other surface would look like a different list.
  const taught = order.filter((id) => id in row.outcomes);
  const tiles = taught.map((slo) =>
    buildOutcomeTile(
      slo,
      row.outcomes[slo]!,
      outcomes.get(slo),
      entries,
      taskCounts.get(slo) ?? 0,
    ),
  );

  const benchmarkable = tiles.filter((t) => t.benchmarkable);
  const measured = tiles.filter((t) => t.status === "measured");
  // The course's own read: every entry filed under any outcome it teaches.
  // Sample-weighted through the shared `aggregate`, so a three-sample outcome
  // cannot outvote a sixty-sample one on the course's headline number.
  const taughtSet = new Set(taught);
  const agg = aggregate(entries.filter((e) => e.slo !== null && taughtSet.has(e.slo)));

  const shared = {
    slug: slugify(row.course),
    code: row.course,
    title: row.title,
    outcomes: tiles,
    benchmarkable_count: benchmarkable.length,
    measured_count: measured.length,
    assessment_count: tiles.filter((t) => t.assessment_point).length,
    aggregate: agg,
  };

  if (benchmarkable.length === 0) {
    return {
      ...shared,
      status: "not_benchmarkable",
      reason:
        "Every outcome this course teaches is one a text benchmark cannot " +
        "measure, so nothing was run for it.",
    };
  }
  if (agg.score === null) {
    return {
      ...shared,
      status: "not_measured",
      reason: `${benchmarkable.length} of its ${tiles.length} outcomes can be measured this way; none has been.`,
    };
  }
  return {
    ...shared,
    status: "measured",
    reason: `${measured.length} of ${benchmarkable.length} measurable outcomes have a score.`,
  };
}

/**
 * Every course of one programme, in the published map's order.
 *
 * Map order, not score order. The coverage grid is a curriculum read top to
 * bottom — GBA 146 before GBA 490 — and re-sorting it by how the models happen
 * to do turns a programme into a ranking of its own courses, which is a claim
 * about the department that this benchmark has no business making.
 */
export function buildCourses(board: LeaderboardResponse): CourseTile[] {
  const outcomes = outcomeIndex(board);
  const order = board.curriculum.available
    ? board.curriculum.outcomes.map((o) => o.id)
    : board.slos;
  const entries = benchmarkEntries(rollupByModel(board));
  const taskCounts = tasksPerOutcome(board);
  return board.curriculum.coverage.map((row) =>
    buildCourseTile(row, outcomes, order, entries, taskCounts),
  );
}

export function findCourse(
  courses: CourseTile[],
  slug: string,
): CourseTile | undefined {
  return courses.find((course) => course.slug === slug);
}

export function findOutcome(
  course: CourseTile,
  slo: string,
): OutcomeTile | undefined {
  // Case-insensitive: `SLO2` in the curriculum, `slo2` in a hand-typed URL.
  const wanted = slo.toUpperCase();
  return course.outcomes.find((tile) => tile.slo.toUpperCase() === wanted);
}

// ---------------------------------------------------------------------------
// Level 1 — the programmes
// ---------------------------------------------------------------------------

/**
 * The programmes on this platform, each with one overall read.
 *
 * ⚠ ONE PROGRAMME TODAY, AND THE LIST SHAPE IS NOT PREMATURE. The curriculum
 * map holds a single `program` string, so this returns one tile — but the level
 * exists in the flow the client asked for, a second programme is a second
 * `slo.yaml`, and a grid that has to be rewritten from a scalar into a list the
 * day that lands is a grid nobody will rewrite. It is also the only level that
 * can state the programme's coverage honestly: 7 of 9 outcomes measurable, and
 * how many of those have a number.
 */
export function buildIndex(board: LeaderboardResponse): ExploreIndex {
  const models = rollupByModel(board);
  const ranked = models.filter((m) => m.recommendable && m.overall.score !== null);
  const demonstration = summariseDemonstration(ranked);

  if (!board.curriculum.available || board.curriculum.coverage.length === 0) {
    return {
      available: false,
      unavailable_reason:
        board.curriculum.unavailable_reason ??
        "This deployment has no curriculum map, so it has no programme or course " +
          "to drill into. Results still group by outcome id on the leaderboard.",
      majors: [],
      demonstration,
    };
  }

  const courses = buildCourses(board);
  const entries = benchmarkEntries(models);
  const agg = aggregate(entries.filter((e) => e.slo !== null));

  const outcomes = board.curriculum.outcomes;
  const benchmarkable = outcomes.filter((o) => o.text_benchmarkable);
  const measuredOutcomes = new Set(
    courses.flatMap((c) => c.outcomes.filter((o) => o.status === "measured").map((o) => o.slo)),
  );
  const modelsMeasured = new Set(
    entries
      .filter((e) => e.slo !== null && e.result.mean_score !== null && e.result.scored_count > 0)
      .map((e) => e.result.model_key),
  ).size;

  const name = board.curriculum.program ?? "This programme";
  const shared = {
    slug: slugify(name),
    name,
    source: board.curriculum.source,
    course_count: courses.length,
    outcome_count: outcomes.length,
    benchmarkable_count: benchmarkable.length,
    measured_count: measuredOutcomes.size,
    models_measured: modelsMeasured,
    aggregate: agg,
  };

  const major: MajorTile =
    agg.score === null
      ? {
          ...shared,
          status: "not_measured",
          reason: `${benchmarkable.length} of ${outcomes.length} outcomes can be measured by a text benchmark; none has a score yet.`,
        }
      : {
          ...shared,
          status: "measured",
          reason: measuredReason(
            agg,
            `, ${modelsMeasured} ${modelsMeasured === 1 ? "model" : "models"}`,
          ),
        };

  return {
    available: true,
    unavailable_reason: null,
    majors: [major],
    demonstration,
  };
}

export function findMajor(index: ExploreIndex, slug: string): MajorTile | undefined {
  return index.majors.find((major) => major.slug === slug);
}

// ---------------------------------------------------------------------------
// Level 4 — the evidence behind one (course, outcome) pair
// ---------------------------------------------------------------------------

/** One model's read on one outcome, with the receipt to check it. */
export interface EvidenceRow {
  model_key: string;
  display_name: string;
  data_residency_label: string;
  /** False for test stubs. Shown here — they are real rows — but never ranked. */
  recommendable: boolean;
  /** Every row behind this model's score was seeded, not measured. */
  seeded: boolean;
  aggregate: ScoreAggregate;
  entries: ModelTaskEntry[];
}

export interface EvidenceView {
  course: CourseTile;
  outcome: OutcomeTile;
  /** Models with a real score here, strongest first. */
  ranked: EvidenceRow[];
  /** Models with a row but no score, plus test stubs. Shown, never ranked. */
  unranked: EvidenceRow[];
  /** The tasks the catalogue files under this outcome — the "on what". */
  tasks: TaskLeaderboard[];
  demonstration: DemonstrationTell;
}

/**
 * Everything the "why" level shows for one (course, outcome) pair.
 *
 * ⚠ THE UNRANKED HALF IS NOT PADDING. A reader who drills this far is checking
 * a number, and "three models scored, two more were run and produced nothing" is
 * part of what the number means. Listing only the models that scored would make
 * a partially-failed sweep look like a clean one.
 */
export function buildEvidence(
  board: LeaderboardResponse,
  course: CourseTile,
  outcome: OutcomeTile,
): EvidenceView {
  const rows: EvidenceRow[] = rollupByModel(board)
    .map((model) => {
      const entries = model.entries.filter((entry) => entry.slo === outcome.slo);
      return {
        model_key: model.model_key,
        display_name: model.display_name,
        data_residency_label: model.data_residency_label,
        recommendable: model.recommendable,
        seeded: isSeeded(model),
        aggregate: aggregate(entries),
        entries,
      };
    })
    .filter((row) => row.entries.length > 0);

  const ranked = rows
    .filter((row) => row.recommendable && row.aggregate.score !== null)
    .sort((a, b) => (b.aggregate.score ?? 0) - (a.aggregate.score ?? 0));

  return {
    course,
    outcome,
    ranked,
    unranked: rows.filter((row) => !ranked.includes(row)),
    tasks: board.tasks.filter((task) => task.slo === outcome.slo),
    demonstration: summariseDemonstration(
      rollupByModel(board).filter(
        (m) =>
          m.recommendable &&
          m.entries.some(
            (e) =>
              e.slo === outcome.slo &&
              e.result.mean_score !== null &&
              e.result.scored_count > 0,
          ),
      ),
    ),
  };
}
