/**
 * The recommendation flow's result view, RENDERED.
 *
 * ⚠ QA-32. Heading levels in this flow went out of order: `<h2>Alternatives</h2>`
 * rendered AFTER the `<h3>` recommendation headlines it is meant to introduce
 * (the primary card's headline, and "What we understood" / "What narrowed the
 * field" above it), so a screen-reader user skimming by heading met a level-2
 * heading with no level-2 ancestor and no forward relationship to what preceded
 * it. `lib/intake.test.ts` proves the branch logic; this file proves the
 * rendered heading tree is actually a hierarchy.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Intake } from "@/app/(site)/recommend/intake";
import type { Recommendation, RecommendationResponse } from "@/lib/types";

function recommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    model_key: "luna",
    display_name: "Luna",
    headline: "Use Luna for this",
    why: ["It scored well on similar work."],
    surface: "web",
    surface_label: "Web app",
    surface_rationale: "No integration needed.",
    cost: {
      tier: "paid",
      label: "Paid",
      detail: "$0.20 / $1.20 per Mtok",
      input_usd_per_mtok: 0.2,
      output_usd_per_mtok: 1.2,
    },
    data_residency: "third_party",
    data_residency_label: "Leaves campus",
    prompt_template: "Do the thing.",
    guardrails: [],
    caveats: ["Hold this loosely."],
    receipts: [],
    evidence_score: 0.84,
    verifiable_evidence: true,
    ...overrides,
  };
}

function recommendationResponse(
  overrides: Partial<RecommendationResponse> = {},
): RecommendationResponse {
  return {
    status: "ok",
    message: "Here is what we found.",
    context_summary: [{ label: "Role", value: "Teacher" }],
    gaps: [],
    constraints: [{ label: "Budget", hard: false, detail: "Prefers free tools." }],
    primary: recommendation(),
    alternatives: [recommendation({ model_key: "atlas", display_name: "Atlas", headline: "Or use Atlas" })],
    matched_task_ids: [],
    missing_benchmarks: [],
    what_would_change_this: [],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** No questions means the "Recommend something" button is live immediately. */
async function askAndGetResult(response: RecommendationResponse) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => response,
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<Intake questions={[]} />);
  await fireEvent.click(screen.getByRole("button", { name: /recommend something/i }));
  await screen.findByText(response.primary!.headline);
}

describe("the recommendation result's heading order", () => {
  it("never puts an <h2> after the <h3>s it is meant to introduce", async () => {
    await askAndGetResult(recommendationResponse());

    const headings = screen.getAllByRole("heading");
    const levels = headings.map((heading) => Number(heading.tagName[1]));

    // A heading tree is well-formed when no level skips DOWN by more than one
    // step at a time going deeper, and — the defect this pins — an <h2> must
    // not appear after an <h3> unless something has already returned to <h2>
    // depth. Concretely: once we see the first <h3>, no <h2> should follow.
    const firstH3 = levels.indexOf(3);
    expect(firstH3, "expected at least one <h3> in the result view").toBeGreaterThan(-1);
    const afterFirstH3 = levels.slice(firstH3 + 1);
    expect(
      afterFirstH3.includes(2),
      `an <h2> appeared after the first <h3>: levels were ${levels.join(",")}`,
    ).toBe(false);
  });

  it('renders "Alternatives" as a heading, not a paragraph, once results have real alternatives', async () => {
    await askAndGetResult(recommendationResponse());

    const alternatives = screen.getByText("Alternatives");
    expect(alternatives.tagName).toMatch(/^H[1-6]$/);
  });

  it("omits the Alternatives heading entirely when there are none", async () => {
    await askAndGetResult(recommendationResponse({ alternatives: [] }));

    expect(screen.queryByText("Alternatives")).toBeNull();
  });
});

/**
 * QA-25: pressing "Recommend something" swaps the whole question form out for
 * the result with nothing telling a screen-reader user it happened, and an
 * `ask()` failure rendered with no `role="alert"` — silent on both counts.
 */
describe("the recommendation flow's screen-reader announcements", () => {
  it("moves focus onto the result when it arrives", async () => {
    await askAndGetResult(recommendationResponse());

    const region = screen.getByRole("region", { name: /recommendation result/i });
    expect(document.activeElement).toBe(region);
  });

  it("announces a failed request with role=\"alert\"", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Intake questions={[]} />);
    await fireEvent.click(screen.getByRole("button", { name: /recommend something/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/could not get a recommendation/i);
  });
});
