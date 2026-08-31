/**
 * The landing page, rendered.
 *
 * ⚠ WHAT THIS TESTS THAT `specimen.test.ts` CANNOT. That file proves the RULES
 * are right — that an unauthored use mode resolves to "not measured yet" with no
 * number. This one proves the PAGE actually shows it. A landing page that
 * computed three honest readings and then rendered only the flattering one would
 * pass every pure test in this directory, and would be the single most damaging
 * bug this project could ship: the marketing page for a benchmark about honesty,
 * quietly hiding its own gaps.
 *
 * It also pins the front door's two exits, because the whole point of the
 * routing move was that the dense data stays reachable.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  CurriculumView,
  LeaderboardResponse,
  ModelResult,
  TaskLeaderboard,
  TrustTell,
} from "@/lib/types";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

// Imported after the mock is registered — the page calls getLeaderboard at
// module-execution time in its own body, not at import time, but the mock has
// to exist before the module graph is built either way.
const { default: LandingPage } = await import("@/app/page");

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
    mean_score: 0.74,
    scored_count: 8,
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

/** The three modes exactly as `curriculum/slo.yaml` declares them today. */
const CURRICULUM: CurriculumView = {
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
  ],
  use_modes: [
    { id: "capability", title: "Capability", statement: "Can the model itself produce the work?", in_use: true },
    { id: "assistive", title: "Assistive", statement: "Does it improve a student's own work?", in_use: false },
    { id: "instructional", title: "Instructional", statement: "Can it do the instructor's side?", in_use: false },
  ],
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
    slos: ["SLO2"],
    use_modes: ["capability"],
    families: ["slo2"],
    domains: ["business-analytics"],
  };
}

async function renderLanding() {
  render(await LandingPage());
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the landing page's honesty", () => {
  it("shows 'not measured yet' for both modes that have no data", async () => {
    getLeaderboard.mockResolvedValue(
      board([task({ has_results: true, results: [result()] })]),
    );
    await renderLanding();

    // Exactly two of the three readings are unmeasured today, and BOTH must be
    // on the page. This is the assertion that fails if someone "tidies up" the
    // landing by dropping the empty rows.
    expect(await screen.findAllByText(/Not measured yet\./)).toHaveLength(2);
  });

  it("puts no number anywhere near an unmeasured reading", async () => {
    getLeaderboard.mockResolvedValue(
      board([task({ has_results: true, results: [result({ mean_score: 0.74 })] })]),
    );
    await renderLanding();

    for (const modeId of ["assistive", "instructional"]) {
      const row = document.querySelector(`.ld-reading-${modeId}`);
      expect(row, `missing reading for ${modeId}`).not.toBeNull();
      // A score leaking across from the measured capability row is the exact
      // failure this guards.
      expect(row!.textContent).not.toMatch(/\d\.\d\d/);
      expect(within(row as HTMLElement).queryByRole("link")).toBeNull();
    }
  });

  it("shows the real number and a receipt for the measured mode", async () => {
    getLeaderboard.mockResolvedValue(
      board([task({ has_results: true, results: [result({ mean_score: 0.74 })] })]),
    );
    await renderLanding();

    const row = document.querySelector(".ld-reading-capability") as HTMLElement;
    expect(row.textContent).toContain("0.74");
    expect(row.textContent).toContain("Luna");
    // The receipt — a claim on this page is worthless without one.
    // Plain getAttribute rather than a jest-dom matcher: this suite has no
    // jest-dom dependency and does not need one for a single string compare.
    expect(within(row).getByRole("link").getAttribute("href")).toBe(
      "/leaderboard?task=slo2%2Fl3-break-even",
    );
  });

  it("quotes the programme's outcome statement verbatim", async () => {
    getLeaderboard.mockResolvedValue(board([task()]));
    await renderLanding();

    expect(
      screen.getByText(new RegExp(CURRICULUM.outcomes[0]!.statement.slice(0, 60))),
    ).toBeTruthy();
    expect(screen.getByText(/BScBA General Business \(core\)/)).toBeTruthy();
  });

  it("reports all three as unmeasured on a fresh install, with no invented finding", async () => {
    getLeaderboard.mockResolvedValue(board([task({ has_results: false })]));
    await renderLanding();

    expect(screen.getAllByText(/Not measured yet\./)).toHaveLength(3);
    expect(document.body.textContent).not.toMatch(/\d\.\d\d/);
  });
});

describe("the landing page's resilience", () => {
  it("still renders the argument when the API is unreachable", async () => {
    getLeaderboard.mockRejectedValue(new Error("connect ECONNREFUSED"));
    await renderLanding();

    // The pitch is sentences; only the specimen needs the API. A 500 here would
    // be a front door that will not open for the least patient visitor we have.
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain(
      "Your syllabus already says",
    );
    expect(screen.getByText(/not reachable from this page right now/)).toBeTruthy();
  });

  it("says why the example is missing when the curriculum map is absent", async () => {
    getLeaderboard.mockResolvedValue({
      ...board([]),
      curriculum: {
        ...CURRICULUM,
        available: false,
        unavailable_reason: "curriculum/slo.yaml was not mounted",
      },
    });
    await renderLanding();

    expect(screen.getByText(/was not mounted/)).toBeTruthy();
  });
});

describe("the front door's exits", () => {
  it("offers both doors, pointing at the leaderboard and the intake", async () => {
    getLeaderboard.mockResolvedValue(board([task()]));
    await renderLanding();

    const hrefs = Array.from(document.querySelectorAll("a")).map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toContain("/leaderboard");
    expect(hrefs).toContain("/recommend");
  });

  it("never sends a visitor back to the landing for results", async () => {
    // `/` is the pitch now. A "see the results" link left pointing at `/` would
    // loop a professor back onto the sales copy — the specific regression the
    // routing move could introduce.
    getLeaderboard.mockResolvedValue(board([task()]));
    await renderLanding();

    const resultsLinks = Array.from(document.querySelectorAll("a")).filter((a) =>
      /result|found|runs/i.test(a.textContent ?? ""),
    );
    expect(resultsLinks.length).toBeGreaterThan(0);
    for (const link of resultsLinks) {
      expect(link.getAttribute("href")).not.toBe("/");
    }
  });
});

/**
 * QA-25: the landing page had no `<main>` landmark at all and no skip link —
 * every keyboard user had to tab through the whole page with no way to jump
 * past it.
 */
describe("the landing page's landmarks", () => {
  it("wraps its content in a <main> that the skip link actually reaches", async () => {
    getLeaderboard.mockResolvedValue(board([task()]));
    await renderLanding();

    const main = document.querySelector("main");
    expect(main, "no <main> landmark on the landing page").not.toBeNull();
    expect(main!.id).toBe("main-content");

    const skipLink = document.querySelector("a.skip-link");
    expect(skipLink, "no skip link on the landing page").not.toBeNull();
    expect(skipLink!.getAttribute("href")).toBe("#main-content");
  });

  it("keeps the header and footer outside <main>", async () => {
    getLeaderboard.mockResolvedValue(board([task()]));
    await renderLanding();

    const main = document.querySelector("main")!;
    expect(main.querySelector("header")).toBeNull();
    expect(main.querySelector("footer")).toBeNull();
  });
});
