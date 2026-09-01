/**
 * The overview page, RENDERED — the claims a pure test cannot see.
 *
 * ⚠ EVERY RULE IN `lib/overview.ts` IS ALREADY UNIT-TESTED, AND THAT IS NOT
 * ENOUGH. The failures this suite exists for are all of the same shape: the
 * rule was right and the page did not honour it. A confidence tell computed and
 * never drawn. A demonstration-data notice returned by the module and rendered
 * nowhere. A door wired to a route that does not exist. Every one of those ships
 * with `overview.test.ts` green.
 *
 * This page is also the one where such a failure costs the most: it is a
 * candidate front door, most of its readers will never click through, and what
 * it shows them IS the product.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { board, result, task } from "./fixtures";
import type { ModelResult } from "@/lib/types";

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

const { default: OverviewPage } = await import("@/app/overview/page");

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const USAGE = { prompt_tokens: 4200, completion_tokens: 2600 };

function model(key: string, score: number, overrides: Partial<ModelResult> = {}): ModelResult {
  return result({
    model_key: key,
    display_name: key.toUpperCase(),
    mean_score: score,
    run_id: `run_${key}`,
    usage: USAGE,
    ...overrides,
  });
}

function boardOf(results: ModelResult[]) {
  return board([
    task({ task_id: "slo2/a", slo: "SLO2", results, has_results: results.length > 0 }),
    task({
      task_id: "slo4/a",
      slo: "SLO4",
      family: "slo4",
      results: results.map((r) => ({ ...r, mean_score: (r.mean_score ?? 0) - 0.2 })),
      has_results: results.length > 0,
    }),
  ]);
}

async function renderWith(response: unknown) {
  getLeaderboard.mockResolvedValue(response);
  render(await OverviewPage());
}

/* ------------------------------------------------------------- the hook */

describe("the read a visitor actually gets", () => {
  it("names the standouts and what each is strongest at", async () => {
    await renderWith(boardOf([model("luna", 0.9), model("vega", 0.7)]));

    const cards = document.querySelectorAll(".ov-card");
    expect(cards.length, "no standout cards rendered").toBeGreaterThan(0);
    // The hook has to be explanative: the SUBJECT, not just a rank — and in the
    // programme's own words rather than its filing code.
    expect(document.body.textContent).toContain("Quantitative Literacy");
  });

  it("never puts our internal filing language in the one sentence", () => {
    // ⚠ THIS SHIPPED, AND ONLY A REAL RENDER CAUGHT IT. `rollupByOutcome` ends
    // with an "Outside the SLO benchmark" bucket for tasks with no outcome
    // attached. It is a fine row on a report card and gibberish in a headline:
    // live, against real data, the front door read "Luna is at its strongest on
    // Outside the SLO benchmark". Every fixture in the unit suite tags its
    // tasks, so nothing there could see it.
    const untagged = board([
      task({ task_id: "demo/x", slo: null, results: [model("luna", 0.9)], has_results: true }),
    ]);
    return renderWith(untagged).then(() => {
      const card = document.querySelector(".ov-card");
      expect(card).not.toBeNull();
      expect(card!.textContent).not.toContain("Outside the SLO benchmark");
      expect(card!.textContent).not.toContain("SLO");
      // It still says something true about the model, rather than going blank.
      expect(card!.textContent).toContain("across the work we set it");
    });
  });

  it("puts the read above the doors, not below them", async () => {
    await renderWith(boardOf([model("luna", 0.9), model("vega", 0.7)]));

    const headline = document.querySelector(".ov-headline");
    const doors = document.querySelector(".ov-doors");
    expect(headline).not.toBeNull();
    expect(doors).not.toBeNull();
    // DOCUMENT_POSITION_FOLLOWING === 4: the doors come after the reading.
    expect(headline!.compareDocumentPosition(doors!) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("renders no number without the confidence that qualifies it", async () => {
    // ⚠ THE RULE THE WHOLE PRODUCT STANDS ON. A score that loses its tell does
    // not become a weaker claim; it becomes a stronger one than the evidence
    // supports.
    await renderWith(boardOf([model("luna", 0.9), model("vega", 0.7)]));

    for (const card of document.querySelectorAll(".ov-card")) {
      expect(
        card.querySelector(".ov-score-figure"),
        "a card with no score figure",
      ).not.toBeNull();
      expect(
        card.querySelector(".ov-confidence"),
        `${card.querySelector(".ov-name")?.textContent} shows a score with no confidence`,
      ).not.toBeNull();
    }
  });
});

/* ------------------------------------------------------------ the money */

describe("the value axis", () => {
  it("shows a per-answer price drawn from the rate card", async () => {
    await renderWith(boardOf([model("luna", 0.9), model("vega", 0.7)]));

    const prices = document.querySelectorAll(".ov-price");
    expect(prices.length).toBeGreaterThan(0);
    expect(document.body.textContent).toMatch(/per 100 answers/);
  });

  it("never prints a zero price for a model that bills", async () => {
    // ⚠ THE BUG THIS PAGE IS MOST LIKELY TO SHIP. Our own recorded spend is 0
    // on seeded data; a page deriving cost from it would render "$0.00" beside
    // a paid model and call it free.
    await renderWith(
      boardOf([
        model("luna", 0.9, {
          total_cost_usd: 0,
          usage: { prompt_tokens: 0, completion_tokens: 0 },
        }),
      ]),
    );

    const price = document.querySelector(".ov-price");
    expect(price).not.toBeNull();
    expect(price!.textContent).not.toContain("$0.00");
    expect(price!.textContent).toMatch(/Not priced/);
  });

  it("calls a campus model free rather than cheap", async () => {
    await renderWith(
      boardOf([
        model("sparks", 0.9, {
          data_residency: "on_campus",
          price: {
            tier: "campus_hosted",
            label: "Free to you — runs on campus hardware",
            detail: "No per-use charge.",
            input_usd_per_mtok: 0,
            output_usd_per_mtok: 0,
          },
        }),
      ]),
    );

    expect(document.querySelector(".ov-price-free")).not.toBeNull();
    expect(document.body.textContent).toMatch(/campus hardware/);
  });
});

/* --------------------------------------------------------- the honesty */

describe("the honesty layer", () => {
  it("shows the demonstration-data notice when the data is seeded", async () => {
    await renderWith(boardOf([model("luna", 0.9, { demonstration: true })]));

    const notice = document.querySelector(".ov-demo-notice");
    expect(notice, "seeded data rendered with no disclosure").not.toBeNull();
    expect(notice!.textContent!.toLowerCase()).toMatch(/illustrat/);
  });

  it("puts that notice above the numbers it qualifies", async () => {
    // A disclosure a reader meets after forming an impression has disclosed
    // nothing.
    await renderWith(boardOf([model("luna", 0.9, { demonstration: true })]));

    const notice = document.querySelector(".ov-demo-notice")!;
    const card = document.querySelector(".ov-card")!;
    expect(notice.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("shows no such notice when the data is real", async () => {
    await renderWith(boardOf([model("luna", 0.9)]));
    expect(document.querySelector(".ov-demo-notice")).toBeNull();
  });

  it("always carries the your-field-may-differ nudge", async () => {
    await renderWith(boardOf([model("luna", 0.9), model("vega", 0.7)]));

    const nudge = document.querySelector(".ov-nudge");
    expect(nudge, "no scope nudge — the average reads as a verdict").not.toBeNull();
    expect(nudge!.textContent!.toLowerCase()).toMatch(/your|subject|course/);
  });

  it("renders the caveats rather than hiding them behind a toggle", async () => {
    await renderWith(boardOf([model("luna", 0.9), model("vega", 0.7)]));

    const caveats = document.querySelectorAll(".ov-caveats li");
    expect(caveats.length).toBeGreaterThan(0);
  });

  it("never shows a test stub as a standout", async () => {
    await renderWith(
      boardOf([
        model("mock", 1.0, {
          display_name: "Mock model",
          recommendable: false,
          data_residency: "not_a_real_model",
        }),
        model("luna", 0.8),
      ]),
    );

    for (const card of document.querySelectorAll(".ov-card")) {
      expect(card.textContent).not.toContain("Mock model");
    }
  });
});

/* ------------------------------------------------------- the copy itself */

describe("the words, as a professor meets them", () => {
  it("names the model in the report-card link with no stray punctuation seam", async () => {
    // ⚠ REPORTED FROM A REAL RENDER AS "Luna (…) 's full report card". The link
    // used to read `See {display_name}&rsquo;s …`, gluing an apostrophe onto an
    // interpolated name — one reflow of that JSX puts the name and the
    // apostrophe on separate lines and JSX inserts a space between them. The
    // possessive is gone, so the seam cannot reopen; this fails if it returns.
    await renderWith(boardOf([model("luna", 0.9, { display_name: "Luna (Llama 3.1 8B)" })]));

    const link = document.querySelector(".ov-card-link")!;
    const text = link.textContent!;
    expect(text).toContain("Luna (Llama 3.1 8B)");
    expect(text, "a space landed before punctuation").not.toMatch(/\s+['\u2019,.]/);
    expect(text, "doubled whitespace in the link").not.toMatch(/\s\s/);
  });

  it("counts the coverage claim rather than asserting one that rots", async () => {
    // ⚠ THE PAGE USED TO SAY "Most of this benchmark has not been run yet" in
    // fixed text — true the day it was written and false the day coverage
    // passes half, with nothing to catch the turn. The claim now comes from the
    // same counts the coverage line renders.
    await renderWith(boardOf([model("luna", 0.9), model("vega", 0.7)]));

    const trust = document.querySelector(".ld-trust")!;
    expect(trust.textContent).not.toMatch(/most of this benchmark/i);

    const coverage = document.querySelector(".ov-coverage")!.textContent!;
    const counts = coverage.match(/(\d+) of the (\d+)/);
    expect(counts, "coverage line no longer states a count").not.toBeNull();
    expect(trust.textContent).toContain(`${counts![1]} of the ${counts![2]} outcomes`);
  });

  it("still states the coverage rule when there is no reading to count", async () => {
    // The trust block renders with the API down, so the dynamic sentence needs
    // a branch that claims nothing rather than printing "undefined of the".
    getLeaderboard.mockRejectedValue(new Error("connection refused"));
    render(await OverviewPage());

    const trust = document.querySelector(".ld-trust")!;
    expect(trust.textContent).not.toMatch(/undefined|NaN/);
    expect(trust.textContent).toContain("Nothing unmeasured is counted as a zero");
  });

  it("does not narrate itself to the reader", async () => {
    // The register is a colleague handing over findings, not a guide explaining
    // what the page is about to do. These are the tics that were cut; a
    // regression would be someone adding them back one sentence at a time.
    await renderWith(boardOf([model("luna", 0.9), model("vega", 0.7)]));

    const body = document.body.textContent!;
    for (const tic of [
      /here is the short version/i,
      /the short version/i,
      /read this first/i,
      /only if you want to/i,
      /they are not small print/i,
      /rather than fill this page/i,
      /where would you like to go/i,
    ]) {
      expect(body, `meta-narration is back: ${tic}`).not.toMatch(tic);
    }
  });
});

/* ------------------------------------------------------------ the doors */

describe("the three doors", () => {
  it("offers all three, each to a route that exists", async () => {
    await renderWith(boardOf([model("luna", 0.9)]));

    const doors = document.querySelector(".ov-doors")!;
    const hrefs = [...doors.querySelectorAll("a")].map((a) => a.getAttribute("href"));

    expect(hrefs).toContain("/recommend");
    expect(hrefs).toContain("/leaderboard");
    expect(hrefs).toContain("/compare");
  });

  it("labels each door by what the reader gets, not by our jargon", async () => {
    await renderWith(boardOf([model("luna", 0.9)]));

    const doors = within(document.querySelector(".ov-doors") as HTMLElement);
    expect(doors.getByText(/recommendation for what you actually do/i)).toBeTruthy();
    expect(doors.getByText(/what we actually tested/i)).toBeTruthy();
    expect(doors.getByText(/outcome you care about/i)).toBeTruthy();
  });
});

/* ------------------------------------------------------- degraded states */

describe("degrading honestly", () => {
  it("still opens when the API is unreachable", async () => {
    // ⚠ A FRONT DOOR THAT WILL NOT OPEN IS SHOWN TO THE VISITOR LEAST WILLING
    // TO TRY AGAIN. The reading needs the API; the argument and the doors do
    // not, and they must survive without it.
    getLeaderboard.mockRejectedValue(new Error("connection refused"));
    render(await OverviewPage());

    expect(document.querySelector(".ov-headline-down")).not.toBeNull();
    expect(document.querySelector(".ov-doors")).not.toBeNull();
    expect(screen.getByText(/what we actually tested/i)).toBeTruthy();
  });

  it("says nothing is measured rather than rendering an empty frame", async () => {
    await renderWith(board([task()]));

    expect(document.querySelectorAll(".ov-card")).toHaveLength(0);
    expect(document.querySelector(".ov-headline")!.textContent).toBeTruthy();
    // And the doors are still there — an empty benchmark is exactly when the
    // recommendation walkthrough is the most useful thing on the page.
    expect(document.querySelector(".ov-doors")).not.toBeNull();
  });

  it("does not imply a contest when only one model was measured", async () => {
    await renderWith(boardOf([model("luna", 0.9)]));

    const cards = document.querySelectorAll(".ov-card");
    expect(cards).toHaveLength(1);
    expect(cards[0]!.querySelector(".ov-role")!.textContent!.toLowerCase()).not.toMatch(
      /strongest|best|ahead/,
    );
    // With one row there is nothing to set against anything, so the strip that
    // exists to show a trade-off must not render at all.
    expect(document.querySelector(".ov-tradeoff")).toBeNull();
  });
});
