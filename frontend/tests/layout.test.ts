/**
 * Page width, checked against the stylesheet.
 *
 * ⚠ THE BUG THIS EXISTS TO PREVENT SHIPPED, AND NOBODY NOTICED FOR THREE
 * SECTIONS. `main { max-width }` was declared three times — 1080px in the
 * skeleton, 1140px in Dashboard v1, 1180px in the redesign — each added by a
 * later section without removing the one above it. Only the last had any
 * effect, so two of the three carried comments explaining a width the browser
 * never used, and the app quietly rendered narrower than any of them intended.
 *
 * A duplicate max-width does not fail a build, a type check, or a render test.
 * It just makes the site the wrong width, which is what the user reported.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  fileURLToPath(new URL("../src/app/globals.css", import.meta.url)),
  "utf8",
);

/** The sheet with comments stripped — a rule quoted in prose is not a rule. */
const RULES = CSS.replace(/\/\*[\s\S]*?\*\//g, " ");

describe("the page container", () => {
  it("sets main's max-width exactly once", () => {
    const declarations = [...RULES.matchAll(/\bmain\s*\{[^}]*?max-width\s*:/g)];
    expect(
      declarations.length,
      "more than one `main { max-width }` — only the last one will apply",
    ).toBe(1);
  });

  it("takes that width from a token rather than a literal", () => {
    // A literal here is how the third one got added: it reads as a local tweak
    // rather than as a change to the site's width.
    expect(RULES).toMatch(/\bmain\s*\{[^}]*max-width:\s*var\(--page-max\)/);
  });

  it("is wide enough for the tables the site is mostly made of", () => {
    const [, value] = RULES.match(/--page-max:\s*([^;]+);/)!;
    const rem = Number(value!.trim().replace("rem", ""));
    // 1180px (73.75rem) was the old effective cap and was reported as using a
    // middle third of the screen. Anything at or below it is a regression.
    expect(rem).toBeGreaterThan(73.75);
  });

  it("keeps the landing's prose inside a readable measure", () => {
    // ⚠ THE ONE WIDTH THAT MUST NOT BE SOLVED BY MAKING IT BIGGER. Filling the
    // viewport with a single 200-character line is not a fix for empty margins;
    // the wide sections below are. Typographic practice puts the readable band
    // at roughly 45–85 characters.
    const measures = [...RULES.matchAll(/grid-template-columns:[^;]*?(\d+)ch/g)]
      .map((m) => Number(m[1]));
    expect(measures.length).toBeGreaterThan(0);
    for (const ch of measures) {
      expect(ch, `${ch}ch is outside the readable band`).toBeLessThanOrEqual(85);
      expect(ch, `${ch}ch is too narrow to fill a line`).toBeGreaterThanOrEqual(45);
    }
  });

  it("gives the landing a wide variant for its non-prose sections", () => {
    // This is what actually fills the screen. If it disappears, the prose
    // measure is all that is left and the skinny-column report comes back.
    expect(RULES).toContain(".ld-grid-wide");
    expect(RULES).toMatch(/\.ld-grid-wide\s*\{[^}]*minmax\(0,\s*1fr\)/);
  });
});
