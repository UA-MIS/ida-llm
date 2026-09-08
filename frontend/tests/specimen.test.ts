/**
 * The landing page's specimen — where a pitch is most tempted to overclaim.
 *
 * Every test here pins a rule that, if broken, would put a confident-sounding
 * sentence in the most prominent position on the site with nothing behind it.
 * Two of the three use modes have NO data and cannot yet have any; the page
 * must say that in those words, and must keep saying it as the benchmark grows.
 */

import { describe, expect, it } from "vitest";

import {
  bestMeasured,
  buildSpecimen,
  pickSpecimenOutcome,
  readingFor,
  tasksFor,
  tidyQuoted,
  PREFERRED_SPECIMEN_SLO,
} from "@/lib/specimen";
import type {
  CurriculumView,
  LeaderboardResponse,
  ModelResult,
  OutcomeView,
  TaskLeaderboard,
  TrustTell,
  UseModeView,
} from "@/lib/types";

function trust(overrides: Partial<TrustTell> = {}): TrustTell {
  return {
    kind: "verifiable",
    scorer: "numeric_match",
    tier_label: "Verifiable",
    headline: "A program compared the answer to a known correct one.",
    confidence: "high",
    confidence_label: "High confidence",
    confidence_reason: "A program checked the answers against a gold key.",
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
    task_id: "slo2/l3-break-even",
    title: "Break-even volume",
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

const SLO2: OutcomeView = {
  id: "SLO2",
  title: "Quantitative Literacy",
  statement:
    "Students analyze, solve, and communicate effectively regarding quantitative business problems using appropriate software, data sources, and tools.",
  text_benchmarkable: true,
  benchmark_note: "The one outcome that is straightforwardly checkable.",
};

/** The three modes exactly as `curriculum/slo.yaml` declares them today. */
const MODES: UseModeView[] = [
  {
    id: "capability",
    title: "Capability",
    statement:
      "Can the model itself produce work that would satisfy the outcome, given the same prompt a student is given? The model is the candidate.",
    in_use: true,
  },
  {
    id: "assistive",
    title: "Assistive",
    statement:
      "Does the model improve a student's own work against the outcome without doing it for them -- feedback, critique, a next question? The model is a tutor and the student is the candidate.",
    in_use: false,
  },
  {
    id: "instructional",
    title: "Instructional",
    statement:
      "Can the model do the instructor's side of the outcome -- author an item, apply a marking key, grade against a rubric? The model is staff.",
    in_use: false,
  },
];

const CURRICULUM: CurriculumView = {
  available: true,
  unavailable_reason: null,
  program: "BScBA General Business (core)",
  source: "https://folio.taskstream.com/Folio/CurMap/view.asp",
  outcomes: [
    {
      id: "SLO1",
      title: "Problem Solving",
      statement: "Students assess a business problem…",
      text_benchmarkable: true,
      benchmark_note: "…",
    },
    SLO2,
    {
      id: "SLO5",
      title: "Teamwork",
      statement: "Students demonstrate ability to work effectively on teams…",
      text_benchmarkable: false,
      benchmark_note: "OUT OF SCOPE for a text benchmark.",
    },
  ],
  use_modes: MODES,
  coverage: [],
};

function board(
  tasks: TaskLeaderboard[],
  overrides: Partial<LeaderboardResponse> = {},
): LeaderboardResponse {
  return {
    tasks,
    task_count: tasks.length,
    measured_task_count: tasks.filter((t) => t.has_results).length,
    runs_considered: tasks.reduce((n, t) => n + t.results.length, 0),
    has_any_results: tasks.some((t) => t.has_results),
    curriculum: CURRICULUM,
    benchmark_task_count: tasks.filter((t) => t.in_benchmark).length,
    slos: ["SLO1", "SLO2"],
    use_modes: ["capability"],
    families: ["slo2"],
    domains: ["business-analytics"],
    ...overrides,
  };
}

describe("picking the outcome to quote", () => {
  it("prefers SLO2 — MIS 200's assessment point and the checkable one", () => {
    expect(pickSpecimenOutcome(CURRICULUM)?.id).toBe(PREFERRED_SPECIMEN_SLO);
  });

  it("never quotes an outcome a text benchmark cannot measure", () => {
    // SLO5 Teamwork is `text_benchmarkable: false` and must never be the
    // specimen — leading with an outcome we have said we cannot measure would
    // promise exactly what the curriculum note refuses to.
    const onlyTeamwork: CurriculumView = {
      ...CURRICULUM,
      outcomes: CURRICULUM.outcomes.filter((o) => !o.text_benchmarkable),
    };
    expect(pickSpecimenOutcome(onlyTeamwork)).toBeUndefined();
  });

  it("falls through to another benchmarkable outcome when SLO2 is absent", () => {
    const noSlo2: CurriculumView = {
      ...CURRICULUM,
      outcomes: CURRICULUM.outcomes.filter((o) => o.id !== "SLO2"),
    };
    expect(pickSpecimenOutcome(noSlo2)?.id).toBe("SLO1");
  });

  it("returns nothing when the deployment has no curriculum map", () => {
    expect(
      pickSpecimenOutcome({ ...CURRICULUM, available: false }),
    ).toBeUndefined();
  });
});

describe("the two modes that have no data", () => {
  it.each([["assistive"], ["instructional"]])(
    "reports %s as not-yet-measured, with no number",
    (modeId) => {
      const mode = MODES.find((m) => m.id === modeId)!;
      const reading = readingFor(mode, SLO2, [
        task({ has_results: true, results: [result()] }),
      ]);

      expect(reading.status).toBe("not_authored");
      expect(reading.best).toBeNull();
      expect(reading.headline).toBe("Not measured yet");
      // ⚠ The whole point: a measured `capability` task sitting in the same
      // board must not leak a number into a mode nobody has authored for.
      expect(reading.detail).not.toMatch(/\d\.\d/);
    },
  );

  it("distinguishes 'not authored yet' from 'authored but not run'", () => {
    // Different admissions. Collapsing them would tell a reader that a run is
    // pending when the vocabulary is in fact still reserved.
    const notAuthored = readingFor(MODES[1]!, SLO2, []);
    const notRun = readingFor(MODES[0]!, SLO2, [task({ has_results: false })]);

    expect(notAuthored.status).toBe("not_authored");
    expect(notAuthored.detail).toMatch(/no task has been written/i);

    expect(notRun.status).toBe("not_measured");
    expect(notRun.detail).toMatch(/no model has a finished/i);
  });

  it("captions each mode from the curriculum, never from a table here", () => {
    const reading = readingFor(MODES[2]!, SLO2, []);
    expect(reading.title).toBe("Instructional");
    // The curriculum's own question, not a paraphrase of it.
    expect(reading.question).toContain("author an item, apply a marking key");
  });
});

describe("the measured mode", () => {
  it("reports the real strongest result and its receipt", () => {
    const reading = readingFor(MODES[0]!, SLO2, [
      task({
        has_results: true,
        results: [result({ mean_score: 0.62 }), result({ model_key: "other", display_name: "Other", mean_score: 0.91, run_id: "run_9" })],
      }),
    ]);

    expect(reading.status).toBe("measured");
    expect(reading.best?.meanScore).toBe(0.91);
    expect(reading.best?.runId).toBe("run_9");
    expect(reading.detail).toContain("0.91");
  });

  it("never lets a test stub become the headline finding", () => {
    // The mock scores 1.00 deterministically. A landing page whose one finding
    // came from a fixture would be a lie in the most prominent position.
    const reading = readingFor(MODES[0]!, SLO2, [
      task({
        has_results: true,
        results: [
          result({ model_key: "mock", display_name: "Mock", mean_score: 1.0, recommendable: false }),
          result({ mean_score: 0.55 }),
        ],
      }),
    ]);
    expect(reading.best?.modelKey).toBe("luna");
    expect(reading.best?.meanScore).toBe(0.55);
  });

  it("never lets a seeded row become the headline finding either", () => {
    // The front door's own promise is "exactly one number... and it appears
    // only when a real finished run stands behind it" — no badge, no caveat,
    // because this is the one page that shows no data vocabulary at all. A
    // seeded row scoring higher than a real one must still lose.
    const reading = readingFor(MODES[0]!, SLO2, [
      task({
        has_results: true,
        results: [
          result({ model_key: "demo", display_name: "Demo", mean_score: 0.97, demonstration: true }),
          result({ mean_score: 0.55, demonstration: false }),
        ],
      }),
    ]);
    expect(reading.best?.modelKey).toBe("luna");
    expect(reading.best?.meanScore).toBe(0.55);
  });

  it("reads as not-measured-yet when every result for it is seeded", () => {
    const reading = readingFor(MODES[0]!, SLO2, [
      task({
        has_results: true,
        results: [result({ model_key: "demo", display_name: "Demo", mean_score: 0.9, demonstration: true })],
      }),
    ]);
    expect(reading.status).toBe("not_measured");
    expect(reading.best).toBeNull();
  });

  it("treats a null score as absent, never as a zero", () => {
    const reading = readingFor(MODES[0]!, SLO2, [
      task({ has_results: true, results: [result({ mean_score: null })] }),
    ]);
    expect(reading.status).toBe("not_measured");
    expect(reading.best).toBeNull();
  });

  it("does not count a stub-only task as measured", () => {
    const reading = readingFor(MODES[0]!, SLO2, [
      task({
        has_results: true,
        results: [result({ model_key: "mock", mean_score: 1.0, recommendable: false })],
      }),
    ]);
    expect(reading.status).toBe("not_measured");
  });
});

describe("selecting tasks for a reading", () => {
  it("matches on both the outcome and the mode", () => {
    const tasks = [
      task({ task_id: "a", slo: "SLO2", use_mode: "capability" }),
      task({ task_id: "b", slo: "SLO1", use_mode: "capability" }),
      task({ task_id: "c", slo: "SLO2", use_mode: "assistive" }),
      task({ task_id: "d", slo: null, use_mode: null }),
    ];
    expect(tasksFor(tasks, "SLO2", "capability").map((t) => t.task_id)).toEqual(["a"]);
  });

  it("returns null from bestMeasured when nothing qualifies", () => {
    expect(bestMeasured([])).toBeNull();
    expect(bestMeasured([task({ results: [result({ mean_score: null })] })])).toBeNull();
  });

  it("excludes a seeded row from bestMeasured, same as it excludes a stub", () => {
    expect(
      bestMeasured([
        task({ results: [result({ mean_score: 0.99, demonstration: true })] }),
      ]),
    ).toBeNull();
  });
});

describe("building the whole specimen", () => {
  it("produces one reading per curriculum mode, in curriculum order", () => {
    const specimen = buildSpecimen(board([task({ has_results: true, results: [result()] })]));
    expect(specimen.available).toBe(true);
    if (!specimen.available) return;

    expect(specimen.readings.map((r) => r.modeId)).toEqual([
      "capability",
      "assistive",
      "instructional",
    ]);
    // Exactly one of the three is measurable today, and the page must reflect
    // that rather than showing three confident findings.
    expect(specimen.readings.filter((r) => r.status === "measured")).toHaveLength(1);
    expect(specimen.anyMeasured).toBe(true);
  });

  it("quotes the programme's outcome statement verbatim", () => {
    const specimen = buildSpecimen(board([]));
    if (!specimen.available) throw new Error("expected a specimen");
    expect(specimen.outcome.statement).toBe(SLO2.statement);
    expect(specimen.program).toBe("BScBA General Business (core)");
  });

  it("degrades honestly when the curriculum map is missing", () => {
    const specimen = buildSpecimen(
      board([], {
        curriculum: {
          ...CURRICULUM,
          available: false,
          unavailable_reason: "curriculum/slo.yaml was not mounted",
        },
      }),
    );
    expect(specimen.available).toBe(false);
    if (specimen.available) return;
    expect(specimen.reason).toContain("not mounted");
  });

  it("reports nothing measured on a fresh install rather than an empty finding", () => {
    const specimen = buildSpecimen(board([task({ has_results: false })]));
    if (!specimen.available) throw new Error("expected a specimen");
    expect(specimen.anyMeasured).toBe(false);
    expect(specimen.readings.every((r) => r.best === null)).toBe(true);
  });
});

describe("quoted-text tidying", () => {
  it("converts the YAML's ASCII double hyphen to an em dash", () => {
    expect(tidyQuoted("a tutor -- and a candidate")).toBe("a tutor — and a candidate");
  });

  it("changes glyphs only, never words", () => {
    const original = MODES[1]!.statement;
    expect(tidyQuoted(original).replace(/—/g, "--")).toBe(original.trim());
  });

  it("leaves a hyphenated compound alone", () => {
    expect(tidyQuoted("cost-volume-profit")).toBe("cost-volume-profit");
  });
});
