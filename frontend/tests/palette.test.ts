/**
 * The palette, checked against the real stylesheet.
 *
 * ⚠ THIS TEST READS `globals.css` ITSELF rather than a copy of the values. A
 * test holding its own table of hexes passes forever while the sheet drifts away
 * from it — which is the exact failure this codebase already documents for
 * hardcoded curriculum labels and hardcoded version strings. There is one place
 * the colours live, and this parses that place.
 *
 * The palette is meant to be TUNED (the brief was "the human will tune it on
 * staging"). This is what makes tuning safe: change any token and the assertions
 * below say immediately whether the result is still readable, in both themes,
 * against both the page background and the raised surface.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { AA_LARGE, AA_NORMAL, contrastRatio, parseHex, relativeLuminance } from "@/lib/contrast";

const CSS = readFileSync(
  fileURLToPath(new URL("../src/app/globals.css", import.meta.url)),
  "utf8",
);

/**
 * Pull one `--token: #hex;` declaration out of a block of CSS.
 *
 * Deliberately strict: a token that has been renamed or removed throws here
 * rather than resolving to undefined and skipping its assertions silently.
 */
function tokens(block: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const match of block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    found[match[1]!] = match[2]!;
  }
  return found;
}

/** The light theme is bare `:root`; the dark theme is the one inside the media query. */
function themeBlocks(): { light: string; dark: string } {
  const darkStart = CSS.indexOf("@media (prefers-color-scheme: dark)");
  expect(darkStart).toBeGreaterThan(-1);
  const lightStart = CSS.indexOf(":root {");
  return {
    light: CSS.slice(lightStart, darkStart),
    dark: CSS.slice(darkStart, CSS.indexOf("* { box-sizing")),
  };
}

/**
 * Shortest distance between two hues, in degrees (0–180).
 *
 * Hue is the axis that survives a re-tune: a palette can be lightened or
 * darkened wholesale for a theme without two colours becoming confusable, but
 * two colours at the same hue are confusable at every lightness.
 */
function hueDistance(a: string, b: string): number {
  const delta = Math.abs(hueDegrees(a) - hueDegrees(b));
  return delta > 180 ? 360 - delta : delta;
}

function hueDegrees(hex: string): number {
  const { r, g, b } = parseHex(hex);
  const [rn, gn, bn] = [r / 255, g / 255, b / 255];
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const span = max - min;
  if (span === 0) return 0; // achromatic; no hue to compare
  const raw =
    max === rn
      ? ((gn - bn) / span) % 6
      : max === gn
        ? (bn - rn) / span + 2
        : (rn - gn) / span + 4;
  return (raw * 60 + 360) % 360;
}

const { light, dark } = themeBlocks();
const LIGHT = tokens(light);
const DARK = tokens(dark);

/** Tokens whose whole job is to be read as text somewhere on the site. */
const TEXT_TOKENS = ["fg", "muted", "faint", "accent", "brand", "pass", "fail", "pending"];

/**
 * Every neutral. Checked for a COOL cast — see the test at the bottom of the
 * per-theme block for why this list is longer than the four it used to be.
 */
const NEUTRAL_TOKENS = [
  "bg", "surface", "surface-2", "fg", "muted", "faint", "border", "border-strong",
];

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("%s theme", (_name, theme) => {
  it("defines every token the sheet relies on", () => {
    for (const key of [...new Set([...TEXT_TOKENS, ...NEUTRAL_TOKENS])]) {
      expect(theme[key], `missing --${key}`).toBeDefined();
    }
  });

  it.each(TEXT_TOKENS)("--%s meets WCAG AA against the page background", (key) => {
    expect(contrastRatio(theme[key]!, theme.bg!)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it.each(TEXT_TOKENS)("--%s meets WCAG AA against the raised surface too", (key) => {
    // Half the text on this site sits inside a card, and a token tuned against
    // the page background alone goes unreadable exactly there.
    expect(contrastRatio(theme[key]!, theme.surface!)).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it("separates the raised surfaces from the background by tone", () => {
    // Not a contrast requirement — a legibility one. If surface === bg, every
    // card on the site loses its edge and the page reads as one flat sheet.
    expect(relativeLuminance(theme.surface!)).not.toBeCloseTo(
      relativeLuminance(theme.bg!),
      3,
    );
    expect(relativeLuminance(theme["surface-2"]!)).not.toBeCloseTo(
      relativeLuminance(theme.surface!),
      3,
    );
  });

  it("keeps borders visible without letting them shout", () => {
    // A border nobody can see is a card with no edge; one at text contrast is a
    // page of boxes. AA_LARGE is the non-text floor.
    expect(contrastRatio(theme["border-strong"]!, theme.bg!)).toBeGreaterThanOrEqual(1.2);
    expect(contrastRatio(theme["border-strong"]!, theme.bg!)).toBeLessThan(AA_NORMAL);
  });

  it("uses no pure black and no pure white anywhere", () => {
    // The original complaint survives the warm-to-cool migration unchanged:
    // pure neutrals have no temperature at all, and a page built from them
    // reads as unconsidered. Cool is a temperature; #fff is the absence of one.
    for (const [key, hex] of Object.entries(theme)) {
      const { r, g, b } = parseHex(hex);
      expect([r, g, b], `--${key} is pure white`).not.toEqual([255, 255, 255]);
      expect([r, g, b], `--${key} is pure black`).not.toEqual([0, 0, 0]);
    }
  });

  it("keeps every neutral cool rather than warm or dead grey", () => {
    // ⚠ THIS ASSERTION USED TO RUN THE OTHER WAY, and the inversion is the
    // whole palette-unification change in one line. It read
    // `expect(r).toBeGreaterThan(b)` — every neutral warm — because the tool
    // pages were warm paper. The landing then shipped cool, the warm ground was
    // reviewed as reading BROWN, and the app moved onto the landing's values
    // rather than the other way round.
    //
    // It is INVERTED rather than deleted on purpose: a direction-free "not dead
    // grey" test would pass for a warm value silently reintroduced by hand, and
    // reintroducing one is exactly how the seam comes back. It also covers all
    // eight neutrals now, not the four it used to, because the seam appeared in
    // the borders as readily as in the background.
    for (const key of NEUTRAL_TOKENS) {
      const { r, b } = parseHex(theme[key]!);
      expect(b, `--${key} is warm or neutral, not cool`).toBeGreaterThan(r);
    }
  });

  it("keeps the interactive accent distinguishable from the failure colour", () => {
    // The reason crimson is the BRAND and indigo is the INTERACTIVE accent: a
    // link that shares a hue with "low confidence" undermines the one thing this
    // site is arguing about itself.
    //
    // ⚠ MEASURED AS HUE, NOT AS CONTRAST RATIO. Contrast ratio is a LIGHTNESS
    // comparison, and in dark mode both of these are deliberately light — their
    // ratio is ~1.08 and would be ~1.0 for any well-built dark palette. Asserting
    // on it would mean either a permanently failing test or a threshold tuned
    // down until it proves nothing. Hue separation is the property actually
    // being claimed, so hue is what is measured.
    expect(hueDistance(theme.accent!, theme.fail!)).toBeGreaterThan(90);
    expect(hueDistance(theme.brand!, theme.accent!)).toBeGreaterThan(90);
  });
});

describe("one palette, not two", () => {
  /**
   * ⚠ THE REGRESSION THIS EXISTS TO CATCH IS INVISIBLE. The landing shipped with
   * its own `--ld-*` cool-neutral palette while the tool pages were warm, and
   * the result was a temperature seam on every click-through — a bug nobody
   * sees in a screenshot of either page alone, only in the transition between
   * them. The fix made the landing tokens ALIASES of the canonical ones.
   *
   * Re-forking is a one-line change that looks entirely reasonable in a diff
   * ("just tweak the landing's ink"), and nothing else in this suite would fail.
   * So: the aliases must stay aliases.
   */

  /** The only `--ld-*` tokens allowed to carry their own colour, and why. */
  const LANDING_OWN = new Set([
    "ld-raise",        // a surface ABOVE the page; no tool-page token does that
    "ld-accent-deep",  // pressed state for the one filled button
    "ld-on-accent",    // its foreground
    "ld-pine",         // the single second hue, used on exactly one mark
    "ld-shadow",       // a deeper cast than the tool pages' subtle lift
  ]);

  /**
   * ⚠ A LENGTH IS NOT A COLOUR. `--ld-max` is the landing's maximum width; it
   * has no business in a palette assertion, and adding it to LANDING_OWN would
   * have quietly changed that set's meaning from "allowed to carry its own
   * colour" to "allowed to be anything" — which is the loophole a hex would
   * eventually walk through. Dimensional values are skipped by SHAPE instead,
   * so a colour can never take this exit.
   */
  const DIMENSION = /^-?[\d.]+(rem|px|em|ch|vw|vh|%)$/;

  function landingDeclarations(block: string): [string, string][] {
    return [...block.matchAll(/--(ld-[a-z0-9-]+):\s*([^;]+);/g)]
      .map((m): [string, string] => [m[1]!, m[2]!.trim()])
      .filter(([, value]) => !DIMENSION.test(value));
  }

  it.each([
    ["light", light],
    ["dark", dark],
  ])("%s: every shared landing token resolves to a canonical one", (_name, block) => {
    for (const [token, value] of landingDeclarations(block)) {
      if (LANDING_OWN.has(token)) continue;
      expect(value, `--${token} forks the palette instead of aliasing it`).toMatch(
        /^var\(--[a-z0-9-]+\)$/,
      );
    }
  });

  it("does not let a colour escape through the dimension exemption", () => {
    // The detector, checked against the mistake it must not permit.
    expect(DIMENSION.test("84rem")).toBe(true);
    expect(DIMENSION.test("#fbfcfd")).toBe(false);
    expect(DIMENSION.test("rgba(0, 0, 0, 0.5)")).toBe(false);
  });

  it("keeps the landing's own tokens to the documented few", () => {
    // A new `--ld-*` hex is how a second palette grows back one token at a time.
    for (const [token, value] of landingDeclarations(light)) {
      if (value.startsWith("var(")) continue;
      expect(LANDING_OWN, `undocumented landing colour --${token}`).toContain(token);
    }
  });

  it("leaves no warm token anywhere in the sheet", () => {
    // The literal goal of the unification, stated as a value check: the old warm
    // palette's exact hexes must not survive anywhere, in a token or a comment.
    const RETIRED_WARM = [
      "#fbf9f6", "#f3efea", "#eae4dc", "#1f1c1a", "#6e6862",
      "#e6dfd6", "#d2c8bb", "#191714", "#211e1b", "#2a2622",
      "#ede7df", "#a69d93", "#322e2a", "#474139",
    ];
    const declarations = CSS.replace(/\/\*[\s\S]*?\*\//g, " ");
    for (const hex of RETIRED_WARM) {
      expect(declarations.toLowerCase(), `retired warm value ${hex} is still declared`)
        .not.toContain(hex);
    }
  });
});

describe("every colour comes from a token", () => {
  /** The sheet with its comments removed — a hex inside prose is not a colour. */
  function rulesOnly(): string {
    const body = CSS.slice(CSS.indexOf("* { box-sizing"));
    return body.replace(/\/\*[\s\S]*?\*\//g, " ");
  }

  it("declares no colour literal outside the two token blocks", () => {
    // ⚠ THIS IS THE ONE THAT ACTUALLY CAUGHT SOMETHING. The filled-button rule
    // carried `color: #fff`, typed in back when --accent was dark in both
    // themes. Warming the palette gave dark mode a LIGHT indigo accent, and that
    // literal silently became white-on-light-indigo at roughly 1.5:1.
    //
    // No token-level assertion can see it: the value is not a token, so every
    // contrast check in this file passed while a real control was unreadable.
    // The rule that catches it is structural — if a colour is not a token, the
    // palette does not actually control it, and no amount of tuning on staging
    // will fix it.
    const literals = rulesOnly().match(/#[0-9a-fA-F]{3,8}\b|\brgba?\([^)]*\)/g) ?? [];
    expect(literals).toEqual([]);
  });

  it("would notice a colour typed straight into a rule", () => {
    // The detector, checked against a sample of the exact mistake — so this
    // suite cannot pass by failing to look.
    const sample = "* { box-sizing: border-box; } button { color: #fff; }";
    expect(sample.match(/#[0-9a-fA-F]{3,8}\b/g)).toEqual(["#fff"]);
    // …and is not fooled by a hex mentioned in a comment.
    const commented = "* { box-sizing: border-box; } /* not #fff, ever */ a { color: var(--accent); }";
    expect(commented.replace(/\/\*[\s\S]*?\*\//g, " ").match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
  });
});

describe("contrast arithmetic", () => {
  it("agrees with the WCAG reference extremes", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#777777", "#ffffff")).toBeCloseTo(4.48, 1);
    expect(contrastRatio("#abc", "#aabbcc")).toBeCloseTo(1, 10);
  });

  it("is symmetric", () => {
    expect(contrastRatio("#2f4c8a", "#fbf9f6")).toBeCloseTo(
      contrastRatio("#fbf9f6", "#2f4c8a"),
      10,
    );
  });

  it("rejects a value that is not a colour rather than treating it as black", () => {
    expect(() => parseHex("var(--accent)")).toThrow();
    expect(() => parseHex("#12345")).toThrow();
  });

  it("exposes the AA thresholds it is checked against", () => {
    expect(AA_NORMAL).toBe(4.5);
    expect(AA_LARGE).toBe(3);
  });
});
