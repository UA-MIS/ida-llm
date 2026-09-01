/**
 * QA-33. The "best measured score" star was a non-focusable `<span title=…>`
 * with no other accessible text — its ENTIRE content was the glyph "★", so
 * the site's one crown was reachable to a sighted mouse user only. Same
 * `aria-hidden` glyph + `.sr-only` label pattern `compare/page.tsx`'s `Cell`
 * already uses for its empty-state glyphs.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ModelResultCard } from "@/components/model-result-card";

import { result } from "./fixtures";

afterEach(cleanup);

describe("the best-on-task star", () => {
  it("carries its meaning in text an assistive technology can read, not just in title", () => {
    const { container } = render(
      <ModelResultCard result={result()} rank={1} isBest />,
    );
    const star = container.querySelector(".star")!;
    expect(star, "no .star rendered for the best result").not.toBeNull();

    const glyph = star.querySelector('[aria-hidden="true"]');
    expect(glyph?.textContent).toBe("★");

    const srOnly = star.querySelector(".sr-only");
    expect(srOnly, "the star has no accessible text of its own").not.toBeNull();
    expect(srOnly!.textContent).toMatch(/best measured score/i);
  });

  it("renders a plain rank number, not a star, when this result is not the best", () => {
    const { container } = render(
      <ModelResultCard result={result()} rank={2} isBest={false} />,
    );
    expect(container.querySelector(".star")).toBeNull();
    expect(container.querySelector(".rank")?.textContent).toBe("2");
  });
});

/**
 * D-92: this card is the finest-grained place `ModelResult.demonstration`
 * ever reaches a reader — a single task, a single model, a single row. It is
 * reached by drilling into a task on `/leaderboard`, where the seeded number
 * used to render exactly like a real one.
 */
describe("the demonstration-data tell", () => {
  it("flags a seeded result", () => {
    const { container } = render(
      <ModelResultCard result={result({ demonstration: true })} rank={1} isBest={false} />,
    );
    expect(
      container.querySelector(".badge-demo"),
      "a seeded result carries no demonstration tell",
    ).not.toBeNull();
  });

  it("never flags a result that was actually measured", () => {
    const { container } = render(
      <ModelResultCard result={result({ demonstration: false })} rank={1} isBest={false} />,
    );
    expect(
      container.querySelector(".badge-demo"),
      "a real measurement was labelled illustrative",
    ).toBeNull();
  });
});
