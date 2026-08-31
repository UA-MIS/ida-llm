/**
 * What the stylesheet is allowed to delete at a narrow width.
 *
 * ⚠ A CSS TEST, BECAUSE THIS DEFECT LIVES NOWHERE ELSE. Every rendered-DOM test
 * in this suite runs in jsdom, which applies no stylesheet — so a `display:
 * none` in a media query is invisible to all of them. That is precisely how a
 * phone came to show "0.88" where a desktop showed "0.88 · Low confidence",
 * with the whole suite green: the data was right, the markup was right, and a
 * breakpoint deleted the half of the claim that qualified it.
 *
 * ⚠ THE RULE BEING PINNED. Cost, task counts, sample counts and outcome counts
 * are columns a phone can lose — they are detail. Confidence is not detail; it
 * is the difference between a reading and a verdict, and this product's stated
 * rule is that every number keeps its trust tell. A narrow screen gets a
 * compacted tell, never no tell.
 *
 * The parallel test in `matrix.test.ts` reads this same file for the ramp
 * contrast, for the same reason: some claims are only checkable against the
 * real stylesheet.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  fileURLToPath(new URL("../src/app/globals.css", import.meta.url)),
  "utf8",
);

/** Every `@media` block's body, so a rule can be checked for where it lives. */
function mediaBlocks(css: string): string[] {
  const blocks: string[] = [];
  const re = /@media[^{]*\{/g;
  while (re.exec(css) !== null) {
    let depth = 1;
    let i = re.lastIndex;
    while (i < css.length && depth > 0) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") depth--;
      i++;
    }
    blocks.push(css.slice(re.lastIndex, i - 1));
  }
  return blocks;
}

describe("the confidence tell is never dropped at a breakpoint", () => {
  it("declares no rule that hides a .col-trust cell", () => {
    expect(CSS).not.toMatch(/\.col-trust[^{}]*\{[^}]*display:\s*none/);
  });

  it("does not hide .col-trust inside any media query", () => {
    for (const block of mediaBlocks(CSS)) {
      const hidesTrust = /\.col-trust[^{}]*\{[^}]*display:\s*none/.test(block);
      expect(hidesTrust, "a media query hides the trust column").toBe(false);
    }
  });

  it("does not hide the podium's confidence at any width", () => {
    // The podium is the visual layer most readers actually look at. Its pips
    // used to be deleted below 760px alongside the rank number, on the stated
    // grounds that "the confidence is restated on the model's own page" — which
    // was false, because that page hid it under `.col-optional` at the very
    // same breakpoint.
    expect(CSS).not.toMatch(/\.podium-confidence[^{}]*\{[^}]*display:\s*none/);
    expect(CSS).not.toMatch(/\.podium-rank,\s*\.podium-confidence\s*\{\s*display:\s*none/);
  });

  it("still drops the columns that ARE optional, so the fix cost nothing in width", () => {
    // The trade this fix depends on: Cost, Tasks, Samples and Outcomes go, and
    // confidence stays. If `.col-optional` ever stopped being dropped, the
    // narrow layout would be carrying every column again.
    const dropsOptional = mediaBlocks(CSS).some((block) =>
      /\.col-optional\s*\{\s*display:\s*none/.test(block),
    );
    expect(dropsOptional).toBe(true);
  });
});

describe("only .table-scroll scrolls sideways", () => {
  it("keeps the invariant the stylesheet states in its own comment", () => {
    expect(CSS).toMatch(/\.table-scroll\s*\{[^}]*overflow-x:\s*auto/);
  });
});

describe("the quoted outcome statement is not indented off a phone", () => {
  it("resets the blockquote margin the browser supplies", () => {
    // `.ld p { margin: 0 }` reset paragraphs and nothing reset this one, so the
    // user agent's `margin: 1em 40px` left 247px of a 375px screen for the
    // element the landing page calls its credibility claim.
    // Matched loosely: the rule carries an explanatory comment that itself
    // contains braces, so a `[^}]*` window would stop short of the declaration.
    const rule = CSS.slice(CSS.indexOf(".ld-slo {"));
    expect(rule.slice(0, rule.indexOf("\n}"))).toMatch(/margin:\s*1em\s+0\s*;/);
  });
});
