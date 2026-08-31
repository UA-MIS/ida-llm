/**
 * The jargon boundary.
 *
 * Every string in this file is one a professor was actually shown. The QA pass
 * found `IDA_JUDGE_MODEL_KEY` and `models.yaml` rendering verbatim on 228
 * result cards, which is why the last assertion here is the important one: it
 * does not check a particular replacement, it checks that no operator
 * vocabulary survives at all.
 */

import { describe, expect, it } from "vitest";

import { OPERATOR_VOCABULARY, plainCaveats, plainLanguage } from "@/lib/plain";

/** Verbatim from the live API — the string on the professor-facing cards. */
const LIVE_CAVEAT =
  "This run carries a score, but the platform cannot grade this task today " +
  "(subjective task: scoring it needs an LLM judge, and no judge model is " +
  "configured for this deployment (set IDA_JUDGE_MODEL_KEY to a key in " +
  "models.yaml). The run's transcripts are archived, so it can be graded " +
  "retroactively once one is.) — the score was produced when grading was " +
  "available. Re-running now would not reproduce it.";

describe("plainLanguage", () => {
  it("removes the environment variable name from the live caveat", () => {
    const plain = plainLanguage(LIVE_CAVEAT);
    expect(plain).not.toContain("IDA_JUDGE_MODEL_KEY");
    expect(plain).not.toContain("models.yaml");
    expect(plain).not.toMatch(OPERATOR_VOCABULARY);
  });

  it("keeps the fact that the transcripts survive, which is the reassuring half", () => {
    // The jargon is the defect; the qualification is not. A translation that
    // dropped "it can be marked later" would replace a confusing true sentence
    // with a clear, alarming, incomplete one.
    expect(plainLanguage(LIVE_CAVEAT).toLowerCase()).toContain("kept");
    expect(plainLanguage(LIVE_CAVEAT).toLowerCase()).toContain("re-marked");
  });

  it("does not leave a doubly-nested parenthetical behind", () => {
    const plain = plainLanguage(LIVE_CAVEAT);
    expect(plain).not.toContain("((");
    expect(plain).not.toContain("()");
  });

  it("scrubs a config key even in a sentence it has never seen", () => {
    // The point of the fallback layer: the NEXT leak must not need a code
    // change to be caught, only to be worded well.
    const invented = "Set IDA_SOME_NEW_KEY in models.yaml to enable this.";
    expect(plainLanguage(invented)).not.toMatch(OPERATOR_VOCABULARY);
  });

  it("translates the run detail page's internal vocabulary", () => {
    const plain = plainLanguage(
      "grading it needs LLM-as-judge scoring, which is not implemented in the walking skeleton",
    );
    expect(plain).not.toMatch(OPERATOR_VOCABULARY);
  });

  it("fixes the parenthetical plurals the API emits", () => {
    expect(plainLanguage("3 of 5 sample(s) failed.")).toBe("3 of 5 samples failed.");
    expect(plainLanguage("An AI judge graded only 1 answer(s).")).toContain("1 answer.");
  });

  it("is idempotent, so it is safe to apply at every render", () => {
    const once = plainLanguage(LIVE_CAVEAT);
    expect(plainLanguage(once)).toBe(once);
  });

  it("leaves an already-plain sentence untouched", () => {
    const plain = "No score exists for this pair — this is not a score of zero.";
    expect(plainLanguage(plain)).toBe(plain);
  });
});

describe("plainCaveats", () => {
  it("translates every entry and drops nothing that carried meaning", () => {
    const out = plainCaveats([LIVE_CAVEAT, "Scored by an AI judge, not by a professor."]);
    expect(out).toHaveLength(2);
    for (const caveat of out) expect(caveat).not.toMatch(OPERATOR_VOCABULARY);
  });
});
