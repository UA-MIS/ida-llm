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

  /**
   * QA-17. `.row-muted`/`.result-card-muted` moved off `opacity` (which
   * dragged every colour below AA together) and onto `background:
   * var(--surface-2)` plus real text tokens — every text token in the
   * palette needs to stay readable there too, not just on `--bg`/`--surface`.
   */
  it.each(TEXT_TOKENS)("--%s meets WCAG AA against the muted-row surface too", (key) => {
    expect(contrastRatio(theme[key]!, theme["surface-2"]!)).toBeGreaterThanOrEqual(AA_NORMAL);
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

  /**
   * QA-26. `--border`/`--border-strong` sit at 1.15–2.16:1 against the page
   * and against a raised `--surface` card — nowhere near WCAG 1.4.11's 3:1
   * floor for a UI component boundary. `--border-control` is the token
   * reserved for a boundary that is the ONLY affordance marking a control (a
   * form input, a button, the glossary term's underline), and it has to clear
   * 3:1 against both backgrounds a bordered control might sit on: the bare
   * page and a card raised above it.
   */
  it("--border-control clears the WCAG 1.4.11 UI-component floor against both the page and a raised surface", () => {
    expect(theme["border-control"], "missing --border-control").toBeDefined();
    expect(contrastRatio(theme["border-control"]!, theme.bg!)).toBeGreaterThanOrEqual(AA_LARGE);
    expect(contrastRatio(theme["border-control"]!, theme.surface!)).toBeGreaterThanOrEqual(
      AA_LARGE,
    );
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

  it("keeps every neutral warm rather than cool or dead grey", () => {
    // ⚠ THIS ASSERTION HAS NOW RUN BOTH WAYS, and the direction is the whole
    // palette decision in one line. It once read `r > b` (warm paper), was
    // inverted to `b > r` when the site unified on a cool-neutral ground, and is
    // inverted BACK here because the human's mockup specifies the warm "Organic"
    // ground. It is a direction check rather than a "not dead grey" one on
    // purpose: a direction-free test would pass for a cool value reintroduced by
    // hand, and that is exactly how a temperature seam creeps back. All eight
    // neutrals, because the cast has to hold in the borders as well as the paper.
    for (const key of NEUTRAL_TOKENS) {
      const { r, b } = parseHex(theme[key]!);
      expect(r, `--${key} is cool or neutral, not warm`).toBeGreaterThan(b);
    }
  });

  it("keeps the correct and incorrect colours apart by hue", () => {
    // ⚠ THE OLD accent-vs-fail / brand-vs-accent HUE GAPS ARE GONE, deliberately.
    // The cool palette kept the interactive accent >90° from the failure red so a
    // link could never share a hue with "low confidence". The warm "Organic"
    // design is monochromatic — accent and brand are both warm by intent — so
    // that gap cannot hold and is not asserted. State is instead carried by SHAPE
    // (the warn tokens, the check/✕ icons) wherever colour would be ambiguous.
    //
    // What still MUST be hue-distinct is the one pairing colour alone is asked to
    // carry: a correct mark (--pass, sage) against an incorrect/low one (--fail,
    // red). Measured as hue, not contrast ratio — in dark mode both are light and
    // their ratio proves nothing; hue is the property actually claimed.
    expect(hueDistance(theme.pass!, theme.fail!)).toBeGreaterThan(60);
    // Accent and brand stay distinct VALUES, so a link reads as different from a
    // structural mark even inside one warm family.
    expect(theme.accent).not.toBe(theme.brand);
  });
});

/**
 * QA-26, continued: the token clearing 3:1 does nothing for a reader unless
 * the controls the audit actually named are wired to it. This pins the wiring
 * itself so a future edit cannot quietly revert one of them back onto
 * `--border`/`--border-strong`, which look identical in a diff that only
 * changes surrounding rules.
 */
describe("controls named in the QA-26 audit use --border-control", () => {
  /** The sheet with comments stripped — a rule quoted in prose is not a rule. */
  const RULES = CSS.replace(/\/\*[\s\S]*?\*\//g, " ");

  const cases: [name: string, pattern: RegExp][] = [
    [".card", /\.card\s*\{[^}]*border:\s*1px solid var\(--border-control\)/],
    [
      ".filter-bar select / input[type=search]",
      /\.filter-bar select,\s*\.filter-bar input\[type="search"\]\s*\{[^}]*border:\s*1px solid var\(--border-control\)/,
    ],
    [".option", /\.option\s*\{[^}]*border:\s*1px solid var\(--border-control\)/],
    [".term (the glossary underline)", /\.term\s*\{[^}]*border-bottom:\s*1px dotted var\(--border-control\)/],
    [".ld-btn-quiet", /\.ld-btn-quiet\s*\{[^}]*border:\s*1px solid var\(--ld-rule-control\)/],
  ];

  it.each(cases)("%s", (_name, pattern) => {
    expect(RULES).toMatch(pattern);
  });
});

/**
 * QA-17. `.row-muted`/`.result-card-muted` used to be one `opacity` line
 * each — the ratios above prove a token-based replacement CAN pass AA, but
 * only wiring the actual rules to it proves it DOES.
 */
describe("the muted-row treatment (QA-17)", () => {
  const RULES = CSS.replace(/\/\*[\s\S]*?\*\//g, " ");

  it("no longer dims muted rows or cards with opacity", () => {
    for (const selector of [".row-muted", ".result-card-muted"]) {
      const match = RULES.match(new RegExp(`${selector.replace(".", "\\.")}\\s*\\{([^}]*)\\}`));
      expect(match, `no ${selector} rule found`).not.toBeNull();
      expect(match![1], `${selector} still uses opacity`).not.toMatch(/opacity\s*:/);
    }
  });

  it("gives both a tone step off the surface and an explicit text colour", () => {
    for (const selector of [".row-muted", ".result-card-muted"]) {
      const pattern = new RegExp(
        `${selector.replace(".", "\\.")}\\s*\\{[^}]*background:\\s*var\\(--surface-2\\)[^}]*color:\\s*var\\(--muted\\)`,
      );
      expect(RULES, `${selector} is missing the surface-2/--muted treatment`).toMatch(pattern);
    }
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
