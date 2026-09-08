/**
 * The landing page's specimen: ONE outcome, quoted, with what we can honestly
 * say about it under each of the curriculum's three use modes.
 *
 * ⚠ THIS FILE IS WHERE THE LANDING PAGE IS PREVENTED FROM LYING. The page it
 * feeds is a pitch, and a pitch is exactly where a plausible-sounding sentence
 * is most tempting and least checkable. Every rule that keeps it honest is here,
 * as a pure function, so `tests/specimen.test.ts` can hold it to them.
 *
 * The three rules, in the order they are easiest to break:
 *
 *   1. NEVER INVENT A FINDING. Two of the three use modes (`assistive`,
 *      `instructional`) are `in_use: false` in the curriculum — declared
 *      vocabulary with zero tasks authored against them, and `validate_tasks.py`
 *      actively rejects a task that claims one. There is no data, there cannot
 *      yet BE data, and the page says so in those words. A landing page that
 *      showed three confident findings when one mode has been measured would be
 *      the precise thing this project exists to replace.
 *
 *   2. NEVER CAPTION A MODE FROM MEMORY. The titles and the questions come from
 *      `curriculum/slo.yaml` over the wire. lib/trust.ts already documents the
 *      version of this mistake that shipped once: a hardcoded map that said
 *      `professor-assist` for what the curriculum calls `assistive`. The
 *      curriculum's `use_modes[].statement` fields are ALREADY phrased as the
 *      three questions, so there is nothing to write here — only to quote.
 *
 *   3. NEVER CLAIM THE COURSE MAPPING. `curriculum/slo.yaml` knows that MIS 200
 *      carries SLO2 at assessment level, but `CurriculumView` does not put
 *      `coverage` on the wire, so the frontend genuinely does not know it. The
 *      specimen is therefore labelled by programme and outcome — both of which
 *      the API does serve — and says nothing about which course teaches it.
 *      See the deferral note in the landing page.
 */

import { formatScoreValue } from "./format";
import { plainTaskKind } from "./glossary";

import type {
  CurriculumView,
  LeaderboardResponse,
  ModelResult,
  OutcomeView,
  TaskLeaderboard,
  UseModeView,
} from "./types";

/**
 * The outcome we would rather quote, when the deployment has it.
 *
 * SLO2 is MIS 200's assessment point in the published curriculum map, and it is
 * the one outcome whose `benchmark_note` calls it "straightforwardly checkable"
 * — a break-even volume is a number, so a finding about it rests on a
 * programmatic scorer rather than on a judge. That makes it the most defensible
 * thing to put in front of a sceptical reader.
 *
 * ⚠ A PREFERENCE, NOT AN ASSUMPTION. If the deployment's curriculum has no
 * SLO2, `pickSpecimenOutcome` falls through to the first benchmarkable outcome
 * rather than rendering a blank quote or, worse, a remembered one.
 */
export const PREFERRED_SPECIMEN_SLO = "SLO2";

export type ReadingStatus =
  /** Real finished runs stand behind this. A number may be shown. */
  | "measured"
  /** Tasks exist for it, but no model has a finished, scored run yet. */
  | "not_measured"
  /** The curriculum declares the mode but forbids authoring against it yet. */
  | "not_authored";

export interface SpecimenReading {
  modeId: string;
  /** From the curriculum. Never a string in this file. */
  title: string;
  /** The curriculum's own question for this mode. Never a string in this file. */
  question: string;
  status: ReadingStatus;
  /** The short verdict. Factual when measured; an admission otherwise. */
  headline: string;
  /** Why the page can or cannot say more. Always present. */
  detail: string;
  /** Tasks tied to this outcome AND this mode. */
  taskCount: number;
  /** How many of those have at least one finished run. */
  measuredTaskCount: number;
  /** The strongest measured result, or null. Never fabricated. */
  best: {
    modelKey: string;
    displayName: string;
    meanScore: number;
    scoredCount: number;
    sampleCount: number;
    trustLabel: string;
    confidenceLabel: string;
    runId: string;
    taskId: string;
  } | null;
}

export interface Specimen {
  available: true;
  outcome: OutcomeView;
  /** e.g. "BScBA General Business (core)". Null when the map omits it. */
  program: string | null;
  source: string | null;
  readings: SpecimenReading[];
  /** True when at least one reading has real numbers behind it. */
  anyMeasured: boolean;
}

export interface SpecimenUnavailable {
  available: false;
  /** Said out loud on the page. An empty panel with no explanation is worse. */
  reason: string;
}

export type SpecimenResult = Specimen | SpecimenUnavailable;

/**
 * Display-only tidy-up of the curriculum's ASCII double hyphen.
 *
 * The YAML is written in plain ASCII so it stays diffable and copy-pasteable;
 * ` -- ` in running prose renders as a typo on a page set in a serif. This
 * changes glyphs, never words — and it is deliberately the ONLY transformation
 * applied to a quoted curriculum string anywhere in this file.
 */
export function tidyQuoted(text: string): string {
  return text.replace(/\s--\s/g, " — ").trim();
}

/** The outcome to quote, or undefined when the curriculum is unavailable/empty. */
export function pickSpecimenOutcome(
  curriculum: CurriculumView | undefined,
): OutcomeView | undefined {
  if (!curriculum?.available) return undefined;
  const benchmarkable = curriculum.outcomes.filter(
    (outcome) => outcome.text_benchmarkable,
  );
  return (
    benchmarkable.find((outcome) => outcome.id === PREFERRED_SPECIMEN_SLO) ??
    benchmarkable[0]
  );
}

/**
 * The strongest measured result across a set of tasks.
 *
 * ⚠ "STRONGEST" MEANS HIGHEST REAL SCORE, and a null score is not a low one. A
 * model with no number contributes nothing here rather than a zero — the same
 * rule the leaderboard's rollup follows, for the same reason.
 *
 * ⚠ TEST STUBS ARE EXCLUDED. `recommendable` is false for the mock model, and a
 * landing page whose one headline finding came from a deterministic fixture
 * would be a lie in the most prominent position on the site. The leaderboard
 * already excludes stubs from `best_model_key` for exactly this reason.
 *
 * ⚠ SEEDED ROWS ARE EXCLUDED TOO, NOT BADGED. This page's own header comment
 * promises "exactly one number... and it appears only when a real finished run
 * stands behind it" — the one place on the site that draws no `demonstration`
 * caveat at all, on purpose: the front door is deliberately spare ("the dense
 * data stays off this page"), so a seeded row here just reads as "not measured
 * yet" and falls through to the same honest empty state `readingFor` already
 * has for that. See `entriesAreSeeded`/`isSeeded` in lib/rollup.ts for the
 * identical rule everywhere else it is disclosed rather than dropped.
 */
export function bestMeasured(
  tasks: TaskLeaderboard[],
): { task: TaskLeaderboard; result: ModelResult } | null {
  let winner: { task: TaskLeaderboard; result: ModelResult } | null = null;
  for (const task of tasks) {
    for (const result of task.results) {
      if (!result.recommendable) continue;
      if (result.demonstration) continue;
      if (result.mean_score === null) continue;
      if (winner === null || result.mean_score > winner.result.mean_score!) {
        winner = { task, result };
      }
    }
  }
  return winner;
}

/** Tasks measuring this outcome under this mode. */
export function tasksFor(
  tasks: TaskLeaderboard[],
  outcomeId: string,
  modeId: string,
): TaskLeaderboard[] {
  return tasks.filter(
    (task) => task.slo === outcomeId && task.use_mode === modeId,
  );
}

/**
 * One reading — what we can say about this outcome under this use mode.
 *
 * The branch order matters: `in_use === false` is checked FIRST, because it is a
 * statement about the benchmark's design rather than about its progress. "No
 * task has been authored for this yet" and "tasks exist but nothing has run"
 * are different admissions, and collapsing them would tell a reader that work is
 * pending when in fact the vocabulary is still reserved.
 */
export function readingFor(
  mode: UseModeView,
  outcome: OutcomeView,
  allTasks: TaskLeaderboard[],
): SpecimenReading {
  const tasks = tasksFor(allTasks, outcome.id, mode.id);
  const measured = tasks.filter((task) => task.has_results);
  const base = {
    modeId: mode.id,
    title: mode.title,
    question: tidyQuoted(mode.statement),
    taskCount: tasks.length,
    measuredTaskCount: measured.length,
  };

  if (!mode.in_use) {
    return {
      ...base,
      status: "not_authored",
      headline: "Not measured yet",
      detail: `The curriculum defines this question, but no task has been written against it yet.`,
      best: null,
    };
  }

  const winner = bestMeasured(measured);
  if (winner === null) {
    return {
      ...base,
      status: "not_measured",
      headline: "Not measured yet",
      detail:
        tasks.length === 0
          ? `No task tied to this outcome asks this question yet.`
          : `${tasks.length} task${tasks.length === 1 ? " asks" : "s ask"} this ` +
            `question, but no model has a finished, scored run against ${tasks.length === 1 ? "it" : "them"} yet.`,
      best: null,
    };
  }

  const { task, result } = winner;
  return {
    ...base,
    status: "measured",
    headline: "Measured",
    detail:
      `Across ${measured.length} measured task${measured.length === 1 ? "" : "s"} ` +
      `for this outcome, the strongest result so far is ` +
      `${result.display_name} at ${formatScoreValue(result.mean_score!)} on ` +
      `${result.scored_count} of ${result.sample_count} scored sample` +
      `${result.sample_count === 1 ? "" : "s"}.`,
    best: {
      modelKey: result.model_key,
      displayName: result.display_name,
      meanScore: result.mean_score!,
      scoredCount: result.scored_count,
      sampleCount: result.sample_count,
      trustLabel: plainTaskKind(result.trust.kind),
      confidenceLabel: result.trust.confidence_label,
      runId: result.run_id,
      taskId: task.task_id,
    },
  };
}

/**
 * Build the specimen from a leaderboard response.
 *
 * Takes the board rather than fetching it: the fetch belongs to the page (which
 * must survive the API being unreachable), and a pure function is what makes
 * every rule above testable without a network.
 */
export function buildSpecimen(board: LeaderboardResponse): SpecimenResult {
  const outcome = pickSpecimenOutcome(board.curriculum);
  if (!outcome) {
    return {
      available: false,
      reason:
        board.curriculum?.unavailable_reason ??
        "This deployment has no curriculum map loaded, so there is no published outcome to quote.",
    };
  }

  const readings = board.curriculum.use_modes.map((mode) =>
    readingFor(mode, outcome, board.tasks),
  );

  return {
    available: true,
    outcome: { ...outcome, statement: tidyQuoted(outcome.statement) },
    program: board.curriculum.program,
    source: board.curriculum.source,
    readings,
    anyMeasured: readings.some((reading) => reading.status === "measured"),
  };
}
