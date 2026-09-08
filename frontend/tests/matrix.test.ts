/**
 * The comparison matrix — where a grid is most tempted to imply a zero.
 *
 * A grid makes absence enormously visible, which is the good half, and
 * enormously easy to misread, which is the other half. An empty square reads as
 * zero to almost everyone. Every test here pins one of the distinctions that
 * stops it doing so.
 *
 * The ramp block at the bottom checks something no other test in this suite
 * can: that the colour scale stays READABLE. The cells print their score on top
 * of the tint, so a tint tuned one step too dark makes the number vanish, in one
 * theme only, with nothing else failing.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { AA_NORMAL, contrastRatio, parseHex } from "@/lib/contrast";
import {
  bestInColumn,
  buildMatrix,
  columnVerdict,
  rampStep,
  RAMP_STEPS,
} from "@/lib/matrix";
import type {
  CurriculumView,
  LeaderboardResponse,
  ModelResult,
  TaskLeaderboard,
  TrustTell,
} from "@/lib/types";

function trust(overrides: Partial<TrustTell> = {}): TrustTell {
  return {
    kind: "verifiable",
    scorer: "numeric_match",
    tier_label: "Verifiable",
    headline: "A program compared the answer to a known correct one.",
    confidence: "high",
    confidence_label: "High confidence",
    confidence_reason: "Checked against a gold key.",
    caveats: [],
    ...overrides,
  };
}

function result(overrides: Partial<ModelResult> = {}): ModelResult {
  return {
    model_key: "luna",
    display_name: "Luna",
    model_tags: ["cloud"],
    data_residency: "third_party",
    data_residency_label: "Sends data to a third party",
    enabled: true,
    recommendable: true,
    mean_score: 0.8,
    scored_count: 10,
    sample_count: 10,
    error_count: 0,
    total_cost_usd: 0.5,
    // ⚠ Present so `ModelResult` type-checks; this file's subject is not the
    // value axis. The default mirrors tests/fixtures.ts: PRICED but unsized, so
    // a value bug can never pass by a fixture quietly defaulting to "free".
    price: {
      tier: "paid",
      label: "$0.20 in / $1.20 out per million tokens",
      detail: "A million tokens is roughly 700,000 words.",
      input_usd_per_mtok: 0.2,
      output_usd_per_mtok: 1.2,
    },
    usage: { prompt_tokens: 0, completion_tokens: 0 },
    demonstration: false,
    trust: trust(),
    run_id: "run_1",
    run_status: "succeeded",
    task_content_sha: null,
    measured_at: "2026-08-01T12:00:00Z",
    ...overrides,
  };
}

function task(overrides: Partial<TaskLeaderboard> = {}): TaskLeaderboard {
  return {
    task_id: "slo2/t1",
    title: "T1",
    description: "d",
    kind: "verifiable",
    domain: "business-analytics",
    scorer: "numeric_match",
    family: "slo2",
    tags: [],
    slo: "SLO2",
    use_mode: "capability",
    in_benchmark: true,
    sample_count: 10,
    scorable: true,
    unscorable_reason: null,
    results: [],
    has_results: false,
    best_model_key: null,
    ...overrides,
  };
}

/** SLO5 is `text_benchmarkable: false` in the real curriculum. That matters here. */
const CURRICULUM: CurriculumView = {
  available: true,
  unavailable_reason: null,
  program: "BScBA General Business (core)",
  source: null,
  outcomes: [
    { id: "SLO1", title: "Problem Solving", statement: "…", text_benchmarkable: true, benchmark_note: "Judged." },
    { id: "SLO2", title: "Quantitative Literacy", statement: "…", text_benchmarkable: true, benchmark_note: "Checkable." },
    { id: "SLO5", title: "Teamwork", statement: "…", text_benchmarkable: false, benchmark_note: "OUT OF SCOPE for a text benchmark." },
  ],
  use_modes: [{ id: "capability", title: "Capability", statement: "Can it?", in_use: true }],
  coverage: [],
};

function board(tasks: TaskLeaderboard[]): LeaderboardResponse {
  return {
    tasks,
    task_count: tasks.length,
    measured_task_count: tasks.filter((t) => t.has_results).length,
    runs_considered: 1,
    has_any_results: tasks.some((t) => t.has_results),
    curriculum: CURRICULUM,
    benchmark_task_count: tasks.length,
    slos: ["SLO1", "SLO2"],
    use_modes: ["capability"],
    families: ["slo2"],
    domains: ["business-analytics"],
  };
}

describe("the ramp", () => {
  it("puts a score in the step its magnitude belongs to", () => {
    expect(rampStep(0)).toBe(1);
    expect(rampStep(0.19)).toBe(1);
    expect(rampStep(0.5)).toBe(3);
    expect(rampStep(0.99)).toBe(RAMP_STEPS);
    expect(rampStep(1)).toBe(RAMP_STEPS);
  });

  it("never returns a step outside the scale, whatever it is handed", () => {
    // A score outside 0..1 would be an API bug, but a NaN reaching a className
    // renders `cg-step-NaN`, which silently drops the tint rather than failing.
    for (const value of [-1, 2, Number.NaN, Number.POSITIVE_INFINITY]) {
      const step = rampStep(value);
      expect(step).toBeGreaterThanOrEqual(1);
      expect(step).toBeLessThanOrEqual(RAMP_STEPS);
    }
  });
});

describe("the three kinds of cell", () => {
  it("marks an outcome the curriculum says cannot be text-benchmarked", () => {
    const matrix = buildMatrix(board([task({ has_results: true, results: [result()] })]));
    const row = matrix.ranked[0]!;
    const teamwork = row.cells.find((cell) => cell.slo === "SLO5")!;

    // ⚠ NOT "not_measured". A column where every model is blank reads as "every
    // model failed at teamwork" — but nobody tried, on purpose, because the
    // curriculum calls measuring it and filing it under SLO5 the most
    // misleading thing in the repository.
    expect(teamwork.status).toBe("not_benchmarkable");
    expect(teamwork.reason).toMatch(/not measurable by a text benchmark/i);
    expect(teamwork.reason).toContain("OUT OF SCOPE");
    expect(teamwork.score).toBeNull();
    expect(teamwork.step).toBe(0);
  });

  it("separates 'nothing has run' from 'no task exists'", () => {
    const matrix = buildMatrix(board([task({ slo: "SLO2", has_results: false })]));
    const row = [...matrix.ranked, ...matrix.unranked][0];
    if (!row) return; // no models at all in this board
    const withTasks = row.cells.find((cell) => cell.slo === "SLO2")!;
    const without = row.cells.find((cell) => cell.slo === "SLO1")!;
    expect(withTasks.reason).toMatch(/no finished, scored run/i);
    expect(without.reason).toMatch(/no task in the catalogue/i);
  });

  it("never tints or scores a cell that has no measurement", () => {
    const matrix = buildMatrix(board([task({ has_results: true, results: [result()] })]));
    for (const row of [...matrix.ranked, ...matrix.unranked]) {
      for (const cell of row.cells) {
        if (cell.status === "measured") continue;
        // A zero here, or a step-1 tint, is the grid implying a result.
        expect(cell.score, `${cell.slo} invented a score`).toBeNull();
        expect(cell.step, `${cell.slo} tinted an empty cell`).toBe(0);
        expect(cell.reason.length).toBeGreaterThan(0);
      }
    }
  });

  it("gives every cell a reason, always", () => {
    const matrix = buildMatrix(board([task({ has_results: true, results: [result()] })]));
    for (const row of [...matrix.ranked, ...matrix.unranked]) {
      for (const cell of row.cells) expect(cell.reason.trim()).not.toBe("");
    }
  });
});

describe("columns", () => {
  it("shows every published outcome, including ones nothing has measured", () => {
    // Listing only the outcomes with data turns the grid into a highlight reel.
    const matrix = buildMatrix(board([task({ slo: "SLO2", has_results: true, results: [result()] })]));
    expect(matrix.columns.map((c) => c.id)).toEqual(["SLO1", "SLO2", "SLO5"]);
  });

  it("counts only the measurable outcomes as the coverage denominator", () => {
    // 2 of 3, not 3 of 3: a model can never be measured on SLO5, so scoring it
    // out of three would cap every model below 100% for a reason of our own making.
    const matrix = buildMatrix(board([task({ has_results: true, results: [result()] })]));
    expect(matrix.benchmarkableCount).toBe(2);
  });

  it("falls back to bare ids when the curriculum is unavailable", () => {
    const b = board([task()]);
    const matrix = buildMatrix({
      ...b,
      curriculum: { ...CURRICULUM, available: false, outcomes: [], use_modes: [] },
    });
    expect(matrix.columns.map((c) => c.id)).toEqual(["SLO1", "SLO2"]);
  });
});

describe("rows", () => {
  it("keeps test stubs out of the ranking but still on the page", () => {
    const matrix = buildMatrix(
      board([
        task({
          has_results: true,
          results: [
            result({ model_key: "mock", display_name: "Mock", mean_score: 1, recommendable: false }),
            result({ mean_score: 0.6 }),
          ],
        }),
      ]),
    );
    expect(matrix.ranked.map((r) => r.model.model_key)).toEqual(["luna"]);
    expect(matrix.unranked.map((r) => r.model.model_key)).toContain("mock");
  });

  it("orders by breadth of coverage before strength", () => {
    // A model measured on one outcome has not answered "good at what", however
    // well it did there.
    const matrix = buildMatrix(
      board([
        task({ task_id: "a", slo: "SLO1", has_results: true, results: [result({ model_key: "broad", display_name: "Broad", mean_score: 0.5 })] }),
        task({ task_id: "b", slo: "SLO2", has_results: true, results: [
          result({ model_key: "broad", display_name: "Broad", mean_score: 0.5 }),
          result({ model_key: "narrow", display_name: "Narrow", mean_score: 0.99 }),
        ] }),
      ]),
    );
    expect(matrix.ranked.map((r) => r.model.model_key)).toEqual(["broad", "narrow"]);
  });
});

describe("the column winner", () => {
  it("names nobody when nothing in the column is measured", () => {
    const matrix = buildMatrix(board([task({ slo: "SLO2", has_results: false })]));
    const slo5 = matrix.columns.findIndex((c) => c.id === "SLO5");
    expect(bestInColumn(matrix, slo5)).toBeNull();
  });

  it("never lets a stub win a column", () => {
    const matrix = buildMatrix(
      board([
        task({ slo: "SLO2", has_results: true, results: [
          result({ model_key: "mock", display_name: "Mock", mean_score: 1, recommendable: false }),
          result({ mean_score: 0.4 }),
        ] }),
      ]),
    );
    const slo2 = matrix.columns.findIndex((c) => c.id === "SLO2");
    expect(bestInColumn(matrix, slo2)?.row.model.model_key).toBe("luna");
  });
});

/**
 * What the column footer is allowed to CLAIM, which is a different question
 * from which cell is highest.
 *
 * The footer used to crown a winner in every column from `bestInColumn` alone —
 * no minimum gap, no minimum field, none of the guards `lib/findings.ts`
 * applies to the identical claim two pages earlier. Live it named one model in
 * all seven columns while another model sat visibly above it in several.
 */
describe("the column verdict", () => {
  const twoModels = (a: number, b: number) =>
    buildMatrix(
      board([
        task({ slo: "SLO2", has_results: true, results: [
          result({ model_key: "luna", display_name: "Luna", mean_score: a }),
          result({ model_key: "orion", display_name: "Orion", mean_score: b }),
        ] }),
      ]),
    );
  const slo2Of = (m: ReturnType<typeof buildMatrix>) =>
    m.columns.findIndex((c) => c.id === "SLO2");

  it("names a winner when the lead is wide enough to survive the samples", () => {
    const matrix = twoModels(0.9, 0.4);
    const verdict = columnVerdict(matrix, slo2Of(matrix));
    expect(verdict.kind).toBe("best");
    expect(verdict.kind === "best" && verdict.row.model.model_key).toBe("luna");
  });

  it("REFUSES to name a winner on a gap narrower than the meaningful one", () => {
    // 0.88 vs 0.876 — the live leaderboard's actual top two.
    const matrix = twoModels(0.88, 0.876);
    expect(columnVerdict(matrix, slo2Of(matrix)).kind).toBe("tooClose");
  });

  it("does not crown a model that had no competition", () => {
    const matrix = buildMatrix(
      board([
        task({ slo: "SLO2", has_results: true, results: [result({ mean_score: 0.9 })] }),
      ]),
    );
    const verdict = columnVerdict(matrix, slo2Of(matrix));
    expect(verdict.kind).toBe("only");
  });

  it("says nothing at all about a column nobody measured", () => {
    const matrix = buildMatrix(board([task({ slo: "SLO2", has_results: false })]));
    const slo5 = matrix.columns.findIndex((c) => c.id === "SLO5");
    expect(columnVerdict(matrix, slo5).kind).toBe("none");
  });

  it("still never lets a stub take a column", () => {
    const matrix = buildMatrix(
      board([
        task({ slo: "SLO2", has_results: true, results: [
          result({ model_key: "mock", display_name: "Mock", mean_score: 1, recommendable: false }),
          result({ mean_score: 0.4 }),
        ] }),
      ]),
    );
    const verdict = columnVerdict(matrix, slo2Of(matrix));
    expect(verdict.kind).toBe("only");
    expect(verdict.kind === "only" && verdict.row.model.model_key).toBe("luna");
  });
});

/* ------------------------------------------------------------------------- */
/* The ramp, checked against the real stylesheet                             */
/* ------------------------------------------------------------------------- */

describe("the heat ramp stays readable", () => {
  const CSS = readFileSync(
    fileURLToPath(new URL("../src/app/globals.css", import.meta.url)),
    "utf8",
  );

  /** `color-mix(in srgb, A p%, B)` — the plain sRGB blend the browser performs. */
  function mix(a: string, b: string, pct: number): string {
    const A = parseHex(a);
    const B = parseHex(b);
    const t = pct / 100;
    const channel = (x: number, y: number) =>
      Math.round(x * t + y * (1 - t))
        .toString(16)
        .padStart(2, "0");
    return `#${channel(A.r, B.r)}${channel(A.g, B.g)}${channel(A.b, B.b)}`;
  }

  function token(block: string, name: string): string {
    return block.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,8})\\s*;`))![1]!;
  }

  const darkStart = CSS.indexOf("@media (prefers-color-scheme: dark)");
  const THEMES = {
    light: CSS.slice(CSS.indexOf(":root {"), darkStart),
    dark: CSS.slice(darkStart, CSS.indexOf("* { box-sizing")),
  };

  /** The percentages actually declared by `.cg-step-N`, read from the sheet. */
  const percents = [...CSS.matchAll(/\.cg-step-(\d)\s*\{[^}]*?var\(--accent\)\s*(\d+)%/g)]
    .map((m) => [Number(m[1]), Number(m[2])] as const)
    .sort((a, b) => a[0] - b[0]);

  it("declares one rule per step", () => {
    expect(percents.map(([step]) => step)).toEqual(
      Array.from({ length: RAMP_STEPS }, (_, i) => i + 1),
    );
  });

  it("increases monotonically, so a higher score is never a paler cell", () => {
    const values = percents.map(([, pct]) => pct);
    for (let i = 1; i < values.length; i += 1) {
      expect(values[i]!).toBeGreaterThan(values[i - 1]!);
    }
  });

  it.each(["light", "dark"])(
    "%s: keeps the score readable on every step",
    (themeName) => {
      // ⚠ THE ASSERTION THE WHOLE RAMP IS TUNED AROUND. Each cell prints its
      // score in --fg on the tint. Light alone would allow 69%; dark tops out at
      // 58%, so 58% is the cap. Push a step past it and the number disappears in
      // one theme only — invisible in a screenshot of the other.
      const block = THEMES[themeName as "light" | "dark"];
      const accent = token(block, "accent");
      const surface = token(block, "surface");
      const fg = token(block, "fg");

      for (const [step, pct] of percents) {
        const cell = mix(accent, surface, pct);
        expect(
          contrastRatio(fg, cell),
          `step ${step} (${pct}%) makes the score unreadable in ${themeName}`,
        ).toBeGreaterThanOrEqual(AA_NORMAL);
      }
    },
  );

  it("separates adjacent steps enough to tell them apart", () => {
    // A ramp whose middle steps look identical is decoration, not information.
    const values = percents.map(([, pct]) => pct);
    for (let i = 1; i < values.length; i += 1) {
      expect(values[i]! - values[i - 1]!).toBeGreaterThanOrEqual(8);
    }
  });
});
