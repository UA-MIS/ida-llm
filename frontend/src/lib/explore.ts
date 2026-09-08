/**
 * The guided drill-down: major → class → outcome → evidence.
 *
 * ⚠ WHY THE TOP LEVEL IS MAJORS AND NOT A PROGRAMME. This flow used to open on
 * one row: "BScBA General Business (core)", the single `program` string in
 * `curriculum/slo.yaml`. That is what the curriculum map describes, so that is
 * what got rendered — and it is the wrong first screen. Nobody is a professor
 * OF THE CORE. They teach Management Information Systems, and the flow has to
 * start where the reader already stands, in their own major, or the first thing
 * it asks them to do is locate themselves inside somebody else's list.
 *
 * So the top level reads `curriculum/majors.yaml` — the college's eleven
 * undergraduate majors, from the course catalog — and the level below it is
 * that major's classes. Two files, two publishers, one join key:
 *
 *   majors.yaml   which classes exist and whose they are      (course catalog)
 *   slo.yaml      which outcomes a class teaches, at what level (curriculum map)
 *
 * ⚠ WHAT MAKES A CLASS "MEASURED", AND WHY IT IS NOT THE OUTCOMES IT TEACHES.
 * Results are filed by OUTCOME — a task carries `slo:SLO2`, never
 * `course:MIS 200`. So a class scored from "the outcomes it teaches" gets a
 * number that is IDENTICAL for every other class the map marks against those
 * outcomes. Run the three MIS 200 exam families and AC 210, ST 260, GBA 300,
 * OM 300 and FI 302 would each display a score from a course none of them is —
 * a dozen fabricated measurements, each individually plausible, produced by
 * arithmetic rather than by anybody lying. A class therefore counts only the
 * entries whose task FAMILY it claims (`MajorClassView.task_families`), and a
 * class that claims none can never show a number. Today exactly one class in
 * the college claims any: MIS 200.
 *
 * One level per question:
 *
 *   1. major      which majors this college has, and how each reads
 *   2. class      which classes this major has, and how each reads
 *   3. outcome    which outcomes this class teaches, and how each reads — the
 *                 "why" behind the class's number
 *   4. evidence   for one (class, outcome) pair: which model, on what, from
 *                 which run — the receipts
 *
 * ⚠ THIS FILE INVENTS NO NUMBER. Every score comes from `aggregate()` in
 * lib/rollup.ts — the sample-weighted mean, with the weakest-constituent
 * confidence rule and the null-is-not-zero rule already in it. What this module
 * adds is grouping and honest empty states, not arithmetic.
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
 * this repository"; a class that showed MIS 200 or GBA 300 as simply *empty* on
 * teamwork would be making that claim with whitespace.
 *
 * ⚠ AND THERE IS NO FOURTH STATE FOR "THE MAP DOES NOT MARK THIS CLASS", which
 * is now a common case: the catalog lists fourteen MIS classes and the core
 * curriculum map marks exactly one of them. That class is `not_measured` — the
 * honest status — and its REASON says why it is empty. Adding a fourth status
 * would have meant a fourth glyph in `classifyCell`, which `/compare` shares,
 * so a change about the majors taxonomy would have altered a page that has
 * nothing to do with it.
 */

import {
  aggregate,
  summariseDemonstration,
  entriesAreSeeded,
  isSeeded,
  rollupByModel,
  type DemonstrationTell,
  type ModelRollup,
  type ModelTaskEntry,
  type ScoreAggregate,
} from "./rollup";
import type {
  LeaderboardResponse,
  MajorClassView,
  MajorView,
  OutcomeView,
  TaskLeaderboard,
} from "./types";

// ---------------------------------------------------------------------------
// Slugs
// ---------------------------------------------------------------------------

/**
 * A URL segment for a name the curriculum owns.
 *
 * ⚠ USED FOR CLASSES, NOT FOR MAJORS, AND THAT ASYMMETRY IS THE POINT. A major
 * carries an authored `id` in `majors.yaml` precisely so that renaming it in
 * the catalog does not silently break every link to it. A class has no id — the
 * course code IS its identity in both files — so its segment is derived, and
 * every lookup goes back through this same function rather than comparing a
 * slug to a slug stored somewhere else.
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
 * claims (this class masters the outcome, AND the programme measures it here).
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

/** The wording for an unmeasured pair. One string, so every surface agrees. */
export const NOT_MEASURED = "Not measured yet";

/** The wording for an outcome a text benchmark cannot reach at all. */
export const NOT_TEXT_MEASURABLE = "Not text-measurable";

/**
 * Why a class has nothing filed against it. One string, four surfaces.
 *
 * The commonest state in the product and the one most likely to be misread: the
 * catalog lists fourteen MIS classes, the exam ingest produced tasks for one of
 * them, so thirteen of fourteen say this. It is a statement about what has been
 * authored, never about the class or the models.
 */
export const NO_TASKS_FOR_CLASS =
  "No task in the catalogue is about this class yet, so nothing has been run for it.";

/** One outcome as one class teaches it. Level 3's row, and level 4's subject. */
export interface OutcomeTile {
  slo: string;
  title: string;
  statement: string;
  /** The curriculum's own words on how (or whether) this outcome is scored. */
  note: string;
  /** The published level for THIS class. */
  level: string;
  level_label: string;
  assessment_point: boolean;
  benchmarkable: boolean;
  status: ExploreStatus;
  aggregate: ScoreAggregate;
  /** Tasks ABOUT THIS CLASS that the catalogue files under this outcome. */
  tasks_available: number;
  /** How many models have a real score here. Coverage, stated not implied. */
  models_measured: number;
  /**
   * True when every entry that fed this tile's score was seeded, not measured.
   *
   * Per outcome, so it self-clears the moment a real measurement replaces the
   * seeded one for THIS pairing — see `entriesAreSeeded`.
   */
  seeded: boolean;
  /** Always populated, always specific — the tile's own caption. */
  reason: string;
}

/** One class of a major. Level 2's column, and level 3's subject. */
export interface ClassTile {
  slug: string;
  code: string;
  title: string;
  credit_hours: number | null;
  /**
   * Task families whose results are about this class's own material.
   *
   * The filter every number on this tile is built through. Empty means no
   * result can be attributed to this class — see the module docstring.
   */
  task_families: string[];
  /** Every outcome the map marks for this class, in curriculum order. */
  outcomes: OutcomeTile[];
  /** True when the published coverage grid has a row for this class at all. */
  in_curriculum_map: boolean;
  /** Outcomes this class teaches that a text benchmark can reach. */
  benchmarkable_count: number;
  /** Of those, how many have a score. */
  measured_count: number;
  /** Outcomes this class is an assessment point for — what the department grades. */
  assessment_count: number;
  status: ExploreStatus;
  aggregate: ScoreAggregate;
  reason: string;
  /**
   * Whether the models measured on this class are seeded, real, or a mix — same
   * rule and same words as every other level, scoped to the models that
   * actually contributed to THIS class rather than the whole board. See
   * `summariseDemonstration`.
   */
  demonstration: DemonstrationTell;
}

/** One major. Level 1's column, and level 2's subject. */
export interface MajorTile {
  /** The authored id from `majors.yaml`. The URL segment, and the React key. */
  slug: string;
  name: string;
  /**
   * The department's own short code — `"MIS"`, `"AC"`, `"GBA"` — for a column
   * that has no room for the full name. See `codeForMajor`.
   */
  code: string;
  department: string;
  catalog: string | null;
  /** `catalog` / `core-only` / `none` — how far the class list got. */
  class_source: string;
  class_source_label: string;
  class_count: number;
  /** Classes with at least one task family claimed — the ones that CAN score. */
  measurable_class_count: number;
  /** Of those, how many have a score. */
  measured_class_count: number;
  /** Distinct outcomes the map marks across this major's classes. */
  outcome_count: number;
  benchmarkable_count: number;
  measured_count: number;
  models_measured: number;
  status: ExploreStatus;
  aggregate: ScoreAggregate;
  reason: string;
}

/** What level 1 needs to render, plus the honest reason it might be empty. */
export interface ExploreIndex {
  available: boolean;
  unavailable_reason: string | null;
  majors: MajorTile[];
  /** Core courses no major owns. Shown as a footnote, never as a major. */
  unassigned: { course: string; reason: string }[];
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
 * gives — "so the winner is never a fixture" — and a mock folded into a class's
 * headline number is the same lie with fewer places to notice it. They are still
 * reachable: level 4 lists every model that has a row, stub or not.
 */
function benchmarkEntries(models: ModelRollup[]): ModelTaskEntry[] {
  return models.filter((m) => m.recommendable).flatMap((m) => m.entries);
}

function outcomeIndex(board: LeaderboardResponse): Map<string, OutcomeView> {
  return new Map(board.curriculum.outcomes.map((o) => [o.id, o]));
}

/**
 * Does this entry belong to this class?
 *
 * ⚠ THE ONE PREDICATE THE HONESTY OF THIS WHOLE SCREEN RESTS ON. See the module
 * docstring: without it, one exam's score appears under every class that
 * teaches the same outcome.
 */
export function entryIsAboutClass(entry: ModelTaskEntry, families: Set<string>): boolean {
  return families.has(entry.family);
}

/** Tasks ABOUT one class, per outcome. The denominator of "nothing ran". */
function classTasksPerOutcome(
  board: LeaderboardResponse,
  families: Set<string>,
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const task of board.tasks) {
    if (task.slo === null || !families.has(task.family)) continue;
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
// Level 3 — the outcomes one class teaches
// ---------------------------------------------------------------------------

function buildOutcomeTile(
  slo: string,
  level: string,
  outcome: OutcomeView | undefined,
  classEntries: ModelTaskEntry[],
  tasksAvailable: number,
  hasFamilies: boolean,
): OutcomeTile {
  const mine = classEntries.filter((entry) => entry.slo === slo);
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
    seeded: entriesAreSeeded(mine),
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
      reason: !hasFamilies
        ? NO_TASKS_FOR_CLASS
        : tasksAvailable === 0
          ? "No task about this class measures this outcome yet."
          : `${tasksAvailable} ${tasksAvailable === 1 ? "task about this class measures" : "tasks about this class measure"} ` +
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
// Level 2 — the classes of one major
// ---------------------------------------------------------------------------

function buildClassTile(
  entry: MajorClassView,
  board: LeaderboardResponse,
  outcomes: Map<string, OutcomeView>,
  order: string[],
  allEntries: ModelTaskEntry[],
  models: ModelRollup[],
): ClassTile {
  const coverage = board.curriculum.coverage.find((row) => row.course === entry.course);
  const families = new Set(entry.task_families);
  const hasFamilies = families.size > 0;

  // ⚠ FILTERED BEFORE ANYTHING IS COUNTED, not after. Every number on this tile
  // and every number in the grid beside it is built from this one list, so
  // there is no path by which a class's headline can include a result its rows
  // do not — see the module docstring for what that path used to produce.
  const classEntries = allEntries.filter((e) => entryIsAboutClass(e, families));
  const taskCounts = classTasksPerOutcome(board, families);

  // Curriculum order, not the map's insertion order: SLO10 must not sort before
  // SLO2, and a class page that ordered outcomes differently from every other
  // surface would look like a different list.
  const marked = coverage ? order.filter((id) => id in coverage.outcomes) : [];
  const tiles = marked.map((slo) =>
    buildOutcomeTile(
      slo,
      coverage!.outcomes[slo]!,
      outcomes.get(slo),
      classEntries,
      taskCounts.get(slo) ?? 0,
      hasFamilies,
    ),
  );

  const benchmarkable = tiles.filter((t) => t.benchmarkable);
  const measured = tiles.filter((t) => t.status === "measured");
  const markedSet = new Set(marked);

  // ⚠ THE SAME ENTRIES ITS ROWS ARE BUILT FROM, so the headline and the rows
  // cannot disagree — the rule this whole module is organised around.
  const counted = classEntries.filter((e) => e.slo !== null && markedSet.has(e.slo));
  const agg = aggregate(counted);

  // A result about this class filed under an outcome the map does not mark for
  // it. Rare, and reported rather than dropped in silence: it means either the
  // map or a task tag is wrong, and a number that vanishes from a page without
  // saying so is the failure mode this codebase keeps writing tests against.
  const unmarked = classEntries.filter(
    (e) => e.slo !== null && !markedSet.has(e.slo) && e.result.scored_count > 0,
  ).length;
  const stray =
    unmarked > 0
      ? ` ${unmarked} scored ${unmarked === 1 ? "result is" : "results are"} filed under ` +
        "an outcome the map does not mark for this class, so they are not counted here."
      : "";

  // Models with a real, rankable contribution to THIS class — not the whole
  // board's demonstration split: a class whose own results are all measured
  // must not be told "some figures here are illustrative" because a different
  // class somewhere else is still seeded.
  const contributing = models.filter(
    (m) =>
      m.recommendable &&
      m.entries.some(
        (e) =>
          entryIsAboutClass(e, families) &&
          e.slo !== null &&
          markedSet.has(e.slo) &&
          e.result.mean_score !== null &&
          e.result.scored_count > 0,
      ),
  );

  const shared = {
    slug: slugify(entry.course),
    code: entry.course,
    title: entry.title,
    credit_hours: entry.credit_hours,
    task_families: [...entry.task_families],
    outcomes: tiles,
    in_curriculum_map: coverage !== undefined,
    benchmarkable_count: benchmarkable.length,
    measured_count: measured.length,
    assessment_count: tiles.filter((t) => t.assessment_point).length,
    aggregate: agg,
    demonstration: summariseDemonstration(contributing),
  };

  if (tiles.length === 0) {
    // The commonest case in the product: the catalog lists fourteen MIS classes
    // and the core curriculum map marks exactly one of them. Not an error, and
    // emphatically not a class that failed — the map simply does not go there.
    return {
      ...shared,
      status: "not_measured",
      reason:
        "The published curriculum map does not mark this class against any outcome, " +
        "so there is nothing yet to measure it on." + stray,
    };
  }
  if (benchmarkable.length === 0) {
    return {
      ...shared,
      status: "not_benchmarkable",
      reason:
        "Every outcome this class teaches is one a text benchmark cannot " +
        "measure, so nothing was run for it." + stray,
    };
  }
  if (agg.score === null) {
    return {
      ...shared,
      status: "not_measured",
      reason:
        (hasFamilies
          ? `${benchmarkable.length} of its ${tiles.length} outcomes can be measured this way; none has been.`
          : NO_TASKS_FOR_CLASS) + stray,
    };
  }
  return {
    ...shared,
    status: "measured",
    reason:
      `${measured.length} of ${benchmarkable.length} measurable outcomes have a score.` + stray,
  };
}

/**
 * Every class of one major, in the catalog's order.
 *
 * Catalog order, not score order. The class list is a catalog read top to
 * bottom — MIS 200 before MIS 466 — and re-sorting it by how the models happen
 * to do turns a major into a ranking of its own classes, which is a claim about
 * the department that this benchmark has no business making. It is also why the
 * FLIPPED grid puts classes on the horizontal axis: model order is a rank and is
 * meant to be read as one; class order is not, and a vertical list of classes
 * would imply the top one matters most.
 */
export function buildClasses(board: LeaderboardResponse, major: MajorTile): ClassTile[] {
  const view = board.curriculum.majors.find((m) => m.id === major.slug);
  if (!view) return [];
  return buildClassesFor(board, view);
}

function buildClassesFor(board: LeaderboardResponse, view: MajorView): ClassTile[] {
  const outcomes = outcomeIndex(board);
  const order = board.curriculum.available
    ? board.curriculum.outcomes.map((o) => o.id)
    : board.slos;
  const models = rollupByModel(board);
  const entries = benchmarkEntries(models);
  return view.classes.map((entry) =>
    buildClassTile(entry, board, outcomes, order, entries, models),
  );
}

export function findClass(classes: ClassTile[], slug: string): ClassTile | undefined {
  return classes.find((row) => row.slug === slug);
}

export function findOutcome(tile: ClassTile, slo: string): OutcomeTile | undefined {
  // Case-insensitive: `SLO2` in the curriculum, `slo2` in a hand-typed URL.
  const wanted = slo.toUpperCase();
  return tile.outcomes.find((row) => row.slo.toUpperCase() === wanted);
}

// ---------------------------------------------------------------------------
// Level 1 — the majors
// ---------------------------------------------------------------------------

/**
 * The short label a column-width space actually has room for.
 *
 * ⚠ THE CATALOG'S OWN CODE, NEVER A DERIVED ONE. `major.subject_codes` is
 * `curriculum/majors.yaml`'s own `subject_codes` field — the prefixes the
 * registrar prints on the course, e.g. `["MIS"]`. Joining rather than picking
 * one covers a major with more than one prefix without deciding which wins.
 * Falling back to the full `name` for an empty list (Business Cyber Security,
 * Real Estate — neither has a catalogued prefix of its own) is a real
 * admission that no code exists, not a bug: inventing one would be exactly
 * the kind of transcription this file's provenance rule forbids.
 */
export function codeForMajor(view: MajorView): string {
  return view.subject_codes.length > 0 ? view.subject_codes.join("/") : view.name;
}

function buildMajorTile(
  view: MajorView,
  board: LeaderboardResponse,
  entries: ModelTaskEntry[],
): MajorTile {
  const classes = buildClassesFor(board, view);

  // Every family any of this major's classes claims, and every outcome the map
  // marks across them. The major's headline is the union of its classes' own
  // numbers — same entries, so the two levels cannot disagree.
  const families = new Set(classes.flatMap((c) => c.task_families));
  const marked = new Set(classes.flatMap((c) => c.outcomes.map((o) => o.slo)));
  const counted = entries.filter(
    (e) => entryIsAboutClass(e, families) && e.slo !== null && marked.has(e.slo),
  );
  const agg = aggregate(counted);

  const benchmarkableOutcomes = new Set(
    classes.flatMap((c) => c.outcomes.filter((o) => o.benchmarkable).map((o) => o.slo)),
  );
  const measuredOutcomes = new Set(
    classes.flatMap((c) => c.outcomes.filter((o) => o.status === "measured").map((o) => o.slo)),
  );
  const modelsMeasured = new Set(
    counted
      .filter((e) => e.result.mean_score !== null && e.result.scored_count > 0)
      .map((e) => e.result.model_key),
  ).size;

  const measurable = classes.filter((c) => c.task_families.length > 0);

  const shared = {
    slug: view.id,
    name: view.name,
    code: codeForMajor(view),
    department: view.department,
    catalog: view.catalog,
    class_source: view.class_source,
    class_source_label: view.class_source_label,
    class_count: classes.length,
    measurable_class_count: measurable.length,
    measured_class_count: classes.filter((c) => c.status === "measured").length,
    outcome_count: marked.size,
    benchmarkable_count: benchmarkableOutcomes.size,
    measured_count: measuredOutcomes.size,
    models_measured: modelsMeasured,
    aggregate: agg,
  };

  if (classes.length === 0) {
    return {
      ...shared,
      status: "not_measured",
      // The catalog list for this major has not been transcribed. Said plainly:
      // a major showing no classes must not read as a major with no classes.
      reason: `${view.class_source_label}, so there is nothing here to measure yet.`,
    };
  }
  if (measurable.length === 0) {
    return {
      ...shared,
      status: "not_measured",
      reason:
        `${classes.length} ${classes.length === 1 ? "class" : "classes"}; no task in the ` +
        "catalogue is about any of them yet, so none has been run.",
    };
  }
  if (agg.score === null) {
    return {
      ...shared,
      status: "not_measured",
      reason:
        `${measurable.length} of its ${classes.length} classes ${measurable.length === 1 ? "has" : "have"} ` +
        "tasks written about it; none has a finished, scored run.",
    };
  }
  return {
    ...shared,
    status: "measured",
    reason: measuredReason(
      agg,
      `, ${modelsMeasured} ${modelsMeasured === 1 ? "model" : "models"}`,
    ),
  };
}

/**
 * The majors this college offers, each with one overall read.
 *
 * ⚠ ELEVEN COLUMNS, ONE OF WHICH HAS A PATH THROUGH IT, AND THAT IS THE POINT.
 * MIS is the only major with a benchmarked class today. The other ten are not
 * padding and they are not placeholders: they are the real catalog, showing
 * honestly that nothing has been measured there — which is what makes the one
 * that IS measured mean something, and what makes "a second major just fills
 * in" a data change rather than a rebuild.
 */
export function buildIndex(board: LeaderboardResponse): ExploreIndex {
  const models = rollupByModel(board);
  const ranked = models.filter((m) => m.recommendable && m.overall.score !== null);
  const demonstration = summariseDemonstration(ranked);

  const views = board.curriculum.majors;
  if (views.length === 0) {
    return {
      available: false,
      unavailable_reason:
        "This deployment has no majors taxonomy (curriculum/majors.yaml), so it has no " +
        "major or class to drill into. Results still group by outcome id on the leaderboard.",
      majors: [],
      unassigned: [],
      demonstration,
    };
  }

  const entries = benchmarkEntries(models);
  return {
    available: true,
    unavailable_reason: null,
    majors: views.map((view) => buildMajorTile(view, board, entries)),
    unassigned: board.curriculum.unassigned_core.map((row) => ({
      course: row.course,
      reason: row.reason,
    })),
    demonstration,
  };
}

export function findMajor(index: ExploreIndex, slug: string): MajorTile | undefined {
  return index.majors.find((major) => major.slug === slug);
}

// ---------------------------------------------------------------------------
// Level 4 — the evidence behind one (class, outcome) pair
// ---------------------------------------------------------------------------

/** One model's read on one outcome of one class, with the receipt to check it. */
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
  klass: ClassTile;
  outcome: OutcomeTile;
  /** Models with a real score here, strongest first. */
  ranked: EvidenceRow[];
  /** Models with a row but no score, plus test stubs. Shown, never ranked. */
  unranked: EvidenceRow[];
  /** The tasks about THIS CLASS filed under this outcome — the "on what". */
  tasks: TaskLeaderboard[];
  demonstration: DemonstrationTell;
}

/**
 * Everything the "why" level shows for one (class, outcome) pair.
 *
 * ⚠ SCOPED TO THE CLASS'S OWN TASKS, like every level above it. An evidence
 * page that listed every SLO2 task would show a professor of MIS 200 a set of
 * receipts from courses they do not teach, under a heading that says MIS 200.
 *
 * ⚠ THE UNRANKED HALF IS NOT PADDING. A reader who drills this far is checking
 * a number, and "three models scored, two more were run and produced nothing" is
 * part of what the number means. Listing only the models that scored would make
 * a partially-failed sweep look like a clean one.
 */
export function buildEvidence(
  board: LeaderboardResponse,
  klass: ClassTile,
  outcome: OutcomeTile,
): EvidenceView {
  const families = new Set(klass.task_families);
  const mine = (entry: ModelTaskEntry) =>
    entry.slo === outcome.slo && entryIsAboutClass(entry, families);

  const models = rollupByModel(board);
  const rows: EvidenceRow[] = models
    .map((model) => {
      const entries = model.entries.filter(mine);
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
    klass,
    outcome,
    ranked,
    unranked: rows.filter((row) => !ranked.includes(row)),
    tasks: board.tasks.filter(
      (task) => task.slo === outcome.slo && families.has(task.family),
    ),
    demonstration: summariseDemonstration(
      models.filter(
        (m) =>
          m.recommendable &&
          m.entries.some(
            (e) => mine(e) && e.result.mean_score !== null && e.result.scored_count > 0,
          ),
      ),
    ),
  };
}
