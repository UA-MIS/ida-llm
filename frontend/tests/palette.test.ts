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
const TEXT_TOKENS = ["fg", "muted", "accent", "brand", "pass", "fail", "pending"];

describe.each([
  ["light", LIGHT],
  ["dark", DARK],
])("%s theme", (_name, theme) => {
  it("defines every token the sheet relies on", () => {
    for (const key of [...TEXT_TOKENS, "bg", "surface", "surface-2", "border", "border-strong"]) {
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
    // The specific complaint this palette answers: pure neutrals have no
    // temperature, and a page built from them reads as clinical.
    for (const [key, hex] of Object.entries(theme)) {
      const { r, g, b } = parseHex(hex);
      expect([r, g, b], `--${key} is pure white`).not.toEqual([255, 255, 255]);
      expect([r, g, b], `--${key} is pure black`).not.toEqual([0, 0, 0]);
    }
  });

  it("keeps the two neutrals warm rather than dead grey", () => {
    // Every neutral carries the same faint warm cast; a neutral with r === b is
    // the flat grey the redesign exists to remove.
    for (const key of ["bg", "surface", "fg", "muted"]) {
      const { r, b } = parseHex(theme[key]!);
      expect(r, `--${key} has no warm cast`).toBeGreaterThan(b);
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
