/**
 * The comparison matrix: every model against every outcome, in one grid.
 *
 * The leaderboard answers "which model is best overall". This answers a
 * different question — "which model is best at WHAT" — and a table sorted by one
 * number cannot show it. A matrix can, because the eye reads a row as a profile
 * and a column as a contest.
 *
 * ⚠ THIS FILE INVENTS NO DATA. It regroups `GET /leaderboard` through the
 * existing rollups and adds exactly one thing of its own: which of five ramp
 * steps a score falls into. Everything else — how a mean is weighted, what
 * counts as measured, why a null is not a zero — already has one implementation
 * in lib/rollup.ts and keeps it.
 *
 * ⚠ THREE KINDS OF EMPTY CELL, AND THEY ARE NOT THE SAME CLAIM. A grid makes
 * absence enormously visible, which is good, and enormously easy to misread,
 * which is not. The three are kept apart everywhere:
 *
 *   measured            a real score, from finished runs
 *   not_measured        tasks exist; nothing has run, or nothing scored
 *   not_benchmarkable   the curriculum says a text benchmark CANNOT measure
 *                       this outcome (SLO5 Teamwork, SLO8 Oral Communication)
 *
 * The third is the one worth the care. A column where every model is blank reads
 * as "every model failed at teamwork" unless the page says, loudly, that nobody
 * even tried — because trying would be the dishonest thing. `curriculum/slo.yaml`
 * calls measuring it and filing it under SLO5 "the most misleading thing in this
 * repository"; a grid that quietly left the column empty would be doing exactly
 * that with whitespace instead of a number.
 */

import { formatScoreValue } from "./format";
import { rollupByModel, rollupByOutcome, isRanked, type ModelRollup } from "./rollup";
import type { Confidence, LeaderboardResponse, OutcomeView } from "./types";

/** How many steps the heat ramp has. Mirrored by `.cg-step-N` in globals.css. */
export const RAMP_STEPS = 5;

/**
 * Which ramp step a score falls into, 1..RAMP_STEPS.
 *
 * ⚠ INTENSITY, NOT A TRAFFIC LIGHT. The steps are one hue getting stronger, so
 * the colour says HOW MUCH and never how good — the same discipline the score
 * bars already follow, and for the reason globals.css gives: these are means
 * over small samples, and a red-to-green ramp turns a 0.55 into a verdict the
 * evidence does not support. The confidence tell, not the colour, is what says
 * how much to trust a cell.
 */
export function rampStep(score: number): number {
  if (!Number.isFinite(score)) return 1;
  const clamped = Math.min(1, Math.max(0, score));
  return Math.min(RAMP_STEPS, Math.floor(clamped * RAMP_STEPS) + 1);
}

export type CellStatus = "measured" | "not_measured" | "not_benchmarkable";

export interface MatrixCell {
  slo: string;
  status: CellStatus;
  /** Null unless `status === "measured"`. Never 0 as a stand-in for absent. */
  score: number | null;
  /** 0 when there is no score — no cell is tinted on the strength of nothing. */
  step: number;
  confidence: Confidence;
  measuredTasks: number;
  tasksAvailable: number;
  scoredSamples: number;
  /** The receipt, when there is one to link. */
  runId: string | null;
  /** Always populated, always specific. Shown on hover and to screen readers. */
  reason: string;
}

export interface MatrixColumn {
  id: string;
  title: string;
  heading: string;
  benchmarkable: boolean;
  /** The curriculum's own words on why an outcome is or is not measurable. */
  note: string;
}

export interface MatrixRow {
  model: ModelRollup;
  cells: MatrixCell[];
  /** Outcomes with a real score. The row's coverage, stated not implied. */
  measuredCount: number;
}

export interface Matrix {
  available: boolean;
  unavailableReason: string | null;
  columns: MatrixColumn[];
  /** Models with at least one real score, strongest coverage first. */
  ranked: MatrixRow[];
  /** Test stubs and unmeasured models. Shown, never ranked. */
  unranked: MatrixRow[];
  /** Tasks the catalogue does not file under any outcome — a footnote, not a column. */
  unfiledTaskCount: number;
  benchmarkableCount: number;
}

/**
 * The minimum a cell's subject has to tell the classifier about itself.
 *
 * ⚠ WIDER THAN AN OUTCOME ON PURPOSE. `/compare` puts one outcome behind every
 * cell; `/explore` puts a programme behind one, a course behind the next, and an
 * outcome behind the third. The three-state rule — measured / not-measured /
 * not-benchmarkable, and never a blank standing in for a nought — is identical
 * for all four, and it is the single most load-bearing rule on this site. So it
 * is stated once, here, and the callers differ only in the NOUN they hand it.
 */
export interface CellSubject {
  /** The id the cell sits under — an outcome id, a course slug, a programme slug. */
  key: string;
  benchmarkable: boolean;
  /** The curriculum's own words on why it is or is not measurable. */
  note: string;
  /**
   * What this cell is about, as a noun phrase a sentence can be built around:
   * "this outcome", "the outcomes this course teaches". Singular and plural
   * variants, because "N tasks measure this outcome" and "…measure them" both
   * have to read as English.
   */
  noun: string;
  pronoun: { singular: string; plural: string };
  /**
   * Who has not run it, as the clause "…but ___ finished, scored run against
   * it": "this model has no" for a per-model cell, "no model has a" for a cell
   * that summarises every model at once.
   *
   * ⚠ A SUMMARY CELL IS NOT A MODEL. `/explore` ends every row with an "All
   * models" cell, and it inherited the per-model sentence — telling a reader
   * that "this model" had not run something, in a square that is about all of
   * them. Small, and exactly the kind of wrong that makes a page look like it
   * was generated rather than written.
   */
  absence: string;
  /**
   * The denominator of "nothing ran" — how many things COULD have produced a
   * score in this cell. Tasks, for a per-model cell; task × model pairings, for
   * a cell that spans every model.
   */
  tasksAvailable: number;
}

/** The subject wording for one learning outcome — `/compare`'s only case. */
export function outcomeSubject(column: MatrixColumn, tasksAvailable: number): CellSubject {
  return {
    key: column.id,
    benchmarkable: column.benchmarkable,
    note: column.note,
    noun: "this outcome",
    pronoun: { singular: "it", plural: "them" },
    absence: "this model has no",
    tasksAvailable,
  };
}

/**
 * Which of the three things a cell is, and the sentence that says so.
 *
 * ⚠ THE ONE IMPLEMENTATION OF THE THREE-STATE RULE. Every grid on this site —
 * the comparison matrix and all three levels of the drill-down — routes its
 * cells through this function, so a course grid physically cannot classify a
 * pairing differently from the leaderboard that feeds it. Duplicating the rule
 * per page is what let `/explore/[major]/[course]` ship without a disclosure
 * three other pages already had.
 */
export function classifyCell(
  subject: CellSubject,
  agg:
    | {
        score: number | null;
        confidence: Confidence;
        measured_tasks: number;
        scored_samples: number;
        latest_run_id: string | null;
      }
    | undefined,
): MatrixCell {
  const { tasksAvailable } = subject;

  const base = {
    slo: subject.key,
    confidence: agg?.confidence ?? ("none" as Confidence),
    measuredTasks: agg?.measured_tasks ?? 0,
    tasksAvailable,
    scoredSamples: agg?.scored_samples ?? 0,
    runId: agg?.latest_run_id ?? null,
  };

  // Checked FIRST, and before looking at any score: an outcome the curriculum
  // says a text benchmark cannot measure is not a gap in our coverage, it is a
  // boundary we published. It must never read as a model's failure.
  if (!subject.benchmarkable) {
    return {
      ...base,
      status: "not_benchmarkable",
      score: null,
      step: 0,
      reason:
        `Not measurable by a text benchmark, so nothing was run. ${subject.note}`.trim(),
    };
  }

  if (agg == null || agg.score === null) {
    return {
      ...base,
      status: "not_measured",
      score: null,
      step: 0,
      reason:
        tasksAvailable === 0
          ? `No task in the catalogue measures ${subject.noun} yet.`
          // ⚠ THE VERB AGREES WITH THE NOUN. "1 task measure this outcome"
          // was what shipped, on the one sentence whose entire job is to stop
          // an empty square reading as a zero. `lib/rollup.ts` makes the same
          // argument about "1 of the 2 models have been measured": a caveat
          // that reads as machine-generated is a caveat nobody believes.
          : `${tasksAvailable} ${tasksAvailable === 1 ? "task measures" : "tasks measure"} ${subject.noun}, ` +
            `but ${subject.absence} finished, scored run against ` +
            `${tasksAvailable === 1 ? subject.pronoun.singular : subject.pronoun.plural}.`,
    };
  }

  return {
    ...base,
    status: "measured",
    score: agg.score,
    step: rampStep(agg.score),
    reason:
      `${formatScoreValue(agg.score)} across ${agg.measured_tasks} measured task` +
      `${agg.measured_tasks === 1 ? "" : "s"} (${agg.scored_samples} scored sample` +
      `${agg.scored_samples === 1 ? "" : "s"}).`,
  };
}

/** Column set: every published outcome, in the curriculum's own order. */
function columnsOf(board: LeaderboardResponse): MatrixColumn[] {
  if (!board.curriculum.available) {
    // Ids are honest; a remembered list of nine titles is not.
    return board.slos.map((id) => ({
      id,
      title: id,
      heading: id,
      benchmarkable: true,
      note: "Outcome statements are unavailable in this deployment.",
    }));
  }
  return board.curriculum.outcomes.map((outcome: OutcomeView) => ({
    id: outcome.id,
    title: outcome.title,
    heading: `${outcome.id} · ${outcome.title}`,
    benchmarkable: outcome.text_benchmarkable,
    note: outcome.benchmark_note,
  }));
}

/**
 * Build the whole matrix from one leaderboard response.
 *
 * Row order puts the widest real COVERAGE first, then the strongest overall
 * score — because the question this page answers is "who is good at what", and a
 * model measured on one outcome has not answered it however well it did there.
 */
export function buildMatrix(board: LeaderboardResponse): Matrix {
  const columns = columnsOf(board);
  const models = rollupByModel(board);

  const rows: MatrixRow[] = models.map((model) => {
    const byOutcome = rollupByOutcome(model, board);
    const lookup = new Map(byOutcome.map((row) => [row.slo, row]));
    const cells = columns.map((column) => {
      const row = lookup.get(column.id);
      return classifyCell(
        outcomeSubject(column, row?.tasks_available ?? 0),
        row?.aggregate,
      );
    });
    return {
      model,
      cells,
      measuredCount: cells.filter((cell) => cell.status === "measured").length,
    };
  });

  const ranked = rows
    .filter((row) => isRanked(row.model))
    .sort(
      (a, b) =>
        b.measuredCount - a.measuredCount ||
        (b.model.overall.score ?? 0) - (a.model.overall.score ?? 0),
    );

  return {
    available: columns.length > 0,
    unavailableReason:
      columns.length > 0
        ? null
        : (board.curriculum.unavailable_reason ??
          "This deployment has no curriculum map and no outcome ids in its results, so there are no columns to draw."),
    columns,
    ranked,
    unranked: rows.filter((row) => !isRanked(row.model)),
    unfiledTaskCount: board.tasks.filter((task) => task.slo === null).length,
    benchmarkableCount: columns.filter((column) => column.benchmarkable).length,
  };
}

/**
 * The strongest model on one outcome, for the column footer.
 *
 * Ties are left to the first in row order rather than broken arbitrarily — and
 * a column nobody has measured returns null rather than a winner by default.
 */
export function bestInColumn(
  matrix: Matrix,
  columnIndex: number,
): { row: MatrixRow; cell: MatrixCell } | null {
  let best: { row: MatrixRow; cell: MatrixCell } | null = null;
  for (const row of matrix.ranked) {
    const cell = row.cells[columnIndex];
    if (!cell || cell.status !== "measured" || cell.score === null) continue;
    if (best === null || cell.score > best.cell.score!) best = { row, cell };
  }
  return best;
}

/**
 * How far apart two scores in one column must be before the footer will name a
 * winner.
 *
 * ⚠ THE SAME NUMBER, AND THE SAME ARGUMENT, AS `lib/findings.ts`. The findings
 * paragraph goes to real lengths to refuse "best" without a gap wide enough to
 * survive the sample sizes — and then the grid's own footer crowned a winner in
 * every column with no gap test, no minimum number of competitors, and no
 * regard for confidence. The overclaim the summary refuses two pages earlier
 * was being made seven times along the bottom of this grid.
 *
 * Five points on a 0–1 scale is deliberately conservative: it fails to call
 * real differences rather than announcing fake ones, which is the right way
 * round here.
 */
export const MEANINGFUL_GAP = 0.05;

export type ColumnVerdict =
  /** Nothing measured in this column — no winner, and not a tie either. */
  | { kind: "none" }
  /** One model measured. A single entrant is not a contest and must not read as one. */
  | { kind: "only"; row: MatrixRow; cell: MatrixCell }
  /** Two or more, separated by less than the gap. Named, but not ranked. */
  | { kind: "tooClose"; row: MatrixRow; cell: MatrixCell; runnerUp: MatrixRow }
  /** A real lead over a real field. */
  | { kind: "best"; row: MatrixRow; cell: MatrixCell };

/**
 * What the column footer is entitled to claim.
 *
 * ⚠ `bestInColumn` IS STILL THE ARITHMETIC AND THIS IS STILL THE CLAIM, kept
 * apart on purpose. "Which cell is highest" is a fact; "which model is
 * strongest at this outcome" is an assertion about the world, and the second one
 * needs guards the first does not.
 */
export function columnVerdict(matrix: Matrix, columnIndex: number): ColumnVerdict {
  const measured = matrix.ranked
    .map((row) => ({ row, cell: row.cells[columnIndex] }))
    .filter(
      (entry): entry is { row: MatrixRow; cell: MatrixCell } =>
        entry.cell !== undefined &&
        entry.cell.status === "measured" &&
        entry.cell.score !== null,
    )
    .sort((a, b) => b.cell.score! - a.cell.score!);

  if (measured.length === 0) return { kind: "none" };

  const top = measured[0]!;
  if (measured.length === 1) return { kind: "only", row: top.row, cell: top.cell };

  const runnerUp = measured[1]!;
  if (top.cell.score! - runnerUp.cell.score! < MEANINGFUL_GAP) {
    return { kind: "tooClose", row: top.row, cell: top.cell, runnerUp: runnerUp.row };
  }
  return { kind: "best", row: top.row, cell: top.cell };
}
