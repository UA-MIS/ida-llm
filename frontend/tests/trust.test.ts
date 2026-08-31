/**
 * How the trust tell is drawn.
 *
 * The classification lives in the API; what is pinned here is that the drawing
 * never contradicts it — in particular that a missing score never acquires a
 * number on its way to the screen.
 */

import { describe, expect, it } from "vitest";

import {
  confidenceColorVar,
  confidencePips,
  groupByOutcome,
  isDeEmphasised,
  outcomeHeading,
  outcomeOf,
  plainTags,
  residencyGlyph,
  sampleFacets,
  summariseResult,
  trustGlyph,
  titleForUseMode,
} from "@/lib/trust";
import type {
  CurriculumView,
  ModelResult,
  TaskLeaderboard,
  TrustTell,
} from "@/lib/types";

const VERIFIABLE_TRUST: TrustTell = {
  kind: "verifiable",
  scorer: "numeric_match",
  tier_label: "Verifiable",
  headline: "Verifiable — a program compared the answer to a known correct one.",
  confidence: "high",
  confidence_label: "High confidence",
  confidence_reason: "A program checked 5 answers against a gold key.",
  caveats: [],
};

function result(overrides: Partial<ModelResult> = {}): ModelResult {
  return {
    model_key: "luna",
    display_name: "Luna",
    model_tags: ["cloud"],
    data_residency: "third_party",
    data_residency_label: "Sends data to a third party",
    enabled: true,
    recommendable: true,
    mean_score: 0.91,
    scored_count: 5,
    sample_count: 5,
    error_count: 0,
    total_cost_usd: 0,
    trust: VERIFIABLE_TRUST,
    run_id: "run_abc",
    run_status: "succeeded",
    task_content_sha: null,
    measured_at: "2026-08-01T12:00:00Z",
    ...overrides,
  };
}

describe("confidence rendering", () => {
  it("maps each tier to a distinct number of filled pips", () => {
    expect(confidencePips("high")).toEqual({ filled: 3, total: 3 });
    expect(confidencePips("moderate")).toEqual({ filled: 2, total: 3 });
    expect(confidencePips("low")).toEqual({ filled: 1, total: 3 });
    expect(confidencePips("none")).toEqual({ filled: 0, total: 3 });
  });

  it("gives every tier a colour, and 'none' a neutral one", () => {
    expect(confidenceColorVar("high")).toBe("var(--pass)");
    expect(confidenceColorVar("low")).toBe("var(--fail)");
    // Not-measured is not a failure, so it is muted rather than red.
    expect(confidenceColorVar("none")).toBe("var(--muted)");
  });
});

describe("glyphs", () => {
  it("distinguishes a checked score from a judged one", () => {
    expect(trustGlyph("verifiable")).toBe("✓");
    expect(trustGlyph("subjective")).toBe("⚖");
    expect(trustGlyph("verifiable")).not.toBe(trustGlyph("subjective"));
  });

  it("marks a campus-hosted model with a lock", () => {
    expect(residencyGlyph("on_campus")).toBe("🔒");
    expect(residencyGlyph("third_party")).not.toBe(residencyGlyph("on_campus"));
  });
});

describe("summariseResult", () => {
  it("states the score with what it was measured on, in the reader's words", () => {
    // ⚠ "Checked by a program", NOT the API's `tier_label`. This sentence goes
    // into headings and `title` attributes on professor-facing pages, and the
    // raw labels are "Verifiable" and "Subjective (AI-scored)" — the second of
    // which `lib/glossary.ts` exists in part to keep off the page. Pinning the
    // plain form here is what stops the jargon leaking back in through a
    // summary nobody thinks of as copy.
    expect(summariseResult(result())).toBe(
      "Luna: 0.91 on 5 of 5 samples — Checked by a program, high confidence",
    );
  });

  it("NEVER turns a missing score into a number", () => {
    const summary = summariseResult(
      result({
        mean_score: null,
        trust: {
          ...VERIFIABLE_TRUST,
          confidence: "none",
          confidence_label: "Not scored",
          confidence_reason: "Every one of the 5 attempted samples failed.",
        },
      }),
    );
    expect(summary).not.toContain("0.00");
    expect(summary).toContain("failed");
  });
});

describe("isDeEmphasised", () => {
  it("de-emphasises a test stub and an unmeasured pair", () => {
    expect(isDeEmphasised(result({ recommendable: false }))).toBe(true);
    expect(isDeEmphasised(result({ mean_score: null }))).toBe(true);
  });

  it("leaves a real, measured result at full weight", () => {
    expect(isDeEmphasised(result())).toBe(false);
  });
});

/** A stand-in for `curriculum/slo.yaml` — the shape, not a copy of the content. */
const CURRICULUM: CurriculumView = {
  available: true,
  unavailable_reason: null,
  program: "BScBA General Business (core)",
  source: "https://example.invalid/curriculum-map",
  outcomes: [
    {
      id: "SLO2",
      title: "Quantitative Literacy",
      statement: "Students analyze, solve, and communicate…",
      text_benchmarkable: true,
      benchmark_note: "…",
    },
    {
      id: "SLO5",
      title: "Teamwork",
      statement: "Students work effectively in teams…",
      text_benchmarkable: false,
      benchmark_note: "not measurable by a single-turn text benchmark",
    },
    {
      id: "SLO9",
      title: "General Business Knowledge",
      statement: "Students demonstrate knowledge…",
      text_benchmarkable: true,
      benchmark_note: "…",
    },
  ],
  use_modes: [
    { id: "capability", title: "Capability", statement: "Can it do this?", in_use: true },
    { id: "assistive", title: "Assistive", statement: "Can it help?", in_use: false },
  ],
};

const NO_CURRICULUM: CurriculumView = {
  available: false,
  unavailable_reason: "No curriculum/slo.yaml in this deployment.",
  program: null,
  source: null,
  outcomes: [],
  use_modes: [],
};

function task(overrides: Partial<TaskLeaderboard> = {}): TaskLeaderboard {
  return {
    task_id: "t",
    title: "T",
    description: "d",
    kind: "verifiable",
    domain: "business-analytics",
    scorer: "numeric_match",
    family: "f",
    tags: [],
    slo: null,
    use_mode: null,
    in_benchmark: false,
    sample_count: 5,
    scorable: true,
    unscorable_reason: null,
    results: [],
    has_results: false,
    best_model_key: null,
    ...overrides,
  };
}

describe("tags", () => {
  it("hides the prefixed axis tags, which are rendered from the parsed fields", () => {
    // `slo:SLO2` next to the outcome's real title would print the same fact
    // twice, once in the programme's words and once in raw tag form.
    expect(
      plainTags([
        "slo-benchmark",
        "slo:SLO2",
        "use-mode:capability",
        "ladder-l1",
        "unit-economics",
      ]),
    ).toEqual(["ladder-l1", "unit-economics"]);
  });
});

describe("use mode titles", () => {
  it("takes the wording from the curriculum, never from a table in the UI", () => {
    expect(titleForUseMode(CURRICULUM, "capability")).toBe("Capability");
    expect(titleForUseMode(CURRICULUM, "assistive")).toBe("Assistive");
  });

  it("falls back to the raw id rather than inventing a caption", () => {
    // An id is honest; a guessed caption is the bug this replaced — the old
    // hardcoded map called `assistive` "professor-assist", which is not a word
    // the curriculum uses.
    expect(titleForUseMode(NO_CURRICULUM, "assistive")).toBe("assistive");
    expect(titleForUseMode(CURRICULUM, "instructional")).toBe("instructional");
  });
});

describe("outcome headings", () => {
  it("pairs the id with the programme's own title", () => {
    expect(outcomeHeading(CURRICULUM, "SLO2")).toBe("SLO2 · Quantitative Literacy");
  });

  it("shows a bare id rather than guessing when the curriculum is unavailable", () => {
    expect(outcomeHeading(NO_CURRICULUM, "SLO2")).toBe("SLO2");
    expect(outcomeOf(NO_CURRICULUM, "SLO2")).toBeUndefined();
  });

  it("surfaces an outcome the curriculum does not know, rather than blanking it", () => {
    // `SL02` with a zero is the classic typo. It is a tagging error the CI gate
    // reports; the UI showing it is how the person who must fix it sees it.
    expect(outcomeHeading(CURRICULUM, "SL02")).toBe("SL02");
  });

  it("keeps outcomes that cannot be text-benchmarked visible", () => {
    expect(outcomeOf(CURRICULUM, "SLO5")?.text_benchmarkable).toBe(false);
  });
});

describe("groupByOutcome", () => {
  it("groups in the order the API supplied, not alphabetically", () => {
    // SLO10 would sort before SLO2 as a string; the API sends curriculum order
    // and this function must not re-sort it.
    const tasks = [
      task({ task_id: "b", slo: "SLO9" }),
      task({ task_id: "a", slo: "SLO2" }),
    ];
    expect(groupByOutcome(tasks, ["SLO2", "SLO9"]).map((g) => g.slo)).toEqual([
      "SLO2",
      "SLO9",
    ]);
  });

  it("puts untagged families last under a null key, not in an error state", () => {
    // The exemplar and demo families predate the benchmark. They are real
    // measurements that are simply not filed under an outcome.
    const tasks = [task({ task_id: "legacy" }), task({ task_id: "a", slo: "SLO2" })];
    const groups = groupByOutcome(tasks, ["SLO2"]);
    expect(groups.map((g) => g.slo)).toEqual(["SLO2", null]);
    expect(groups[1]?.tasks.map((t) => t.task_id)).toEqual(["legacy"]);
  });

  it("omits an outcome with no tasks rather than rendering an empty heading", () => {
    expect(groupByOutcome([task({ slo: "SLO2" })], ["SLO2", "SLO9"])).toHaveLength(1);
  });
});

describe("sampleFacets", () => {
  it("reads the un-prefixed per-sample keys in a fixed order", () => {
    expect(
      sampleFacets({
        provenance: "synthetic",
        skill: "contribution-margin-per-unit",
        use_mode: "capability",
        slo: "SLO2",
      }),
    ).toEqual([
      ["slo", "SLO2"],
      ["use_mode", "capability"],
      ["skill", "contribution-margin-per-unit"],
      ["provenance", "synthetic"],
    ]);
  });

  it("leaves an author's other metadata keys alone", () => {
    // Deciding which of an author's keys are interesting is how a dashboard
    // eventually hides the one that mattered — so only the four are read, and
    // nothing else is dropped from the underlying data.
    expect(sampleFacets({ slo: "SLO2", something_else: "kept in the data" })).toEqual([
      ["slo", "SLO2"],
    ]);
  });

  it("survives a task with no metadata at all", () => {
    expect(sampleFacets(undefined)).toEqual([]);
    expect(sampleFacets({})).toEqual([]);
  });
});
