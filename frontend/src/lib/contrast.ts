/**
 * WCAG contrast arithmetic, so the palette can be tuned without being guessed at.
 *
 * ⚠ WHY THIS IS CODE AND NOT A NOTE IN THE CSS. The palette in `globals.css` is
 * explicitly meant to be adjusted — the brief for it was "the human will tune it
 * on staging". A palette that anyone is invited to edit needs a way to fail
 * loudly when an edit makes text unreadable, and "it looked fine on my monitor"
 * is not that: the two people most likely to miss a 3.9:1 body text are the
 * person who chose the colour and the person reviewing the diff.
 *
 * So the numbers are computed, `tests/palette.test.ts` asserts them against the
 * real stylesheet, and a tweak that breaks AA fails CI rather than shipping.
 *
 * Straight out of WCAG 2.1: sRGB channels are linearised, weighted into a
 * relative luminance, and compared as (lighter + 0.05) / (darker + 0.05).
 */

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

/** Parse `#rgb` or `#rrggbb`. Throws on anything else — a silently-zero colour
 *  would make every contrast check pass against black. */
export function parseHex(hex: string): Rgb {
  const value = hex.trim().replace(/^#/, "");
  const full =
    value.length === 3
      ? value
          .split("")
          .map((c) => c + c)
          .join("")
      : value;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) {
    throw new Error(`Not a hex colour: ${hex}`);
  }
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  };
}

function channel(value: number): number {
  const s = value / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

/** WCAG relative luminance, 0 (black) to 1 (white). */
export function relativeLuminance(color: Rgb | string): number {
  const { r, g, b } = typeof color === "string" ? parseHex(color) : color;
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** Contrast ratio between two colours, 1 (identical) to 21 (black on white). */
export function contrastRatio(a: Rgb | string, b: Rgb | string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const [light, dark] = la >= lb ? [la, lb] : [lb, la];
  return (light + 0.05) / (dark + 0.05);
}

/** WCAG AA for body text. */
export const AA_NORMAL = 4.5;
/** WCAG AA for large/bold text, and the floor for non-text UI boundaries. */
export const AA_LARGE = 3;
