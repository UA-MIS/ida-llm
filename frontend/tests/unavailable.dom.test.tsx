/**
 * What a professor sees when the API is down.
 *
 * ⚠ THE FAILURE THIS PREVENTS IS A SOCIAL ONE, NOT A TECHNICAL ONE. An outage
 * is going to happen; the question is what it does to a reader who has been
 * persuaded, once, to give an AI benchmark ten minutes. A raw 500 with a stack
 * trace tells that reader "this whole thing is broken and probably always was"
 * — and they do not come back. The same outage behind a calm sentence tells
 * them "come back in a minute", which is both kinder and truer.
 *
 * So these tests are about WORDS as much as behaviour:
 *
 *   1. The page must not throw. A thrown error reaches the boundary, and the
 *      boundary is the alarming thing.
 *   2. The visible prose must contain no stack trace, no status code, and none
 *      of the vocabulary that reads as catastrophe.
 *   3. It must not over-reassure either. We cannot see the database from here,
 *      so we do not get to promise the data is fine — only that this is our
 *      problem and usually temporary.
 *   4. The technical detail must still be one click away, because an operator
 *      loading the same page needs it and hiding it entirely would trade one
 *      reader's comfort for another's blindness.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const getLeaderboard = vi.hoisted(() => vi.fn());
class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
vi.mock("@/lib/api", () => ({ getLeaderboard, ApiError }));

const { ResultsUnavailable } = await import("@/components/service-unavailable");
const { default: LeaderboardPage } = await import("@/app/(site)/leaderboard/page");
const { default: ComparePage } = await import("@/app/(site)/compare/page");
const { default: AppError } = await import("@/app/error");

/** The words that make an outage read as a catastrophe. */
const ALARMING = [
  "500",
  "internal server error",
  "stack",
  "exception",
  "traceback",
  "fatal",
  "crash",
  "ECONNREFUSED",
];

/**
 * ⚠ REASSURANCE WE HAVE NOT EARNED. If the API is unreachable we cannot see the
 * database either, so "your data is safe" / "nothing is lost" would be a claim
 * made from no evidence — on a site whose entire argument is that it does not
 * do that. Being unable to check is exactly when the temptation is strongest.
 */
const OVERCLAIMS = ["nothing is lost", "your data is safe", "data is safe", "unaffected"];

function visibleText(root: HTMLElement | Document = document): string {
  // Everything except what is tucked inside the technical disclosure.
  const clone = (root instanceof Document ? root.body : root).cloneNode(true) as HTMLElement;
  clone.querySelectorAll("details .unavailable-detail").forEach((node) => node.remove());
  return clone.textContent ?? "";
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the fallback itself", () => {
  function renderFallback() {
    render(
      <ResultsUnavailable
        what="the benchmark results"
        retryHref="/leaderboard"
        cause={new ApiError("Could not reach the API at http://ida-llm-api/leaderboard: ECONNREFUSED", 0)}
      />,
    );
  }

  it("leads with a calm, plain sentence rather than an error", () => {
    renderFallback();
    expect(screen.getByRole("heading").textContent).toMatch(/temporarily unavailable/i);
  });

  it("uses none of the vocabulary that reads as catastrophe", () => {
    renderFallback();
    const text = visibleText().toLowerCase();
    for (const word of ALARMING) {
      expect(text, `the fallback says "${word}" to a professor`).not.toContain(
        word.toLowerCase(),
      );
    }
  });

  it("tells the reader it is not their fault", () => {
    renderFallback();
    expect(visibleText()).toMatch(/our end|nothing you did|not (something )?you/i);
  });

  it("says what to do, and offers somewhere that still works", () => {
    renderFallback();
    expect(visibleText()).toMatch(/try again/i);
    const hrefs = Array.from(document.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("/leaderboard"); // retry
    expect(hrefs).toContain("/"); // the landing page degrades gracefully on its own
  });

  it("promises nothing about the data it cannot see", () => {
    renderFallback();
    const text = visibleText().toLowerCase();
    for (const claim of OVERCLAIMS) {
      expect(text, `the fallback claims "${claim}" while unable to check`).not.toContain(claim);
    }
  });

  /**
   * Hiding the cause outright would make the page useless to the person who can
   * actually fix it. It goes behind a closed disclosure: invisible to a
   * professor, one click from an operator.
   */
  it("keeps the technical cause available but closed", () => {
    renderFallback();
    const details = document.querySelector<HTMLDetailsElement>(".unavailable details");
    expect(details, "no technical disclosure at all").not.toBeNull();
    expect(details!.open).toBe(false);
    expect(details!.textContent).toContain("ECONNREFUSED");
  });

  it("survives an error it cannot read", () => {
    render(<ResultsUnavailable what="the results" retryHref="/leaderboard" cause={undefined} />);
    expect(screen.getByRole("heading").textContent).toMatch(/temporarily unavailable/i);
  });
});

describe("/leaderboard when the API is down", () => {
  it("does not throw", async () => {
    getLeaderboard.mockRejectedValue(new ApiError("GET /leaderboard failed: 503", 503));
    await expect(LeaderboardPage({ searchParams: Promise.resolve({}) })).resolves.toBeTruthy();
  });

  it("shows the calm fallback instead of the ranking", async () => {
    getLeaderboard.mockRejectedValue(new ApiError("GET /leaderboard failed: 503", 503));
    render(await LeaderboardPage({ searchParams: Promise.resolve({}) }));

    expect(document.querySelector(".unavailable")).not.toBeNull();
    expect(document.querySelector("table.leaderboard")).toBeNull();
    expect(document.querySelector(".plain-summary")).toBeNull();
  });

  it("leaks no status code into the prose", async () => {
    getLeaderboard.mockRejectedValue(new ApiError("GET /leaderboard failed: 503", 503));
    render(await LeaderboardPage({ searchParams: Promise.resolve({}) }));
    expect(visibleText()).not.toContain("503");
  });
});

describe("/compare when the API is down", () => {
  it("does not throw", async () => {
    getLeaderboard.mockRejectedValue(new ApiError("Could not reach the API", 0));
    await expect(ComparePage()).resolves.toBeTruthy();
  });

  it("shows the calm fallback instead of the grid", async () => {
    getLeaderboard.mockRejectedValue(new ApiError("Could not reach the API", 0));
    render(await ComparePage());

    expect(document.querySelector(".unavailable")).not.toBeNull();
    expect(document.querySelector(".cg-grid")).toBeNull();
  });

  /**
   * ⚠ THE MORE VISIBLE CASE. `/compare` is in the nav, so it is a click away
   * from the front door for a reader who has just decided to trust this.
   */
  it("uses none of the alarming vocabulary either", async () => {
    getLeaderboard.mockRejectedValue(new ApiError("Could not reach the API", 0));
    render(await ComparePage());
    const text = visibleText().toLowerCase();
    for (const word of ALARMING) expect(text).not.toContain(word.toLowerCase());
  });
});

/**
 * ⚠ AN OUTAGE IS NOT AN EMPTY BENCHMARK, AND THE TWO MUST NOT LOOK ALIKE.
 * "We have not measured this yet" is a finding this project is proud of.
 * "We cannot reach the results right now" is a fault. Rendering the outage as
 * the empty state would quietly tell a professor the benchmark is emptier than
 * it is — which is the same class of lie as inventing a number, pointing the
 * other way.
 */
describe("an outage and an empty benchmark are told apart", () => {
  it("does not reuse the 'nothing measured yet' copy for a failure", async () => {
    getLeaderboard.mockRejectedValue(new ApiError("GET /leaderboard failed: 503", 503));
    render(await LeaderboardPage({ searchParams: Promise.resolve({}) }));

    expect(screen.queryByText(/No benchmark results yet/i)).toBeNull();
    expect(visibleText()).not.toMatch(/not (been )?measured (against|yet)/i);
  });
});

/**
 * ⚠ THE BOUNDARY IS WHERE EVERY OTHER ROUTE STILL LANDS. `/leaderboard` and
 * `/compare` catch their own failures now, but `/runs`, `/models/<key>` and
 * `/recommend` do not — so this file is the one that decides what a professor
 * sees when any of those breaks. It used to print `error.message` in monospace
 * over an instruction to run `make dev`.
 */
describe("the global error boundary", () => {
  function renderBoundary() {
    render(
      <AppError
        error={Object.assign(new Error("Internal Server Error stack trace here"), {
          digest: "abc123",
        })}
        reset={() => {}}
      />,
    );
  }

  it("speaks in the same calm register as the page-level fallback", () => {
    renderBoundary();
    expect(screen.getByRole("heading").textContent).toMatch(/temporarily unavailable/i);
    expect(visibleText()).toMatch(/our end|nothing you did/i);
  });

  it("keeps the raw message out of the visible prose", () => {
    renderBoundary();
    const text = visibleText().toLowerCase();
    for (const word of ALARMING) expect(text).not.toContain(word.toLowerCase());
  });

  /**
   * The digest is the only string that finds this failure in the server logs.
   * It is useless to a professor and essential to whoever is paged, which is
   * exactly what the disclosure is for.
   */
  it("still carries the message and digest for whoever is on call", () => {
    renderBoundary();
    const details = document.querySelector<HTMLDetailsElement>(".unavailable-cause");
    expect(details!.open).toBe(false);
    expect(details!.textContent).toContain("abc123");
    expect(details!.textContent).toContain("Internal Server Error");
  });

  it("offers a retry that actually re-renders the segment", () => {
    const reset = vi.fn();
    render(<AppError error={new Error("boom")} reset={reset} />);
    screen.getByRole("button", { name: /try again/i }).click();
    expect(reset).toHaveBeenCalled();
  });
});
