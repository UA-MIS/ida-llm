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
