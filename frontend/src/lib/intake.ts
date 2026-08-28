/**
 * Client-side branch logic for the recommendation intake.
 *
 * ⚠ THIS IS NOT THE GATE. The engine re-derives every one of these decisions
 * server-side (`ida_api/recommend.py :: applicable_questions`) before it will
 * answer, and the server's verdict is the only one that counts. What lives here
 * is the *form*: which question to draw next, how far along the professor is,
 * and whether the Ask button should be live yet — feedback that has to be
 * instant, and that is worthless if it costs a round trip per keystroke.
 *
 * The two implementations agree because they read the same `depends_on`
 * conditions off the same served question tree. Neither invents a rule.
 */

import type { IntakeQuestion } from "./types";

export type Answers = Record<string, string>;

/**
 * The questions that apply given what has been answered so far.
 *
 * A question with no condition always applies. A conditional one applies only
 * when its trigger question currently holds one of the listed values — so
 * changing "role" from teacher to researcher retracts the FERPA branch rather
 * than leaving a stale, unanswerable question on screen.
 */
export function applicableQuestions(
  questions: IntakeQuestion[],
  answers: Answers,
): IntakeQuestion[] {
  return questions.filter((question) => {
    const condition = question.depends_on;
    if (!condition) return true;
    const current = answers[condition.question_id];
    return current !== undefined && condition.values.includes(current);
  });
}

/** Applicable, required, and not yet answered. What the Ask button waits on. */
export function missingRequired(
  questions: IntakeQuestion[],
  answers: Answers,
): IntakeQuestion[] {
  return applicableQuestions(questions, answers).filter(
    (question) => question.required && !answers[question.id],
  );
}

/**
 * The next question to put in front of the professor, or null when done.
 *
 * Required questions first, in tree order, then the optional ones — so someone
 * who abandons the form halfway has still given us everything that changes the
 * answer, and only the framing questions are missing.
 */
export function nextQuestion(
  questions: IntakeQuestion[],
  answers: Answers,
): IntakeQuestion | null {
  const applicable = applicableQuestions(questions, answers);
  const unanswered = applicable.filter((question) => !answers[question.id]);
  return (
    unanswered.find((question) => question.required) ?? unanswered[0] ?? null
  );
}

/**
 * How far along we are — over the questions that actually apply *right now*.
 *
 * Recomputed against the live branch rather than the full tree: showing "3 of
 * 12" to a researcher who will never see the four teaching questions is a
 * progress bar that lies about how much is left, which is exactly the thing
 * that makes a busy professor bounce.
 */
export function progress(
  questions: IntakeQuestion[],
  answers: Answers,
): { answered: number; total: number } {
  const applicable = applicableQuestions(questions, answers);
  return {
    answered: applicable.filter((question) => answers[question.id]).length,
    total: applicable.length,
  };
}

/**
 * Drop answers whose question no longer applies.
 *
 * Without this, answering "student data: yes", then "no", then submitting would
 * send a stale `ferpa_hard_requirement` the professor has effectively retracted
 * — and that answer sets a HARD constraint. A stale hard constraint silently
 * changes the recommendation, so retraction has to be real, not visual.
 */
export function pruneAnswers(
  questions: IntakeQuestion[],
  answers: Answers,
): Answers {
  // Iterate to a fixed point: retracting one answer can retract another that
  // depended on it, and a single pass would leave the second one behind.
  let current = answers;
  for (let pass = 0; pass < questions.length + 1; pass += 1) {
    const allowed = new Set(
      applicableQuestions(questions, current).map((question) => question.id),
    );
    const pruned = Object.fromEntries(
      Object.entries(current).filter(([id]) => allowed.has(id)),
    );
    if (Object.keys(pruned).length === Object.keys(current).length) return pruned;
    current = pruned;
  }
  return current;
}
