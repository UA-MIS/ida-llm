/**
 * The plain-language "what we found" summary, pinned.
 *
 * ⚠ THIS IS THE MOST DANGEROUS MODULE IN THE BRANCH, and these tests exist in
 * proportion to that. Everywhere else on this site, a number is rendered next
 * to its own trust tell and its own receipt. This module does something the
 * rest of the codebase deliberately refuses to do: it writes an ENGLISH
 * SENTENCE claiming a model is strongest. A sentence has no confidence pip
 * attached to it, a reader will quote it in a meeting without the table
 * underneath, and it is the one thing on the page a professor will remember.
 *
 * So the rules below are not stylistic. Each one is a way this summary could
 * mislead a reader who trusted it:
 *
 *   1. It must never name a winner it cannot defend — not from a tie, not from
 *      a single measured model, not from a test stub.
 *   2. It must never print a number when nothing has been measured.
 *   3. It must carry the caveats WITH the claim, not somewhere below it, so
 *      that quoting the headline alone still quotes something true.
 */

import { describe, expect, it } from "vitest";

import { summariseBoard } from "@/lib/findings";

import { board, result, task, trust } from "./fixtures";

/**
 * Two models measured on one task, with scores you choose.
 *
 * ⚠ `taskOverrides` IS HOW YOU MAKE THE EVIDENCE AI-MARKED, and the distinction
 * cost this file a red test. `verifiable_share` is computed in `lib/rollup.ts`
 * from the TASK's `kind`, not from the result's trust tell — because whether
 * work has a single right answer is a property of the work, not of one model's
 * attempt at it. Setting `trust.kind` alone changes the badge and nothing else.
 */
function twoModels(
  a: number,
  b: number,
  extra: Parameters<typeof result>[0] = {},
  taskOverrides: Parameters<typeof task>[0] = {},
) {
  return board([
    task({
      has_results: true,
      best_model_key: a >= b ? "luna" : "atlas",
      results: [
        result({ model_key: "luna", display_name: "Luna", mean_score: a, ...extra }),
        result({ model_key: "atlas", display_name: "Atlas", mean_score: b, ...extra }),
      ],
      ...taskOverrides,
    }),
  ]);
}

describe("when nothing has been measured", () => {
  const empty = summariseBoard(board([task(), task()]));

  it("names no leader", () => {
    expect(empty.leader).toBeNull();
  });

  it("says so in plain words rather than rendering an empty frame", () => {
    expect(empty.headline).toMatch(/nothing|have not measured|no results/i);
  });

  /**
   * The single worst failure available to this module: a confident-sounding
   * sentence with a fabricated figure in it. Nothing here may contain a decimal
   * that looks like a score.
   */
  it("puts no score-shaped number anywhere in its prose", () => {
    const prose = [empty.headline, ...empty.caveats].join(" ");
    expect(prose).not.toMatch(/\d\.\d\d/);
  });
});

describe("when only a test stub has been measured", () => {
  const stubOnly = summariseBoard(
    board([
      task({
        has_results: true,
        best_model_key: null,
        results: [
          result({
            model_key: "mock",
            display_name: "Mock",
            recommendable: false,
            mean_score: 0.99,
          }),
        ],
      }),
    ]),
  );

  /**
   * A stub returns a fixed answer and scores brilliantly. A summary whose
   * headline reads "Mock is strongest" would be the most embarrassing sentence
   * this project could publish, and it is one `filter` away at all times.
   */
  it("refuses to crown the stub", () => {
    expect(stubOnly.leader).toBeNull();
    expect(stubOnly.headline).not.toMatch(/Mock/);
  });

  it("explains why there is no ranking rather than going quiet", () => {
    expect(stubOnly.headline).toMatch(/stub|nothing.*rank|no.*rank/i);
  });
});

describe("when exactly one model has been measured", () => {
  const single = summariseBoard(
    board([
      task({
        has_results: true,
        best_model_key: "luna",
        results: [result({ mean_score: 0.74 })],
      }),
    ]),
  );

  it("reports the model it measured", () => {
    expect(single.leader?.display_name).toBe("Luna");
    expect(single.headline).toContain("Luna");
  });

  /**
   * "Strongest" is a comparative. With one model there is nothing to compare
   * against, so the word is unearned — and a reader who skims will take it as
   * "we tested several and this won".
   */
  it("never calls it strongest, because there is nothing to be strongest of", () => {
    expect(single.headline).not.toMatch(/strongest|best|leads|ahead|top/i);
  });

  it("says outright that no comparison has happened", () => {
    expect(single.comparable).toBe(false);
    expect(single.caveats.join(" ")).toMatch(/only one model|nothing to compare|no comparison/i);
  });
});

describe("when one model is clearly ahead", () => {
  const clear = summariseBoard(twoModels(0.86, 0.41));

  it("names it, with its score", () => {
    expect(clear.leader?.display_name).toBe("Luna");
    expect(clear.headline).toContain("Luna");
    expect(clear.headline).toContain("86%");
  });

  it("treats the field as comparable", () => {
    expect(clear.comparable).toBe(true);
    expect(clear.rankedCount).toBe(2);
  });
});

describe("when two models are within noise of each other", () => {
  const tie = summariseBoard(twoModels(0.74, 0.72));

  /**
   * Two points apart on ten attempts is not a difference, it is a coin. The
   * headline may still name the higher one — it IS higher — but it must not
   * dress that up as a finding.
   */
  it("says they are too close to separate", () => {
    expect(tie.tooCloseToCall).toBe(true);
    expect(`${tie.headline} ${tie.caveats.join(" ")}`).toMatch(
      /too close|close enough|not a meaningful|within/i,
    );
  });

  it("still refuses the language of a decisive win", () => {
    expect(tie.headline).not.toMatch(/clearly|decisively|much better|far ahead/i);
  });
});

describe("the caveats that travel with every claim", () => {
  it("states how little of the benchmark has actually been run", () => {
    const partial = summariseBoard(
      board([
        task({
          has_results: true,
          best_model_key: "luna",
          results: [result(), result({ model_key: "atlas", display_name: "Atlas", mean_score: 0.5 })],
        }),
        task({ task_id: "slo4/ethics", slo: "SLO4" }),
        task({ task_id: "slo4/ethics-2", slo: "SLO4" }),
      ]),
    );
    // 1 of 3 tasks measured, 1 of 2 outcomes.
    expect(partial.caveats.join(" ")).toMatch(/1 of the 3|1 of 3/);
    expect(partial.coverage.outcomesMeasured).toBe(1);
    expect(partial.coverage.outcomeCount).toBe(2);
  });

  it("warns when the evidence is thin", () => {
    const thin = summariseBoard(
      twoModels(0.86, 0.41, { scored_count: 3, sample_count: 3 }),
    );
    expect(thin.caveats.join(" ")).toMatch(/few|small|thin|handful/i);
  });

  /**
   * A leaderboard built mostly on AI-marked work is a leaderboard of one AI's
   * opinion of others. The reader has to be told that before they act on it.
   */
  it("warns when the ranking rests mostly on AI-marked work", () => {
    const judged = summariseBoard(
      twoModels(
        0.86,
        0.41,
        {
          trust: trust({
            kind: "subjective",
            tier_label: "Subjective",
            confidence: "moderate",
            confidence_label: "Moderate confidence",
          }),
        },
        // The share is read off the task, which is where "has this a single
        // right answer?" actually lives.
        { kind: "subjective", scorer: "llm_judge" },
      ),
    );
    expect(judged.caveats.join(" ")).toMatch(/marked by another AI|AI-marked|judged/i);
  });

  it("does not cry thin evidence when the evidence is not thin", () => {
    const solid = summariseBoard(
      twoModels(0.86, 0.41, { scored_count: 200, sample_count: 200 }),
    );
    expect(solid.caveats.join(" ")).not.toMatch(/handful/i);
  });

  it("always leaves the reader at least one caveat to hold the number against", () => {
    for (const summary of [
      summariseBoard(twoModels(0.86, 0.41)),
      summariseBoard(twoModels(0.74, 0.72)),
    ]) {
      expect(summary.caveats.length).toBeGreaterThan(0);
    }
  });
});

describe("the prose itself", () => {
  const summaries = [
    summariseBoard(board([task(), task()])),
    summariseBoard(twoModels(0.86, 0.41)),
    summariseBoard(twoModels(0.74, 0.72)),
  ];

  it("writes finished sentences everywhere", () => {
    for (const summary of summaries) {
      expect(summary.headline).toMatch(/[.!?]$/);
      for (const caveat of summary.caveats) expect(caveat).toMatch(/[.!?]$/);
    }
  });

  /**
   * The whole point of this block is that it is readable cold, by someone who
   * has never seen the site. Internal vocabulary in it defeats the exercise.
   */
  it("uses none of the vocabulary this project invented", () => {
    for (const summary of summaries) {
      const prose = `${summary.headline} ${summary.caveats.join(" ")}`;
      for (const word of ["SLO", "rollup", "aggregate", "verifiable_share", "use mode", "LLM"]) {
        expect(prose.toLowerCase()).not.toContain(word.toLowerCase());
      }
    }
  });
});
