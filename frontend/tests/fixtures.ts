/**
 * Shared board fixtures for the plain-language layer's tests.
 *
 * Deliberately NOT a refactor of the builders already inlined in
 * `landing.dom.test.tsx` — those pin the landing page and moving them would put
 * an unrelated file in this branch's diff. This file exists because the
 * findings summary and the leaderboard DOM test need the same shapes, and two
 * copies of a fixture drift.
 */

import type {
  CurriculumView,
  LeaderboardResponse,
  ModelResult,
  TaskLeaderboard,
  TrustTell,
} from "@/lib/types";

export function trust(overrides: Partial<TrustTell> = {}): TrustTell {
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

export function result(overrides: Partial<ModelResult> = {}): ModelResult {
  return {
    model_key: "luna",
    display_name: "Luna",
    model_tags: ["cloud"],
    data_residency: "third_party",
    data_residency_label: "Sends data to a third party",
    enabled: true,
    recommendable: true,
    mean_score: 0.74,
    scored_count: 10,
    sample_count: 10,
    error_count: 0,
    total_cost_usd: 0.5,
    // ⚠ THE DEFAULT IS "PRICED BUT UNSIZED", NOT "FREE". A fixture defaulting
    // to a zero rate card would let a value bug pass every test that did not
    // set the field explicitly, and "free" is the exact wrong direction for a
    // default on an axis whose failure mode is calling paid models free.
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

export function task(overrides: Partial<TaskLeaderboard> = {}): TaskLeaderboard {
  return {
    task_id: "slo2/l3-break-even",
    title: "Break-even volume",
    description: "Work out the break-even volume from a cost structure.",
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

export const CURRICULUM: CurriculumView = {
  available: true,
  unavailable_reason: null,
  program: "BScBA General Business (core)",
  source: "https://folio.taskstream.com/Folio/CurMap/view.asp",
  outcomes: [
    {
      id: "SLO2",
      title: "Quantitative Literacy",
      statement:
        "Students analyze, solve, and communicate effectively regarding quantitative business problems using appropriate software, data sources, and tools.",
      text_benchmarkable: true,
      benchmark_note: "Straightforwardly checkable.",
    },
    {
      id: "SLO4",
      title: "Ethical Reasoning",
      statement: "Students identify and evaluate the ethical dimensions of business decisions.",
      text_benchmarkable: true,
      benchmark_note: "Judged against an anchored rubric.",
    },
  ],
  use_modes: [
    { id: "capability", title: "Capability", statement: "Can the model itself produce the work?", in_use: true },
    { id: "assistive", title: "Assistive", statement: "Does it improve a student's own work?", in_use: false },
    { id: "instructional", title: "Instructional", statement: "Can it do the instructor's side?", in_use: false },
  ],
  // ⚠ A REAL GRID, NOT AN EMPTY LIST. `/explore` reads its two middle levels
  // from here and nowhere else, so a fixture with no courses could not
  // exercise a hierarchy at all. Two courses, one of which teaches an outcome
  // the other does not, is the smallest shape that can tell the levels apart.
  coverage: [
    { course: "MIS 200", title: "Fundamentals of MIS", outcomes: { SLO2: "A" } },
    { course: "GBA 300", title: "Business Communications", outcomes: { SLO2: "R", SLO4: "A" } },
  ],
  // ⚠ THE SMALLEST TAXONOMY THAT CAN TELL THE LEVELS APART, and every part of
  // it is load-bearing:
  //
  //   two majors                 so a major grid is a grid and not a special case
  //   MIS 200 with a family      the ONE measurable class — `task()`'s default
  //                              family is "slo2", so the default fixture task
  //                              is attributed here and nowhere else
  //   MIS 221 with no family     a class the catalog lists and nobody has
  //                              written a task about — the commonest real
  //                              state, and the one that must never show a
  //                              number it inherited from MIS 200
  //   MIS 221 absent from the coverage grid above, so it also exercises "the
  //                              curriculum map does not mark this class"
  //   GBA 300 under another major so a score under MIS cannot leak sideways
  majors: [
    {
      id: "management-information-systems",
      name: "Management Information Systems",
      subject_codes: ["MIS"],
      department: "Information Systems, Statistics and Management Science",
      catalog: "https://catalog.ua.edu/undergraduate/business/",
      class_source: "catalog",
      class_source_label: "Transcribed from the course catalog",
      classes: [
        {
          course: "MIS 200",
          title: "Fundamentals of Management Information Systems",
          credit_hours: 3,
          task_families: ["slo2"],
        },
        {
          course: "MIS 221",
          title: "Business Programming I",
          credit_hours: 3,
          task_families: [],
        },
      ],
    },
    {
      id: "general-business",
      name: "General Business",
      subject_codes: ["GBA"],
      department: "Management",
      catalog: null,
      class_source: "core-only",
      class_source_label:
        "Only the classes this major owns in the shared business core",
      classes: [
        {
          course: "GBA 300",
          title: "Business Communications",
          credit_hours: null,
          task_families: [],
        },
      ],
    },
  ],
  unassigned_core: [
    {
      course: "LGS 200",
      reason: "No Legal Studies major exists, so no major owns this core course.",
    },
  ],
};

export function board(
  tasks: TaskLeaderboard[],
  overrides: Partial<LeaderboardResponse> = {},
): LeaderboardResponse {
  return {
    tasks,
    task_count: tasks.length,
    measured_task_count: tasks.filter((t) => t.has_results).length,
    runs_considered: tasks.filter((t) => t.has_results).length,
    has_any_results: tasks.some((t) => t.has_results),
    curriculum: CURRICULUM,
    benchmark_task_count: tasks.length,
    slos: ["SLO2", "SLO4"],
    use_modes: ["capability"],
    families: ["slo2"],
    domains: ["business-analytics"],
    ...overrides,
  };
}
