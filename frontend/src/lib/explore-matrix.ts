/**
 * The drill-down, as a matrix: every model on this level against every entity.
 *
 * ⚠ MODELS ARE ROWS AND ENTITIES ARE COLUMNS, WHICH IS THE ORIENTATION
 * `/compare` USES — and the flip is a claim, not a layout preference. A vertical
 * list is read as a ranking whether or not you meant one, so the axis that runs
 * down the page has to be the axis where order MEANS something. Model order
 * does: these rows are sorted, and the best model is meant to read as best
 * because it is at the top. Entity order does not: majors are the catalog's
 * eleven and classes are a course listing, and standing them in a column would
 * quietly assert that Accounting outranks Marketing, or that MIS 200 matters
 * more than MIS 466. It does not, and this benchmark has no business saying so.
 *
 * The consequence worth stating: the grid is now WIDE and SHORT — a handful of
 * models against as many as fourteen classes — where it used to be tall and
 * narrow. That is why the per-entity prose moved off the header and under the
 * grid (see `components/explore-matrix.tsx`): a sentence does not fit in a
 * column header, and truncating it to a tooltip would break the rule this
 * codebase keeps writing tests about — an empty square must still say something,
 * on the page, at every width.
 *
 * The three grid levels are the same object at three scopes:
 *
 *   1. major      majors × models
 *   2. class      one major's classes × models
 *   3. outcome    one class's outcomes × models   (= `/compare`, scoped)
 *
 * Level 4 — the evidence behind one (class, outcome) pair — is unchanged. It
 * was never a grid and should not become one: it is where the receipts live.
 *
 * ⚠ THREE CLICK TARGETS, THREE DIFFERENT QUESTIONS, AND NONE OF THEM IS A DEAD
 * END. A dense grid where only one thing is clickable teaches the reader to
 * stop looking:
 *
 *   a column header   the entity. Drills into it — the level below, all models.
 *   a row header      the model. Opens its report card, across everything.
 *   a score cell      the (model, entity) crossing. Drills into the entity AND
 *                     carries the model, so the level below opens focused on
 *                     the model whose number you just clicked, rather than
 *                     dropping you back into the full field.
 *
 * ⚠ THIS FILE INVENTS NO NUMBER, AND ITS SUMMARY CELLS ARE NOT A SECOND
 * OPINION. Every cell is `aggregate()` from lib/rollup.ts over one model's
 * entries under one entity; the "All models" row is `aggregate()` over the same
 * entries across every ranked model, and a model's trailing cell is
 * `aggregate()` over that model's entries across every entity on the level. The
 * identical function the leaderboard and `/compare` use, with the
 * sample-weighted mean, the weakest-constituent confidence rule and the
 * null-is-not-zero rule already in it. A summary therefore cannot disagree with
 * the cells it summarises, because it is not computed by different code.
 *
 * ⚠ THE THREE EMPTIES STAY THREE DIFFERENT CLAIMS, and a dense grid is where
 * they are easiest to confuse. Classification runs through `classifyCell` in
 * lib/matrix.ts — one implementation, shared with `/compare` — so a class grid
 * physically cannot decide that "nothing ran" and "cannot be measured" are the
 * same square.
 */

import {
  aggregate,
  entriesAreSeeded,
  rollupByModel,
  summariseDemonstration,
  type DemonstrationTell,
  type ModelRollup,
  type ModelTaskEntry,
  type ScoreAggregate,
} from "./rollup";
import { classifyCell, type MatrixCell } from "./matrix";
import {
  buildClasses,
  buildIndex,
  entryIsAboutClass,
  type ClassTile,
  type ExploreStatus,
  type MajorTile,
  type OutcomeTile,
} from "./explore";
import type { LeaderboardResponse } from "./types";

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

/** One column: a thing you can open, and how it reads across every model. */
export interface MatrixEntityColumn {
  /** URL segment, and the column's React key. */
  key: string;
  /** The small line above the name — "Major", a course code, an outcome id. */
  eyebrow: string;
  heading: string;
  /** The level below. Every column header is a link; that is the drill. */
  href: string;
  /**
   * The column's own read across every ranked model — the "All models" row.
   *
   * Not a second computation: the same `aggregate()` over the same entries the
   * cells above it are built from, so the summary and the column cannot
   * disagree.
   */
  overall: ScoreAggregate;
  /**
   * That same summary as a cell, classified by the same function as every other
   * cell in the column.
   *
   * ⚠ THE POINT OF THE MATRIX REBUILD, IN ONE FIELD. A tile grid computed an
   * entity's headline in one place and its evidence in another, and nothing
   * structural stopped the two from drifting. Here the headline is the same
   * `classifyCell` verdict over the union of the entries its neighbours are
   * built from, rendered by the same `ScoreCell` — it cannot say "measured"
   * above a column of dashes, because it is not separate code.
   */
  overallCell: MatrixCell;
  status: ExploreStatus;
  /** Why there is (or is not) a number. On the page, never a tooltip only. */
  reason: string;
  /** Every score behind this column was seeded — the per-entity disclosure. */
  seeded: boolean;
  /** Whether a text benchmark can reach this entity at all. */
  benchmarkable: boolean;
  /** Extra context — a level badge, a coverage count, a credit line. */
  footnote: string;
}

/** One row: a model, as it reads across every entity on this level. */
export interface MatrixModelRow {
  model_key: string;
  display_name: string;
  /** False for test stubs. Shown — they are real rows — but never ranked. */
  recommendable: boolean;
  /** Every score this model contributed to this level was seeded, not measured. */
  seeded: boolean;
  /** The model's own report card. Every row header is a link. */
  href: string;
  /** One cell per column, in column order. */
  cells: MatrixCell[];
  /** This model across every entity on the level — the trailing column. */
  overall: ScoreAggregate;
  overallCell: MatrixCell;
  /** Entities where this model has a real score. Coverage, stated not implied. */
  measuredCount: number;
}

export interface ExploreMatrix {
  /** False when there is nothing to draw, with `unavailable_reason` saying why. */
  available: boolean;
  unavailable_reason: string | null;
  entities: MatrixEntityColumn[];
  /** Widest real coverage first, then strongest score. Order is a rank. */
  models: MatrixModelRow[];
  /** Seeded-vs-measured across the models that actually appear on this level. */
  demonstration: DemonstrationTell;
  /**
   * Entities a text benchmark can reach — the denominator for a coverage line.
   *
   * ⚠ ENTITIES, WHICH IS ONLY THE SAME AS OUTCOMES ON LEVEL 3. Levels 1 and 2
   * count majors and classes here, while their subtitles count OUTCOMES across
   * them — a different number, correctly, so those pages keep reading that off
   * the tiles in lib/explore.ts. Level 3's columns ARE its outcomes, so it
   * counts these instead and its prose is guaranteed to describe the grid.
   */
  benchmarkable_entities: number;
  /** Of those, how many have a score from at least one model. */
  measured_entities: number;
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

/**
 * What one column IS, stripped to what the matrix needs to build its cells.
 *
 * The three levels differ only in how they answer these questions, so each page
 * hands over a list of these and gets the same grid back.
 */
interface EntitySpec {
  key: string;
  eyebrow: string;
  heading: string;
  href: string;
  benchmarkable: boolean;
  /** The curriculum's own words on why it is or is not measurable. */
  note: string;
  /** How a not-measured cell should name this column: "MIS 200's outcomes". */
  noun: string;
  pronoun: { singular: string; plural: string };
  /**
   * The filter every cell in this column is built from.
   *
   * ⚠ TWO HALVES, AND BOTH ARE LOAD-BEARING. `slos` alone was the old filter,
   * and it is what made a class's score a claim about the OUTCOMES it teaches
   * rather than about the class — so one exam's number would surface under
   * every class the map marks against the same outcome. `families` narrows it
   * to results that are about this entity's own material. An empty `families`
   * means nothing can be attributed here, which is the honest default for the
   * thirteen of fourteen MIS classes nobody has authored tasks about.
   */
  slos: string[];
  families: string[];
  /** Tasks about THIS entity that the catalogue files under any of `slos`. */
  tasksAvailable: number;
  status: ExploreStatus;
  reason: string;
  footnote: string;
}

function entriesUnder(model: ModelRollup, spec: MatchSpec): ModelTaskEntry[] {
  return model.entries.filter(
    (entry) =>
      entry.slo !== null && spec.slos.has(entry.slo) && entryIsAboutClass(entry, spec.families),
  );
}

interface MatchSpec {
  slos: Set<string>;
  families: Set<string>;
}

function matchOf(spec: EntitySpec): MatchSpec {
  return { slos: new Set(spec.slos), families: new Set(spec.families) };
}

/** Tasks about a set of families, filed under a set of outcomes. */
function tasksFor(board: LeaderboardResponse, slos: string[], families: string[]): number {
  const wantSlo = new Set(slos);
  const wantFamily = new Set(families);
  return board.tasks.filter(
    (task) => task.slo !== null && wantSlo.has(task.slo) && wantFamily.has(task.family),
  ).length;
}

function cellFor(
  spec: EntitySpec,
  key: string,
  entries: ModelTaskEntry[],
  absence: string,
  tasksAvailable: number,
): MatrixCell {
  return classifyCell(
    {
      key,
      benchmarkable: spec.benchmarkable,
      note: spec.note,
      noun: spec.noun,
      pronoun: spec.pronoun,
      absence,
      tasksAvailable,
    },
    entries.length === 0 ? undefined : aggregate(entries),
  );
}

/**
 * The rows: every model on the board, ranked ones first, strongest first.
 *
 * ⚠ ORDER IS A CLAIM HERE IN A WAY IT WAS NOT WHEN MODELS WERE COLUMNS. A
 * column order is read as a list; a ROW order is read as a ranking, which is
 * exactly why the flip put models on this axis. So the sort has to be the one
 * the rest of the site already defends: widest real COVERAGE first, then the
 * strongest score — the same rule `buildMatrix` uses on `/compare`, and for the
 * same reason. A model measured on one class out of fourteen has not answered
 * "which model should I use", however well it did on that one.
 *
 * ⚠ AND IT IS SCOPED TO THIS LEVEL, not to the whole board. The reader is
 * looking at one major; "best" has to mean best HERE, or the top row is a
 * ranking of a different page.
 *
 * ⚠ TEST STUBS ARE SHOWN BUT NEVER RANKED FIRST, the same rule the leaderboard
 * and `/compare` apply. `best_model_key` excludes stubs "so the winner is never
 * a fixture", and a grid whose top row is a deterministic mock is the same lie
 * in a different shape. They keep their row — they are real rows — they just do
 * not lead.
 */
function buildModelRows(
  models: ModelRollup[],
  specs: EntitySpec[],
  levelMatch: MatchSpec,
  levelTasksAvailable: number,
): MatrixModelRow[] {
  const matches = specs.map(matchOf);

  const rows = models.map((model) => {
    const cells = specs.map((spec, index) =>
      cellFor(
        spec,
        `${spec.key}:${model.model_key}`,
        entriesUnder(model, matches[index]!),
        "this model has no",
        spec.tasksAvailable,
      ),
    );
    const mine = entriesUnder(model, levelMatch);
    const overall = aggregate(mine);
    return {
      model_key: model.model_key,
      display_name: model.display_name,
      recommendable: model.recommendable,
      // Scoped to THIS level, not the whole board: a model measured for real
      // here must not carry an "illustrative" badge because something it was
      // seeded for sits on a different page.
      seeded: entriesAreSeeded(mine),
      href: `/models/${encodeURIComponent(model.model_key)}`,
      cells,
      overall,
      overallCell: classifyCell(
        {
          key: `${model.model_key}:all`,
          // A model is never itself "out of scope"; only an entity can be.
          benchmarkable: true,
          note: "",
          noun: "this level",
          pronoun: { singular: "it", plural: "them" },
          absence: "this model has no",
          tasksAvailable: levelTasksAvailable,
        },
        mine.length === 0 ? undefined : overall,
      ),
      measuredCount: cells.filter((cell) => cell.status === "measured").length,
    };
  });

  return rows.sort((a, b) => {
    // Stubs last, whatever they scored — `best_model_key`'s rule, restated on
    // the axis that now reads as a ranking.
    const stub = Number(b.recommendable) - Number(a.recommendable);
    if (stub !== 0) return stub;
    const coverage = b.measuredCount - a.measuredCount;
    if (coverage !== 0) return coverage;
    return (b.overall.score ?? 0) - (a.overall.score ?? 0);
  });
}

function buildEntityColumn(
  spec: EntitySpec,
  models: ModelRollup[],
): MatrixEntityColumn {
  const match = matchOf(spec);
  // ⚠ RANKED MODELS ONLY. A stub has a row because it is a real row, but
  // folding it into the summary would put a fixture inside the number a
  // professor reads first.
  const ranked = models.filter((m) => m.recommendable);
  const contributing = ranked.flatMap((model) => entriesUnder(model, match));

  const overall = aggregate(contributing);
  const overallCell = cellFor(
    spec,
    `${spec.key}:all`,
    contributing,
    // ⚠ NOT A MODEL, SO NOT "THIS MODEL". This square is about all of them.
    "no model has a",
    // ⚠ PAIRINGS, NOT TASKS, AND THE FRACTION IS WHY. `aggregate()` counts a
    // measured (model, task) PAIR, so summing across every ranked model made
    // the numerator count pairings while the denominator still counted tasks —
    // a one-task class with two models rendered "2/1", a fraction above one, in
    // the cell a reader takes as the class's headline. The denominator has to
    // be the same unit the numerator is: every task, once per model that could
    // have run it.
    spec.tasksAvailable * ranked.length,
  );

  return {
    key: spec.key,
    eyebrow: spec.eyebrow,
    heading: spec.heading,
    href: spec.href,
    overall,
    overallCell,
    // ⚠ ONE SOURCE OF TRUTH FOR THE STATUS. Taken from the cell rather than
    // from the tile that supplied the caption, so the marker on a column and
    // the square beneath it are the same verdict by construction.
    status: overallCell.status,
    reason: spec.reason,
    seeded: entriesAreSeeded(contributing),
    benchmarkable: spec.benchmarkable,
    footnote: spec.footnote,
  };
}

function assemble(
  board: LeaderboardResponse,
  specs: EntitySpec[],
  unavailableReason: string | null,
): ExploreMatrix {
  const models = rollupByModel(board);
  // Everything anything on this level touches — the scope the rows' seeded
  // flags, their trailing summary and the page's demonstration notice are all
  // measured against.
  const levelMatch: MatchSpec = {
    slos: new Set(specs.flatMap((spec) => spec.slos)),
    families: new Set(specs.flatMap((spec) => spec.families)),
  };
  const levelTasks = specs.reduce((n, spec) => n + spec.tasksAvailable, 0);

  const entities = specs.map((spec) => buildEntityColumn(spec, models));
  const rows = buildModelRows(models, specs, levelMatch, levelTasks);

  // Models with a real, rankable contribution to THIS level — the same scoping
  // `buildEvidence` uses one level down. Not the whole board's split: a major
  // whose own classes are all measured must not be told "some figures here are
  // illustrative" because a different major somewhere else is still seeded.
  //
  // ⚠ AND THEIR ENTRIES ARE NARROWED TO THE LEVEL BEFORE THE SPLIT IS TAKEN,
  // which is the half that is easy to miss and was wrong once already.
  // `summariseDemonstration` asks `isSeeded` of each model, and `isSeeded`
  // reads the model's WHOLE entry set — so a model seeded on everything one
  // major covers, but measured for real on a different major, came back
  // "measured" and the page rendered a grid of entirely illustrative numbers
  // under no banner at all. That is gap #69 and #73 exactly, one scope down:
  // the flag was right per column and per row, and the sentence a reader meets
  // FIRST was silent. Filtering here makes the notice mean what it says.
  const contributing = models
    .filter((model) => model.recommendable)
    .map((model) => ({ ...model, entries: entriesUnder(model, levelMatch) }))
    .filter((model) =>
      model.entries.some(
        (entry) => entry.result.mean_score !== null && entry.result.scored_count > 0,
      ),
    );

  const benchmarkable = entities.filter((entity) => entity.benchmarkable);
  return {
    available: entities.length > 0,
    unavailable_reason: entities.length > 0 ? null : unavailableReason,
    entities,
    models: rows,
    demonstration: summariseDemonstration(contributing),
    benchmarkable_entities: benchmarkable.length,
    measured_entities: benchmarkable.filter((entity) => entity.status === "measured").length,
  };
}

// ---------------------------------------------------------------------------
// Level 1 — majors × models
// ---------------------------------------------------------------------------

function majorSpec(
  major: MajorTile,
  board: LeaderboardResponse,
  classes: ClassTile[],
): EntitySpec {
  const slos = [...new Set(classes.flatMap((c) => c.outcomes.map((o) => o.slo)))];
  const families = [...new Set(classes.flatMap((c) => c.task_families))];
  return {
    key: major.slug,
    eyebrow: "Major",
    heading: major.name,
    href: `/explore/${major.slug}`,
    // A major is not a single outcome, so it is never "out of scope" as a
    // whole: it is reachable if any outcome its classes publish is.
    benchmarkable: true,
    note: "",
    noun: `${major.name}'s classes`,
    pronoun: { singular: "it", plural: "them" },
    slos,
    families,
    tasksAvailable: tasksFor(board, slos, families),
    status: major.status,
    reason: major.reason,
    footnote:
      `${major.class_count} ${major.class_count === 1 ? "class" : "classes"}` +
      (major.measurable_class_count > 0
        ? ` · ${major.measurable_class_count} with tasks written about ${major.measurable_class_count === 1 ? "it" : "them"}`
        : " · none with tasks yet"),
  };
}

/**
 * Level 1: the majors this college offers, each a column against every model.
 *
 * ⚠ ELEVEN COLUMNS, ONE OF WHICH HAS A PATH THROUGH IT. MIS is the only major
 * with a benchmarked class today; the other ten show honestly that nothing has
 * been measured there. That is not scaffolding waiting to be replaced — it is
 * the shape of the claim. A grid that showed only the measured major would be
 * telling a professor of Marketing that this benchmark has nothing to say,
 * without ever admitting that the reason is us and not them.
 */
export function buildMajorMatrix(board: LeaderboardResponse): ExploreMatrix {
  const index = buildIndex(board);
  if (!index.available) {
    return {
      ...assemble(board, [], index.unavailable_reason),
      available: false,
      unavailable_reason: index.unavailable_reason,
    };
  }
  return assemble(
    board,
    index.majors.map((major) => majorSpec(major, board, buildClasses(board, major))),
    null,
  );
}

// ---------------------------------------------------------------------------
// Level 2 — classes × models
// ---------------------------------------------------------------------------

function classSpec(tile: ClassTile, board: LeaderboardResponse, majorSlug: string): EntitySpec {
  const slos = tile.outcomes.map((o) => o.slo);
  return {
    key: tile.slug,
    eyebrow: tile.code,
    heading: tile.title,
    href: `/explore/${majorSlug}/${tile.slug}`,
    // A class is out of scope only when EVERY outcome it teaches is — which is
    // a real case (`buildClassTile` has the same branch) and must read as the
    // published boundary it is, never as a class the models failed. A class the
    // map does not mark at all is NOT out of scope: it is unmeasured, and its
    // reason says which.
    benchmarkable: tile.outcomes.length === 0 || tile.benchmarkable_count > 0,
    note:
      tile.outcomes.length > 0 && tile.benchmarkable_count === 0
        ? "Every outcome this class teaches is one a text benchmark cannot reach."
        : "",
    noun: `${tile.code}'s outcomes`,
    pronoun: { singular: "it", plural: "them" },
    slos,
    families: tile.task_families,
    tasksAvailable: tasksFor(board, slos, tile.task_families),
    status: tile.status,
    reason: tile.reason,
    footnote: tile.in_curriculum_map
      ? `Teaches ${tile.outcomes.length} ${tile.outcomes.length === 1 ? "outcome" : "outcomes"}` +
        (tile.assessment_count > 0
          ? ` · ${tile.assessment_count} assessment ${tile.assessment_count === 1 ? "point" : "points"}`
          : "")
      : "Not in the published curriculum map",
  };
}

/** Level 2: the classes of one major, in the catalog's order. */
export function buildClassMatrix(
  board: LeaderboardResponse,
  major: MajorTile,
): ExploreMatrix {
  // Catalog order, not score order. Re-sorting a class list by how the models
  // happen to do turns a major into a ranking of its own classes, which is a
  // claim about the department this benchmark has no business making.
  const specs = buildClasses(board, major).map((tile) => classSpec(tile, board, major.slug));
  return assemble(
    board,
    specs,
    `${major.class_source_label}, so this major has no classes to drill into yet.`,
  );
}

// ---------------------------------------------------------------------------
// Level 3 — outcomes × models  (this is `/compare`, scoped to one class)
// ---------------------------------------------------------------------------

function outcomeSpec(
  outcome: OutcomeTile,
  tile: ClassTile,
  majorSlug: string,
): EntitySpec {
  return {
    key: outcome.slo,
    eyebrow: outcome.slo,
    heading: outcome.title,
    href: `/explore/${majorSlug}/${tile.slug}/${outcome.slo.toLowerCase()}`,
    benchmarkable: outcome.benchmarkable,
    note: outcome.note,
    noun: "this outcome",
    pronoun: { singular: "it", plural: "them" },
    slos: [outcome.slo],
    families: tile.task_families,
    tasksAvailable: outcome.tasks_available,
    status: outcome.status,
    reason: outcome.reason,
    // The published LEVEL, which is what makes the number worth anything: a
    // benchmark aimed at a pair the department already grades is aimed at
    // something with a human number to compare against later.
    footnote: outcome.level_label,
  };
}

/**
 * Level 3: the outcomes one class teaches, against every model — the "why".
 *
 * ⚠ EVERY OUTCOME THE MAP MARKS FOR THIS CLASS GETS A COLUMN, including the
 * ones a text benchmark cannot reach. Showing only the measurable ones would
 * make MIS 200 look like a three-outcome class and GBA 300 like a five-outcome
 * one, which is a claim about the curriculum rather than about us — and it is
 * the exact edit `curriculum/slo.yaml` warns against.
 */
export function buildOutcomeMatrix(
  board: LeaderboardResponse,
  tile: ClassTile,
  majorSlug: string,
): ExploreMatrix {
  return assemble(
    board,
    tile.outcomes.map((outcome) => outcomeSpec(outcome, tile, majorSlug)),
    tile.in_curriculum_map
      ? `The published coverage grid marks ${tile.code} against no outcome. That means ` +
          "the map does not mark it — not that it teaches none."
      : `The published curriculum map has no row for ${tile.code}, so there is no ` +
          "outcome breakdown to show. That is a gap in the map, not in the class.",
  );
}

// ---------------------------------------------------------------------------
// The cell link
// ---------------------------------------------------------------------------

/**
 * Where a score cell goes: one level down, carrying the model it was about.
 *
 * ⚠ A CELL IS A CROSSING, SO ITS LINK HAS TO CARRY BOTH HALVES. The column
 * header drills into the entity across every model; a cell is about ONE model
 * on that entity, and dropping the reader back into the full field would throw
 * away the specific thing they clicked. The level below reads `?model=` and
 * opens focused on it.
 */
export function cellHref(entity: MatrixEntityColumn, modelKey: string): string {
  return `${entity.href}?model=${encodeURIComponent(modelKey)}`;
}
