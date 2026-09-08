/**
 * The drill-down, as a matrix: every entity on this level against every model.
 *
 * ⚠ WHAT CHANGED, AND WHY IT IS NOT A RESTYLE. The first `/explore` drew each
 * level as a column of paragraph tiles — one entity, one headline number, one
 * sentence of caption. The client asked for a GRID and meant the one on
 * `/compare`: every entity × every model, one score per cell, the whole level
 * legible in a single glance without scrolling through prose. A tile grid
 * answers "how does this course do overall"; a matrix answers "how does each
 * model do on this course", which is the question a professor choosing a model
 * actually has. The three levels are now the same object at three scopes:
 *
 *   1. programme   majors × models
 *   2. course      the programme's courses × models
 *   3. outcome     the course's outcomes × models  (= `/compare`, scoped)
 *
 * Level 4 — the evidence behind one (course, outcome) pair — is unchanged. It
 * was never a grid and should not become one: it is where the receipts live.
 *
 * ⚠ ENTITIES ARE ROWS, MODELS ARE COLUMNS, WHICH IS `/compare` TRANSPOSED. On
 * `/compare` the reader has come to compare models, so a model is a row and a
 * row is a profile. Here the reader has come to drill, so the ROW is the thing
 * you open — a major, a course, an outcome — and every row header is a link to
 * the level below it. Making the drillable thing the row rather than a column
 * header is the difference between an affordance and a puzzle. The cells, the
 * ramp, the three empty states and the confidence tells are literally the same
 * components either way (`components/score-grid.tsx`).
 *
 * ⚠ THIS FILE INVENTS NO NUMBER, AND ITS ROW HEADLINE IS NOT A SECOND OPINION.
 * Every cell is `aggregate()` from lib/rollup.ts over one model's entries under
 * one entity, and every row's "All models" figure is `aggregate()` over the
 * same entries across every ranked model — the identical function the leaderboard
 * and `/compare` use, with the sample-weighted mean, the weakest-constituent
 * confidence rule and the null-is-not-zero rule already in it. A course
 * headline therefore cannot disagree with the cells beside it, because it is
 * not computed by different code.
 *
 * ⚠ THE THREE EMPTIES STAY THREE DIFFERENT CLAIMS, and a dense grid is where
 * they are easiest to confuse. Classification runs through `classifyCell` in
 * lib/matrix.ts — one implementation, shared with `/compare` — so a course grid
 * physically cannot decide that "nothing ran" and "cannot be measured" are the
 * same square.
 */

import {
  aggregate,
  entriesAreSeeded,
  isRanked,
  rollupByModel,
  summariseDemonstration,
  type DemonstrationTell,
  type ModelRollup,
  type ModelTaskEntry,
  type ScoreAggregate,
} from "./rollup";
import { classifyCell, type MatrixCell } from "./matrix";
import {
  buildCourses,
  buildIndex,
  type CourseTile,
  type ExploreStatus,
  type MajorTile,
  type OutcomeTile,
} from "./explore";
import type { LeaderboardResponse } from "./types";

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

/** One column: a model, as it appears across every row of this level. */
export interface MatrixModelColumn {
  model_key: string;
  display_name: string;
  /** False for test stubs. Shown — they are real rows — but never ranked. */
  recommendable: boolean;
  /** Every score this model contributed to this level was seeded, not measured. */
  seeded: boolean;
}

/** One row: a thing you can open, and how each model reads on it. */
export interface MatrixEntityRow {
  /** URL segment, and the row's React key. */
  key: string;
  /** The small line above the name — "Programme", a course code, an outcome id. */
  eyebrow: string;
  heading: string;
  /** The level below. Every row header is a link; that is the drill. */
  href: string;
  /** One cell per column, in column order. */
  cells: MatrixCell[];
  /**
   * The row's own read across every ranked model — the "All models" column.
   *
   * Not a second computation: the same `aggregate()` over the same entries the
   * cells are built from, so the headline and the cells cannot disagree.
   */
  overall: ScoreAggregate;
  /**
   * That same headline as a cell, classified by the same function as every
   * other cell in the row.
   *
   * ⚠ THE POINT OF THE WHOLE REBUILD, IN ONE FIELD. A tile grid computed a
   * course's headline in one place and its evidence in another, and nothing
   * structural stopped the two from drifting. Here the headline is the same
   * `classifyCell` verdict over the union of the entries its neighbours are
   * built from, rendered by the same `ScoreCell` — it cannot say "measured"
   * beside a row of dashes, because it is not separate code.
   */
  overallCell: MatrixCell;
  status: ExploreStatus;
  /** Why there is (or is not) a number. Always shown, never a tooltip only. */
  reason: string;
  /** Every score behind this row was seeded — the per-row disclosure. */
  seeded: boolean;
  /** Whether a text benchmark can reach this row at all. */
  benchmarkable: boolean;
  /** Extra context for the row header — a level badge, a coverage count. */
  footnote: string;
}

export interface ExploreMatrix {
  /** False when there is nothing to draw, with `unavailable_reason` saying why. */
  available: boolean;
  unavailable_reason: string | null;
  columns: MatrixModelColumn[];
  rows: MatrixEntityRow[];
  /** Seeded-vs-measured across the models that actually appear on this level. */
  demonstration: DemonstrationTell;
  /**
   * Rows a text benchmark can reach — the denominator for a coverage line.
   *
   * ⚠ ROWS, WHICH IS ONLY THE SAME AS OUTCOMES ON LEVEL 3. Levels 1 and 2 count
   * programmes and courses here, while their subtitles count OUTCOMES across
   * them — a different number, correctly, so those pages keep reading it off
   * the tiles in lib/explore.ts. Level 3's rows ARE its outcomes, so it counts
   * these instead and its prose is guaranteed to describe the grid under it.
   */
  benchmarkable_rows: number;
  /** Of those, how many have a score from at least one model. */
  measured_rows: number;
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

/**
 * What one row is, stripped to what the matrix needs to build its cells.
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
  /** How a not-measured cell should name this row: "MIS 200's outcomes". */
  noun: string;
  pronoun: { singular: string; plural: string };
  /** Outcome ids this row covers. The cell filter, and nothing else. */
  slos: string[];
  /** Tasks the catalogue files under any of `slos`. */
  tasksAvailable: number;
  status: ExploreStatus;
  reason: string;
  footnote: string;
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

function tasksUnder(slos: string[], counts: Map<string, number>): number {
  return slos.reduce((n, slo) => n + (counts.get(slo) ?? 0), 0);
}

/** One model's entries under one row. The only filter a cell is built from. */
function entriesUnder(model: ModelRollup, slos: Set<string>): ModelTaskEntry[] {
  return model.entries.filter((entry) => entry.slo !== null && slos.has(entry.slo));
}

/**
 * The columns: every model on the board, ranked ones first.
 *
 * ⚠ TEST STUBS ARE SHOWN BUT NEVER RANKED FIRST, the same rule the leaderboard
 * and `/compare` apply. `best_model_key` excludes stubs "so the winner is never
 * a fixture", and a grid whose leftmost column is a deterministic mock is the
 * same lie in a different shape. They keep their column — they are real rows —
 * they just do not lead.
 */
function columnsOf(models: ModelRollup[], slos: Set<string>): MatrixModelColumn[] {
  return [...models]
    .sort((a, b) => {
      const rank = Number(isRanked(b)) - Number(isRanked(a));
      if (rank !== 0) return rank;
      return (b.overall.score ?? 0) - (a.overall.score ?? 0);
    })
    .map((model) => ({
      model_key: model.model_key,
      display_name: model.display_name,
      recommendable: model.recommendable,
      // Scoped to THIS level, not the whole board: a model measured for real
      // here must not carry an "illustrative" badge because something it was
      // seeded for sits on a different page.
      seeded: entriesAreSeeded(entriesUnder(model, slos)),
    }));
}

function buildRow(
  spec: EntitySpec,
  models: ModelRollup[],
  columns: MatrixModelColumn[],
): MatrixEntityRow {
  const slos = new Set(spec.slos);
  const byKey = new Map(models.map((m) => [m.model_key, m]));

  const cells = columns.map((column) => {
    const model = byKey.get(column.model_key);
    const entries = model ? entriesUnder(model, slos) : [];
    return classifyCell(
      {
        key: `${spec.key}:${column.model_key}`,
        benchmarkable: spec.benchmarkable,
        note: spec.note,
        noun: spec.noun,
        pronoun: spec.pronoun,
        absence: "this model has no",
        tasksAvailable: spec.tasksAvailable,
      },
      entries.length === 0 ? undefined : aggregate(entries),
    );
  });

  // ⚠ THE SAME ENTRIES THE CELLS ARE BUILT FROM. Ranked models only — a stub
  // has a column because it is a real row, but folding it into the row's
  // headline would put a fixture inside the number a professor reads first.
  const ranked = models.filter((m) => m.recommendable);
  const contributing = ranked.flatMap((model) => entriesUnder(model, slos));
  const overall = aggregate(contributing);
  const overallCell = classifyCell(
    {
      key: `${spec.key}:all`,
      benchmarkable: spec.benchmarkable,
      note: spec.note,
      noun: spec.noun,
      pronoun: spec.pronoun,
      // ⚠ NOT A MODEL, SO NOT "THIS MODEL". This square is about all of them.
      absence: "no model has a",
      // ⚠ PAIRINGS, NOT TASKS, AND THE FRACTION IS WHY. `aggregate()` counts a
      // measured (model, task) PAIR, so summing across every ranked model made
      // the numerator count pairings while the denominator still counted tasks
      // — a one-task course with two models rendered "2/1", a fraction above
      // one, in the cell a reader takes as the course's headline. The
      // denominator has to be the same unit the numerator is: every task, once
      // per model that could have run it.
      tasksAvailable: spec.tasksAvailable * ranked.length,
    },
    contributing.length === 0 ? undefined : overall,
  );

  return {
    key: spec.key,
    eyebrow: spec.eyebrow,
    heading: spec.heading,
    href: spec.href,
    cells,
    overall,
    overallCell,
    // ⚠ ONE SOURCE OF TRUTH FOR THE STATUS. Taken from the cell rather than
    // from the tile that supplied the caption, so the badge on a row and the
    // square beside it are the same verdict by construction.
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
  // Every outcome anything on this level touches — the scope the columns'
  // seeded flags and the page's demonstration notice are measured against.
  const levelSlos = new Set(specs.flatMap((spec) => spec.slos));
  const columns = columnsOf(models, levelSlos);
  const rows = specs.map((spec) => buildRow(spec, models, columns));

  // Models with a real, rankable contribution to THIS level — the same scoping
  // `buildEvidence` uses one level down. Not the whole board's split: a course
  // whose own outcomes are all measured must not be told "some figures here are
  // illustrative" because a different course somewhere else is still seeded.
  //
  // ⚠ AND THEIR ENTRIES ARE NARROWED TO THE LEVEL BEFORE THE SPLIT IS TAKEN,
  // which is the half that is easy to miss and was wrong. `summariseDemonstration`
  // asks `isSeeded` of each model, and `isSeeded` reads the model's WHOLE entry
  // set — so a model seeded on every outcome one course teaches, but measured
  // for real on a different course, came back "measured" and the page rendered
  // a grid of entirely illustrative numbers under no banner at all. That is
  // gap #69 and #73 exactly, one scope down: the flag was right per row and per
  // column, and the sentence a reader meets FIRST was silent. Filtering here
  // makes the notice mean what it says — "here" is this level.
  const contributing = models
    .filter((model) => model.recommendable)
    .map((model) => ({ ...model, entries: entriesUnder(model, levelSlos) }))
    .filter((model) =>
      model.entries.some(
        (entry) => entry.result.mean_score !== null && entry.result.scored_count > 0,
      ),
    );

  const benchmarkable = rows.filter((row) => row.benchmarkable);
  return {
    available: rows.length > 0,
    unavailable_reason: rows.length > 0 ? null : unavailableReason,
    columns,
    rows,
    demonstration: summariseDemonstration(contributing),
    benchmarkable_rows: benchmarkable.length,
    measured_rows: benchmarkable.filter((row) => row.status === "measured").length,
  };
}

// ---------------------------------------------------------------------------
// Level 1 — programmes × models
// ---------------------------------------------------------------------------

function majorSpec(major: MajorTile, board: LeaderboardResponse): EntitySpec {
  // ⚠ EVERY OUTCOME, NOT ONLY THE MEASURABLE ONES. `MajorTile.aggregate`
  // averages every entry filed under any outcome, so narrowing the set here
  // would make the row's headline a DIFFERENT number from the one level 1's
  // own tile computes — the precise disagreement this rebuild exists to make
  // impossible. Nothing is ever run for an unmeasurable outcome, so in
  // practice the two sets are equal; matching them by construction is what
  // keeps that true after somebody files a task badly.
  const slos = board.curriculum.outcomes.map((outcome) => outcome.id);
  return {
    key: major.slug,
    eyebrow: "Programme",
    heading: major.name,
    href: `/explore/${major.slug}`,
    // A programme is not a single outcome, so it is never "out of scope" as a
    // whole: it is reachable if any outcome it publishes is.
    benchmarkable: true,
    note: "",
    noun: "this programme's outcomes",
    pronoun: { singular: "it", plural: "them" },
    slos,
    tasksAvailable: tasksUnder(slos, tasksPerOutcome(board)),
    status: major.status,
    reason: major.reason,
    footnote:
      `${major.course_count} ${major.course_count === 1 ? "course" : "courses"} · ` +
      `${major.measured_count} of ${major.benchmarkable_count} measurable outcomes have a score`,
  };
}

/**
 * Level 1: the programmes on this platform, each a row against every model.
 *
 * ⚠ ONE PROGRAMME TODAY, AND A ONE-ROW MATRIX IS STILL THE RIGHT SHAPE. The
 * curriculum map holds a single `program` string, so this returns one row — but
 * a second programme is a second `slo.yaml`, and a level built as a special
 * case for one is a level nobody rewrites the day the second lands. It is also
 * the only place a reader can see, in one line, which models have been measured
 * against the programme at all.
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
    index.majors.map((major) => majorSpec(major, board)),
    null,
  );
}

// ---------------------------------------------------------------------------
// Level 2 — courses × models
// ---------------------------------------------------------------------------

function courseSpec(course: CourseTile, majorSlug: string): EntitySpec {
  // Every outcome the course teaches, measurable or not — `CourseTile.aggregate`
  // does the same, and the row headline must be that number, not a near-miss.
  const slos = course.outcomes.map((o) => o.slo);
  return {
    key: course.slug,
    eyebrow: course.code,
    heading: course.title,
    href: `/explore/${majorSlug}/${course.slug}`,
    // A course is out of scope only when EVERY outcome it teaches is — which
    // is a real case (`buildCourseTile` has the same branch) and must read as
    // the published boundary it is, never as a course the models failed.
    benchmarkable: course.benchmarkable_count > 0,
    note:
      course.benchmarkable_count > 0
        ? ""
        : "Every outcome this course teaches is one a text benchmark cannot reach.",
    noun: `${course.code}'s outcomes`,
    pronoun: { singular: "it", plural: "them" },
    slos,
    tasksAvailable: 0, // filled in by `buildCourseMatrix`, which has the counts
    status: course.status,
    reason: course.reason,
    footnote:
      `Teaches ${course.outcomes.length} ${course.outcomes.length === 1 ? "outcome" : "outcomes"}` +
      (course.assessment_count > 0
        ? ` · ${course.assessment_count} assessment ${course.assessment_count === 1 ? "point" : "points"}`
        : ""),
  };
}

/** Level 2: the courses of one programme, in the published map's order. */
export function buildCourseMatrix(
  board: LeaderboardResponse,
  majorSlug: string,
): ExploreMatrix {
  const counts = tasksPerOutcome(board);
  // Map order, not score order. Re-sorting a coverage grid by how the models
  // happen to do turns a programme into a ranking of its own courses, which is
  // a claim about the department this benchmark has no business making.
  const specs = buildCourses(board).map((course) => {
    const spec = courseSpec(course, majorSlug);
    return { ...spec, tasksAvailable: tasksUnder(spec.slos, counts) };
  });
  return assemble(
    board,
    specs,
    "The curriculum map has no coverage grid for this programme, so it has no " +
      "courses to drill into.",
  );
}

// ---------------------------------------------------------------------------
// Level 3 — outcomes × models  (this is `/compare`, scoped to one course)
// ---------------------------------------------------------------------------

function outcomeSpec(
  outcome: OutcomeTile,
  majorSlug: string,
  courseSlug: string,
  counts: Map<string, number>,
): EntitySpec {
  return {
    key: outcome.slo,
    eyebrow: outcome.slo,
    heading: outcome.title,
    href: `/explore/${majorSlug}/${courseSlug}/${outcome.slo.toLowerCase()}`,
    benchmarkable: outcome.benchmarkable,
    note: outcome.note,
    noun: "this outcome",
    pronoun: { singular: "it", plural: "them" },
    slos: [outcome.slo],
    tasksAvailable: counts.get(outcome.slo) ?? 0,
    status: outcome.status,
    reason: outcome.reason,
    // The outcome's own statement, in the curriculum's words. The published
    // LEVEL rides on the badge instead — see the page — because a badge is
    // scannable down a column of rows and a sentence is not.
    footnote: outcome.statement,
  };
}

/**
 * Level 3: the outcomes one course teaches, against every model.
 *
 * ⚠ EVERY OUTCOME THE MAP MARKS FOR THIS COURSE GETS A ROW, including the ones
 * a text benchmark cannot reach. Showing only the measurable ones would make
 * MIS 200 look like a three-outcome course and GBA 300 like a five-outcome one,
 * which is a claim about the curriculum rather than about us — and it is the
 * exact edit `curriculum/slo.yaml` warns against.
 */
export function buildOutcomeMatrix(
  board: LeaderboardResponse,
  course: CourseTile,
  majorSlug: string,
): ExploreMatrix {
  const counts = tasksPerOutcome(board);
  return assemble(
    board,
    course.outcomes.map((outcome) =>
      outcomeSpec(outcome, majorSlug, course.slug, counts),
    ),
    `The published coverage grid marks ${course.code} against no outcome. That ` +
      "means the map does not mark it — not that it teaches none.",
  );
}
