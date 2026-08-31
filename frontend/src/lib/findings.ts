/**
 * "What we found", in two human sentences, before any table.
 *
 * ⚠ THIS MODULE BREAKS THE SITE'S OWN RULE ON PURPOSE, AND THAT IS WHY IT IS
 * WRITTEN THIS CAREFULLY. Everywhere else, a number appears welded to its trust
 * tell and its receipt — you cannot read the score without reading what kind of
 * evidence it is. Here we write a SENTENCE. A sentence travels: it gets quoted
 * in a department meeting, pasted into an email, remembered a week later, all
 * without the table that qualified it.
 *
 * The design follows from that one fact:
 *
 *   1. **The caveats are part of the claim, not a footnote.** `headline` and
 *      `caveats` are rendered together and always; there is no code path that
 *      produces a bare headline. If the honest version of a finding needs a
 *      qualifier, the qualifier ships with it.
 *   2. **Comparative language is earned, never assumed.** "Strongest" requires
 *      at least two ranked models AND a gap wide enough to survive the sample
 *      sizes behind it. One model is not a ranking, and two models two points
 *      apart is a coin toss with a decimal point.
 *   3. **Nothing here is a new measurement.** Every figure comes from
 *      `rollupByModel`, which is the same computation the table below renders.
 *      A summary that disagreed with the table underneath it would be worse
 *      than no summary — and it is the obvious way this goes wrong, so it is
 *      structurally impossible rather than merely avoided.
 *   4. **Test stubs can never win.** `isRanked` already excludes them, and this
 *      module never looks past it. A stub returns a fixed answer and therefore
 *      scores brilliantly; "Mock is the strongest model we tested" is the most
 *      embarrassing sentence this project could publish.
 *
 * The vocabulary is deliberately outside the project's own jargon — no "SLO",
 * no "rollup", no "use mode". A reader who needs the glossary to read the
 * plain-language summary has been failed twice.
 */

import { formatScoreValue } from "./format";
import { isRanked, rollupByModel, type ModelRollup } from "./rollup";
import type { LeaderboardResponse } from "./types";

/**
 * How far apart two overall scores must be before we will call it a difference.
 *
 * ⚠ A JUDGEMENT CALL, NOT A STATISTIC. A defensible version of this number
 * would come from the variance of the per-sample scores, which the leaderboard
 * response does not carry. Five points on a 0–1 scale is a deliberately
 * CONSERVATIVE stand-in: it is wider than the gap most small-sample noise
 * produces, so the failure mode is refusing to call a real difference rather
 * than announcing a fake one. That asymmetry is the right way round for a page
 * whose whole argument is that it will not overclaim.
 */
const MEANINGFUL_GAP = 0.05;

/**
 * Below this many scored attempts behind the leader, the summary says out loud
 * that the evidence is thin. Thirty is the usual rule-of-thumb floor for
 * treating a mean as anything but indicative.
 */
const THIN_EVIDENCE = 30;

/** Below this share of program-checked weight, the ranking is mostly one AI's opinion. */
const MOSTLY_JUDGED = 0.5;

export interface FindingsLeader {
  model_key: string;
  display_name: string;
  /** Never null: a rollup without a score is never a leader. */
  score: number;
  scored_samples: number;
  measured_tasks: number;
  outcomes_measured: number;
}

export interface FindingsCoverage {
  measuredTasks: number;
  taskCount: number;
  outcomesMeasured: number;
  outcomeCount: number;
  scoredSamples: number;
  /** 0..1 share of the ranked weight that a program, not an AI, checked. */
  verifiableShare: number;
}

export interface Findings {
  /** One or two sentences. Always a finished sentence, always safe to quote alone. */
  headline: string;
  /** The qualifiers that travel with the headline. Never empty when there is a claim. */
  caveats: string[];
  /** The model the headline names, or null when naming one would be dishonest. */
  leader: FindingsLeader | null;
  /** True only when two or more models can actually be set against each other. */
  comparable: boolean;
  /** True when the top two are inside `MEANINGFUL_GAP`. */
  tooCloseToCall: boolean;
  rankedCount: number;
  coverage: FindingsCoverage;
}

/** "1 of the 3" — written the way a person says it, not "1/3". */
function ofThe(part: number, whole: number, noun: string, pluralNoun?: string): string {
  const word = whole === 1 ? noun : (pluralNoun ?? `${noun}s`);
  return `${part} of the ${whole} ${word}`;
}

function pluralise(count: number, noun: string, pluralNoun?: string): string {
  return `${count} ${count === 1 ? noun : (pluralNoun ?? `${noun}s`)}`;
}

/**
 * How many outcomes anything at all has been measured against.
 *
 * Read off the ranked models' own coverage rather than off the task list: a
 * task existing under an outcome is not a measurement of it, and counting
 * authored-but-never-run tasks here would inflate the one figure a reader uses
 * to judge how much of the programme this benchmark actually speaks to.
 */
function outcomesCovered(ranked: ModelRollup[]): number {
  const covered = new Set<string>();
  for (const rollup of ranked) for (const slo of rollup.slos_measured) covered.add(slo);
  return covered.size;
}

/**
 * The share of the ranked evidence a program checked, weighted by attempts.
 *
 * Sample-weighted rather than a mean of shares, for the same reason the overall
 * score is: a model measured on six attempts must not get an equal vote with
 * one measured on six hundred.
 */
function verifiableShareOf(ranked: ModelRollup[]): number {
  let weighted = 0;
  let total = 0;
  for (const rollup of ranked) {
    weighted += rollup.overall.verifiable_share * rollup.overall.scored_samples;
    total += rollup.overall.scored_samples;
  }
  return total === 0 ? 0 : weighted / total;
}

/**
 * Read a leaderboard response as an honest paragraph.
 *
 * Pure, and driven entirely by `rollupByModel`, so this can never disagree with
 * the table it sits above.
 */
export function summariseBoard(board: LeaderboardResponse): Findings {
  const rollups = rollupByModel(board);
  const ranked = rollups.filter(isRanked);
  // ⚠ DESTRUCTURED HERE, NOT AFTER THE EARLY RETURN, AND NOT INDEXED. The
  // project compiles with `noUncheckedIndexedAccess`, so `ranked[0]` is
  // `ModelRollup | undefined` no matter what a `length` check above it says.
  // Taking the two off the front once, and guarding `top` below, is what makes
  // "there is a leader" a fact the type system carries rather than one the
  // reader has to reconstruct. `rollupByModel` sorts best-first.
  const [top, runnerUp] = ranked;

  const outcomeCount = board.curriculum.available
    ? board.curriculum.outcomes.length
    : board.slos.length;

  const coverage: FindingsCoverage = {
    measuredTasks: board.measured_task_count,
    taskCount: board.task_count,
    outcomesMeasured: outcomesCovered(ranked),
    outcomeCount,
    scoredSamples: ranked.reduce((sum, r) => sum + r.overall.scored_samples, 0),
    verifiableShare: verifiableShareOf(ranked),
  };

  // ---------------------------------------------------------------- no data
  // `isRanked` already guarantees a non-null score for anything in `ranked`;
  // re-checking it here is what proves that to the compiler.
  if (!top || top.overall.score === null) {
    // Two different silences, and conflating them would misinform. "We have not
    // started" and "everything we ran was a rehearsal" are different facts, and
    // the second one is the more confusing of the two to meet unexplained.
    const stubsMeasured = rollups.some((r) => !r.recommendable && r.overall.score !== null);
    const headline = stubsMeasured
      ? "Nothing here is ready to rank yet. The only finished measurements so far come from a stand-in we use to test our own plumbing, and it is not an AI — so there is no honest ranking to show you."
      : board.has_any_results
        ? "Nothing here is ready to rank yet. Work has been run, but none of it produced a score we would stand behind."
        : "We have not measured anything yet. Rather than show you a placeholder, this page stays empty until real results land.";

    return {
      headline,
      caveats: [
        `${ofThe(coverage.measuredTasks, coverage.taskCount, "piece of work", "pieces of work")} in the catalogue ${coverage.measuredTasks === 1 ? "has" : "have"} been measured so far.`,
        "When results do land, every number on this page will link to the full record behind it.",
      ],
      leader: null,
      comparable: false,
      tooCloseToCall: false,
      rankedCount: 0,
      coverage,
    };
  }

  const leaderScore = top.overall.score;

  const comparable = ranked.length > 1;
  const runnerUpScore = runnerUp?.overall.score ?? null;
  const gap = runnerUpScore === null ? null : leaderScore - runnerUpScore;
  const tooCloseToCall = gap !== null && gap < MEANINGFUL_GAP;

  const leader: FindingsLeader = {
    model_key: top.model_key,
    display_name: top.display_name,
    score: leaderScore,
    scored_samples: top.overall.scored_samples,
    measured_tasks: top.overall.measured_tasks,
    outcomes_measured: top.slos_measured.length,
  };

  // -------------------------------------------------------------- the claim
  const scoreText = formatScoreValue(leaderScore);
  let headline: string;

  if (!comparable) {
    // ⚠ NO COMPARATIVE. One model is not a ranking, and "best" here would be
    // read as "we tried several and this won".
    headline =
      `So far we have measured one AI model, ${top.display_name}, which scored ${scoreText} out of 1.00 ` +
      `across ${pluralise(top.overall.measured_tasks, "piece of work", "pieces of work")}. ` +
      `That is a starting point, not a comparison.`;
  } else if (tooCloseToCall && runnerUp && runnerUpScore !== null) {
    headline =
      `${top.display_name} and ${runnerUp.display_name} come out about level at the top — ` +
      `${scoreText} and ${formatScoreValue(runnerUpScore)} out of 1.00 — ` +
      `which on this much evidence is close enough that we would not pick between them.`;
  } else {
    headline =
      `Of the ${pluralise(ranked.length, "AI model")} we have measured, ${top.display_name} comes out ahead overall, ` +
      `scoring ${scoreText} out of 1.00 across ${pluralise(top.overall.measured_tasks, "piece of work", "pieces of work")}. ` +
      `That is an average, not a guarantee on any single one.`;
  }

  // ------------------------------------------------------------ the caveats
  const caveats: string[] = [];

  if (!comparable) {
    caveats.push(
      "Only one model has been measured, so there is nothing to compare it against yet — treat this as a first reading rather than a ranking.",
    );
  }

  caveats.push(
    `This covers ${ofThe(coverage.measuredTasks, coverage.taskCount, "piece of work", "pieces of work")} we have written, ` +
      `against ${coverage.outcomesMeasured} of your programme's ${coverage.outcomeCount} published outcomes. ` +
      `The rest is not a poor result — it simply has not been run yet.`,
  );

  if (top.overall.scored_samples < THIN_EVIDENCE) {
    caveats.push(
      `The ranking rests on a handful of attempts — ${pluralise(top.overall.scored_samples, "scored attempt")} for the model above. ` +
        `A few more could move these numbers, so hold them loosely.`,
    );
  }

  if (coverage.verifiableShare < MOSTLY_JUDGED) {
    caveats.push(
      `Most of this was marked by another AI against a written marking guide rather than checked by a program, ` +
        `because the work has no single right answer. That is an informed second opinion, not a measurement.`,
    );
  }

  caveats.push(
    "Every number below opens onto the full record behind it — what we asked, what the model answered, and how it was marked.",
  );

  return { headline, caveats, leader, comparable, tooCloseToCall, rankedCount: ranked.length, coverage };
}
