/**
 * The intake's branch logic.
 *
 * These pin the two behaviours that make the flow a conversation rather than a
 * form: a question only appears when it applies, and an answer is genuinely
 * *retracted* when its question stops applying. The second one is not cosmetic
 * — `ferpa_hard_requirement` sets a HARD constraint, so a stale copy of it
 * silently changes the recommendation.
 */

import { describe, expect, it } from "vitest";

import {
  applicableQuestions,
  missingRequired,
  nextQuestion,
  progress,
  pruneAnswers,
} from "@/lib/intake";
import type { IntakeQuestion } from "@/lib/types";

function question(
  id: string,
  overrides: Partial<IntakeQuestion> = {},
): IntakeQuestion {
  return {
    id,
    prompt: `${id}?`,
    detail: null,
    options: [
      { value: "yes", label: "Yes", detail: null },
      { value: "no", label: "No", detail: null },
    ],
    required: true,
    why_it_matters: "because",
    depends_on: null,
    branch_note: null,
    ...overrides,
  };
}

/** A miniature of the real tree: role -> student_data -> ferpa. */
const TREE: IntakeQuestion[] = [
  question("role", {
    options: [
      { value: "teacher", label: "Teaching", detail: null },
      { value: "researcher", label: "Research", detail: null },
    ],
  }),
  question("student_data", {
    depends_on: { question_id: "role", values: ["teacher"] },
  }),
  question("ferpa_hard_requirement", {
    depends_on: { question_id: "student_data", values: ["yes"] },
  }),
  question("stakes"),
  question("surface", { required: false }),
];

describe("applicableQuestions", () => {
  it("hides a branch until its trigger is answered", () => {
    const ids = applicableQuestions(TREE, {}).map((q) => q.id);
    expect(ids).toEqual(["role", "stakes", "surface"]);
  });

  it("opens the FERPA branch only once student data is admitted", () => {
    const asTeacher = { role: "teacher" };
    expect(applicableQuestions(TREE, asTeacher).map((q) => q.id)).toContain(
      "student_data",
    );
    expect(applicableQuestions(TREE, asTeacher).map((q) => q.id)).not.toContain(
      "ferpa_hard_requirement",
    );

    const admitted = { ...asTeacher, student_data: "yes" };
    expect(applicableQuestions(TREE, admitted).map((q) => q.id)).toContain(
      "ferpa_hard_requirement",
    );
  });

  it("never asks a researcher about student data", () => {
    const ids = applicableQuestions(TREE, { role: "researcher" }).map((q) => q.id);
    expect(ids).not.toContain("student_data");
    expect(ids).not.toContain("ferpa_hard_requirement");
  });
});

describe("missingRequired", () => {
  it("counts only the questions that currently apply", () => {
    expect(missingRequired(TREE, {}).map((q) => q.id)).toEqual(["role", "stakes"]);
  });

  it("never blocks on an optional question", () => {
    const missing = missingRequired(TREE, {
      role: "researcher",
      stakes: "yes",
    });
    expect(missing).toEqual([]);
  });

  it("treats teaching_task and student_task as either/or for a teacher", () => {
    const tree: IntakeQuestion[] = [
      question("role", {
        options: [
          { value: "teacher", label: "Teaching", detail: null },
          { value: "both", label: "Both", detail: null },
        ],
      }),
      question("teaching_task"),
      question("student_task"),
      question("stakes"),
    ];
    expect(
      missingRequired(tree, {
        role: "teacher",
        teaching_task: "yes",
        stakes: "yes",
      }).map((q) => q.id),
    ).toEqual([]);
    expect(
      missingRequired(tree, {
        role: "both",
        student_task: "yes",
        stakes: "yes",
      }).map((q) => q.id),
    ).toEqual([]);
    expect(
      missingRequired(tree, { role: "teacher", stakes: "yes" }).map((q) => q.id),
    ).toEqual(["teaching_task", "student_task"]);
  });
});

describe("nextQuestion", () => {
  it("asks required questions before optional ones", () => {
    expect(nextQuestion(TREE, {})?.id).toBe("role");
    expect(nextQuestion(TREE, { role: "researcher" })?.id).toBe("stakes");
  });

  it("falls through to the optional questions once nothing is required", () => {
    expect(nextQuestion(TREE, { role: "researcher", stakes: "yes" })?.id).toBe(
      "surface",
    );
  });

  it("returns null when the applicable tree is exhausted", () => {
    expect(
      nextQuestion(TREE, { role: "researcher", stakes: "yes", surface: "yes" }),
    ).toBeNull();
  });
});

describe("progress", () => {
  it("measures against the live branch, not the whole tree", () => {
    // A researcher will never see student_data or ferpa, so counting them
    // would show a bar that can never fill.
    expect(progress(TREE, { role: "researcher" })).toEqual({
      answered: 1,
      total: 3,
    });
    expect(progress(TREE, { role: "teacher" })).toEqual({
      answered: 1,
      total: 4,
    });
  });
});

describe("pruneAnswers", () => {
  it("retracts an answer whose question no longer applies", () => {
    const answers = {
      role: "teacher",
      student_data: "yes",
      ferpa_hard_requirement: "yes",
    };
    const afterChangingMind = pruneAnswers(TREE, {
      ...answers,
      student_data: "no",
    });
    expect(afterChangingMind).toEqual({ role: "teacher", student_data: "no" });
  });

  it("cascades: retracting one answer retracts what depended on it", () => {
    // role: teacher -> researcher retracts student_data, which must in turn
    // retract ferpa. A single pass would leave ferpa behind — and ferpa is the
    // answer that sets a hard constraint.
    const pruned = pruneAnswers(TREE, {
      role: "researcher",
      student_data: "yes",
      ferpa_hard_requirement: "yes",
      stakes: "yes",
    });
    expect(pruned).toEqual({ role: "researcher", stakes: "yes" });
  });

  it("leaves a fully-consistent answer set untouched", () => {
    const answers = {
      role: "teacher",
      student_data: "yes",
      ferpa_hard_requirement: "no",
      stakes: "yes",
    };
    expect(pruneAnswers(TREE, answers)).toEqual(answers);
  });
});
