/**
 * The plain-language layer, pinned.
 *
 * ⚠ WHAT THIS FILE IS ACTUALLY DEFENDING. The glossary exists for one reader:
 * a professor who has never used a chatbot and has been handed a page full of
 * words this project invented. Every failure mode below is a way that reader
 * silently gets a worse experience while the page still renders fine — which is
 * exactly the class of bug no build step catches:
 *
 *   1. A definition that uses jargon to define jargon ("the SLO rollup's
 *      confidence tier"). It reads as an explanation and explains nothing.
 *   2. A term referenced from a page that has no entry, so the "?" is a dead
 *      affordance — worse than no affordance, because it promises help.
 *   3. A definition that quietly grows into a paragraph, at which point nobody
 *      reads it and the hover card covers the table underneath.
 *   4. A hardcoded caption for something the CURRICULUM owns, which is the
 *      exact mistake `lib/trust.ts` documents at length.
 */

import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  GLOSSARY,
  GLOSSARY_IDS,
  LEADERBOARD_TERMS,
  RECOMMEND_TERMS,
  REPORT_CARD_TERMS,
  RUNS_TERMS,
  glossaryFor,
  lookup,
  plainTaskKind,
  tooltip,
} from "@/lib/glossary";

/**
 * ⚠ WHY NOT JUST `GLOSSARY[id]`. The project compiles with
 * `noUncheckedIndexedAccess`, so indexing a `Record` yields `T | undefined`
 * even for a key taken straight out of `GLOSSARY_IDS`. Asserting the entry
 * exists ONCE, here, keeps that fact in one place and makes a genuinely missing
 * entry fail with the id in the message rather than with "possibly undefined".
 */
function entryFor(id: string) {
  const entry = GLOSSARY[id];
  if (!entry) throw new Error(`no glossary entry for "${id}"`);
  return entry;
}

/**
 * Words a definition may not contain, because they are the very things a
 * first-time reader cannot decode. Each maps to the entry that is allowed to
 * say it — the entry that DEFINES the word obviously has to name it.
 */
const JARGON: Record<string, string[]> = {
  SLO: ["learning-outcome"],
  LLM: [],
  API: ["api"],
  FERPA: ["ferpa", "on-campus"],
  LMS: ["lms"],
  token: ["token", "cost"],
  rubric: ["rubric", "judged"],
  rollup: [],
  aggregate: [],
  "de-identif": ["de-identify"],
};

describe("the glossary as a whole", () => {
  it("keys every entry by its own id, so a lookup cannot return the wrong term", () => {
    for (const id of GLOSSARY_IDS) {
      expect(entryFor(id).id).toBe(id);
    }
  });

  it("gives every term a display name and a plain definition", () => {
    for (const id of GLOSSARY_IDS) {
      const entry = entryFor(id);
      expect(entry.term.length, `${id} has no display term`).toBeGreaterThan(0);
      expect(entry.plain.length, `${id} has no definition`).toBeGreaterThan(0);
    }
  });

  it("writes every definition as a finished sentence", () => {
    for (const id of GLOSSARY_IDS) {
      expect(entryFor(id).plain, `${id} does not end in a full stop`).toMatch(/[.!?]$/);
    }
  });

  /**
   * The hover card sits on top of a table. A definition long enough to need
   * scrolling is one nobody reads, and it hides the number it was explaining.
   */
  it("keeps the first sentence short enough to read in a hover card", () => {
    for (const id of GLOSSARY_IDS) {
      expect(entryFor(id).plain.length, `${id} is too long for a tooltip`).toBeLessThan(220);
    }
  });

  it("never defines jargon with more jargon", () => {
    for (const id of GLOSSARY_IDS) {
      const entry = entryFor(id);
      const body = `${entry.plain} ${entry.more ?? ""}`;
      for (const [word, allowed] of Object.entries(JARGON)) {
        if (allowed.includes(id)) continue;
        expect(
          body.toLowerCase().includes(word.toLowerCase()),
          `${id} uses the undefined term "${word}" in its own definition`,
        ).toBe(false);
      }
    }
  });

  /**
   * ⚠ THE MISTAKE `lib/trust.ts` DOCUMENTS. An earlier version of this codebase
   * carried a hardcoded map of use-mode labels, invented before the vocabulary
   * existed, and every entry in it was wrong. `curriculum/slo.yaml` is the
   * authority for those three titles. The glossary is allowed to explain what a
   * use mode IS; it is not allowed to name the three.
   */
  it("never hardcodes the curriculum's own use-mode titles", () => {
    const forbidden = ["capability", "instructional", "assistive"];
    for (const id of GLOSSARY_IDS) {
      const entry = entryFor(id);
      const body = `${entry.term} ${entry.plain} ${entry.more ?? ""}`;
      for (const word of forbidden) {
        expect(
          body.toLowerCase().includes(word),
          `${id} hardcodes the curriculum-owned mode name "${word}"`,
        ).toBe(false);
      }
    }
  });
});

describe("lookup", () => {
  it("finds a term by id", () => {
    expect(lookup("confidence")?.term).toBeTruthy();
  });

  it("returns undefined for a term nobody has written yet", () => {
    expect(lookup("not-a-real-term")).toBeUndefined();
  });
});

describe("glossaryFor", () => {
  it("returns the requested entries in the order asked for", () => {
    const entries = glossaryFor(["score", "confidence"]);
    expect(entries.map((entry) => entry.id)).toEqual(["score", "confidence"]);
  });

  /**
   * A panel that throws on an unknown id would take a whole page down over a
   * typo in a word list. Skipping is the honest degradation: one definition
   * missing, and the test below is what stops that shipping.
   */
  it("skips ids with no entry rather than throwing", () => {
    expect(glossaryFor(["score", "nope"]).map((entry) => entry.id)).toEqual(["score"]);
  });

  it("drops duplicates so a panel cannot list the same word twice", () => {
    expect(glossaryFor(["score", "score"]).map((entry) => entry.id)).toEqual(["score"]);
  });
});

describe("tooltip", () => {
  it("reads as a definition, leading with the word being defined", () => {
    const verifiable = entryFor("verifiable");
    const text = tooltip("verifiable");
    expect(text.startsWith(verifiable.term)).toBe(true);
    expect(text).toContain(verifiable.plain);
  });

  it("says nothing rather than something wrong for an unknown term", () => {
    expect(tooltip("not-a-real-term")).toBe("");
  });
});

/**
 * ⚠ THE DEAD-AFFORDANCE GUARD. Every page's word list is exported so this file
 * can prove each id resolves. Without it, renaming an entry leaves a "?" that
 * opens nothing, and the page still builds, lints and renders.
 */
describe("the per-page word lists", () => {
  const LISTS: Record<string, readonly string[]> = {
    LEADERBOARD_TERMS,
    REPORT_CARD_TERMS,
    RECOMMEND_TERMS,
    RUNS_TERMS,
  };

  for (const [name, ids] of Object.entries(LISTS)) {
    it(`${name} references only terms that exist`, () => {
      for (const id of ids) {
        expect(lookup(id), `${name} references missing term "${id}"`).toBeDefined();
      }
    });

    it(`${name} is not empty`, () => {
      expect(ids.length).toBeGreaterThan(0);
    });

    it(`${name} lists no term twice`, () => {
      expect(new Set(ids).size).toBe(ids.length);
    });
  }

  /**
   * The four words the whole product turns on. A page that shows scores without
   * explaining what a score is, or shows confidence without explaining that a
   * low-confidence high score is not a verdict, has failed the reader this
   * layer exists for.
   */
  it("explains the load-bearing words wherever numbers appear", () => {
    for (const ids of [LEADERBOARD_TERMS, REPORT_CARD_TERMS]) {
      for (const required of ["score", "confidence", "verifiable", "judged", "not-measured"]) {
        expect(ids).toContain(required);
      }
    }
  });
});

/**
 * ⚠ A REGRESSION GUARD FOR A BUG THAT SHIPPED IN THIS BRANCH AND WAS CAUGHT BY
 * LOOKING AT THE PAGE, NOT BY ANY TEST.
 *
 * `.term` is `all: unset` on purpose: the WORD has to take on the type around
 * it, or an inline definition stops looking like part of its sentence. But
 * `unset` resolves inherited properties to `inherit` — and several of the right
 * places for a term are small-caps labels (`.podium-label`, `.filter-bar
 * label`, `.grid dt`, every `th`). Inside one of those, the definition CARD
 * rendered in full uppercase with letter-spacing: present, technically correct,
 * and completely unreadable.
 *
 * That is this layer's own failure mode — an explanation that does not explain
 * — so it gets a test rather than a comment.
 */
describe("the definition card's styling", () => {
  const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
  const card = css.slice(css.indexOf(".term-card {"), css.indexOf(".term:hover .term-card"));

  it("exists as a rule at all", () => {
    expect(card.length).toBeGreaterThan(0);
  });

  it.each(["text-transform: none", "letter-spacing: normal", "font-style: normal"])(
    "resets inherited %s, so a term inside a small-caps label stays readable",
    (declaration) => {
      expect(card).toContain(declaration);
    },
  );
});

describe("plainTaskKind", () => {
  it("says what was done to the work, not what we call the category", () => {
    expect(plainTaskKind("verifiable")).toBe("Checked by a program");
    expect(plainTaskKind("subjective")).toBe("Marked by another AI");
  });

  /**
   * ⚠ "SUBJECTIVE" IS THE ONE THAT ACTIVELY MISLEADS. To a reader outside this
   * project it says "this result is a matter of opinion", when what it means is
   * "this work has no single right answer, so a second AI marked it against a
   * guide". Leaking either raw value into the interface is the bug.
   */
  it("never leaks the raw taxonomy word", () => {
    for (const kind of ["verifiable", "subjective"] as const) {
      expect(plainTaskKind(kind).toLowerCase()).not.toContain(kind);
    }
  });

  /**
   * The two labels are the plain-English half of the two glossary entries a
   * reader will have met elsewhere. If they drift apart, the same distinction
   * is being drawn in two different vocabularies on one page.
   */
  it("matches the glossary entries for the same distinction", () => {
    expect(plainTaskKind("verifiable")).toBe(entryFor("verifiable").term);
    expect(plainTaskKind("subjective")).toBe(entryFor("judged").term);
  });
});
