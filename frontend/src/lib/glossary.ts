/**
 * The plain-language layer: what every word on this site means, in one place.
 *
 * ⚠ WHO THIS IS FOR, PRECISELY. A history professor who has never used a
 * chatbot, does not use AI daily, and has been told to have a position on it.
 * That reader is not a novice at thinking — they are a novice at THIS
 * VOCABULARY, most of which this project invented. The tone that follows from
 * that is warm and matter-of-fact: explain the word, never the reader.
 *
 * ⚠ THE RULE EVERY ENTRY FOLLOWS. `plain` is ONE sentence, and it contains no
 * word that is itself in this file. A definition that reaches for another piece
 * of jargon has not defined anything; it has moved the problem one hop. That
 * rule is enforced by `tests/glossary.test.ts`, not by discipline, because it
 * is exactly the rule that erodes when someone adds a term in a hurry.
 *
 * `more` is where the nuance goes — the second sentence a curious reader gets
 * when they open the card rather than hover it. It is optional, and several of
 * the most important entries use it for the thing the product most needs
 * understood: that a high score with low confidence is not a verdict.
 *
 * ⚠ WHAT IS DELIBERATELY NOT IN HERE. The three use modes have titles and
 * statements that `curriculum/slo.yaml` owns. `lib/trust.ts` documents at
 * length what happened the last time this codebase captioned them from memory
 * (every entry was wrong). So `use-mode` explains what a use mode IS and stops;
 * the three names come from the curriculum at render time, or not at all.
 *
 * Pure data and pure functions — no React — so the wording can be tested as
 * wording, which is the only part of this that can actually be wrong.
 */

export interface GlossaryEntry {
  id: string;
  /** The word as a heading. Sentence case, because this is prose, not a schema. */
  term: string;
  /** One jargon-free sentence. Short enough to live in a hover card. */
  plain: string;
  /** The nuance a reader gets on click. Where "this is not a verdict" lives. */
  more?: string;
}

/**
 * ⚠ ORDER IS MEANINGFUL. The panel renders in this order, and it is a reading
 * order rather than an alphabet: what we measured, how we scored it, how much
 * to trust it, then the plumbing. A reader who gives up a third of the way
 * through has still had the three that matter.
 */
const ENTRIES: GlossaryEntry[] = [
  // ---------------------------------------------------------------- the idea
  {
    id: "learning-outcome",
    term: "Learning outcome",
    plain:
      "A sentence your own department has already published saying what a student who passes should be able to do.",
    more:
      "You may see these abbreviated to SLO, for Student Learning Outcome. We did not write them and we cannot edit them — they are quoted from your programme's own map, which is what makes them a fair yardstick rather than our opinion of what matters.",
  },
  {
    id: "benchmark",
    term: "Benchmark",
    plain:
      "A fixed set of work we give every model, so that comparing two of them is a fair comparison rather than two different exams.",
    more:
      "Ours is built from your programme's published outcomes. Most public benchmarks measure whether a model can write software, which tells a historian nothing.",
  },
  {
    id: "model",
    term: "Model",
    plain:
      "One particular AI system — the thing behind a product name like ChatGPT or Claude, and the thing we actually test.",
    more:
      "Products change which model they run underneath without telling you, which is why we record the exact version we tested and the settings we used.",
  },
  {
    id: "task",
    term: "Task",
    plain:
      "One concrete piece of academic work we ask a model to do, written to test one learning outcome.",
    more:
      "For example: mark this short answer against this marking guide, or work out this break-even figure. Each one is the kind of thing you might actually assign or actually do.",
  },
  {
    id: "use-mode",
    term: "What we are asking of it",
    plain:
      "Each task asks one of three different questions about a model, and a model can be good at one and poor at another.",
    more:
      "Roughly: can it do the work itself, can it help you teach the work, and can it help a student learn the work. Those are three different jobs, and lumping them together is how you get a number that means nothing. Your programme's map defines the three and we quote its wording.",
  },

  // ------------------------------------------------------------- the numbers
  {
    id: "score",
    term: "Score",
    plain:
      "How well a model did on a piece of work, from 0.00 (nothing right) to 1.00 (everything right).",
    more:
      "It is an average across several attempts, not a single lucky answer. Read it next to the confidence beside it: the score says how well it did, and the confidence says how much weight that deserves.",
  },
  {
    id: "overall-score",
    term: "Overall score",
    plain:
      "One model's average across everything it has been measured on, weighted so a piece of work with more attempts behind it counts for more.",
    more:
      "Work that has never been measured is left out entirely — it is never counted as a nought. That means a strong overall score can rest on very little, which is why the number of outcomes and pieces of work behind it are printed right beside it.",
  },
  {
    id: "confidence",
    term: "Confidence",
    plain:
      "How much weight the number beside it can bear — how it was marked, over how many attempts, and whether anything went wrong.",
    more:
      "⚠ This is about the MEASUREMENT, never about the model. A high score with low confidence does not mean the model is good; it means we have not yet earned the right to tell you either way. Treat it as a promising sign that needs more evidence, not as a verdict.",
  },
  {
    id: "verifiable",
    term: "Checked by a program",
    plain:
      "The answer had one right answer, and ordinary software compared what the model said to it. No AI was involved in the marking.",
    more:
      "This is the strongest evidence on the site. It is also only available where the work genuinely has a right answer — a break-even calculation does, an essay does not.",
  },
  {
    id: "judged",
    term: "Marked by another AI",
    plain:
      "The work had no single right answer, so a second AI system marked it against a written marking guide.",
    more:
      "We treat this as an informed second opinion rather than a measurement, and we never label it high confidence. The marking guide and the reasoning are both on the page behind the number, so you can disagree with it specifically.",
  },
  {
    id: "rubric",
    term: "Marking guide",
    plain:
      "The written criteria used to mark work that has no single right answer, with a worked example at each level.",
    more: "Every marked result links to the exact guide used, so the standard being applied is visible rather than assumed.",
  },
  {
    id: "not-measured",
    term: "Not measured yet",
    plain:
      "Nobody has run this test yet, so we have nothing to report — which is different from having tested it and found it wanting.",
    more:
      "Most of this benchmark is in this state today, and we show the gaps rather than filling them. A blank here is an honest blank; it is never shown as a score of nought.",
  },
  {
    id: "sample",
    term: "Attempt",
    plain:
      "One go at one piece of work. We run several, because a single answer can be luck in either direction.",
    more:
      "The two figures beside a score — say 8/10 — are how many attempts produced a mark out of how many we ran. A small number of attempts is a real reason to hold a score loosely.",
  },
  {
    id: "errored-sample",
    term: "Failed attempt",
    plain:
      "An attempt that never produced an answer at all, usually because the service was down or timed out.",
    more:
      "These are excluded from a score rather than counted as nought. An outage must never be able to make a model look incompetent — that would be a fact about our afternoon, not about the model.",
  },

  // ------------------------------------------------------------- the receipts
  {
    id: "run",
    term: "Run",
    plain:
      "One recorded sitting in which a model was given a piece of work, with everything it was asked and everything it said kept on file.",
    more: "Every number on this site links back to the run that produced it. That is what the proof links open.",
  },
  {
    id: "receipt",
    term: "See the proof",
    plain:
      "The link from any number to the complete record behind it: what we asked, what the model answered, how it was marked, and when.",
    more: "If you disagree with a score, this is where you can see exactly what produced it and say precisely where it went wrong.",
  },
  {
    id: "test-stub",
    term: "Test stub",
    plain:
      "A stand-in that returns a fixed answer, used to check our own plumbing works. It is not an AI and it is never recommended.",
    more:
      "It appears on this site because it produced real rows in our records, and quietly deleting inconvenient rows is the habit this project exists to replace. It is always shown outside the ranking.",
  },

  // ----------------------------------------------------------------- the risk
  {
    id: "on-campus",
    term: "On campus, or in the cloud",
    plain:
      "Whether a model runs on the university's own hardware or on a company's computers somewhere else.",
    more:
      "It matters because anything you type into a model in the cloud has left the university. On campus, it has not — which is usually what makes a tool usable with student work at all.",
  },
  {
    id: "ferpa",
    term: "FERPA",
    plain:
      "The federal law governing student education records, which is why a page about AI keeps asking where your data goes.",
    more:
      "In practice it means student work, grades and anything identifying a student need care about where they are sent. If you are unsure, this site treats that as a yes and gives you the cautious answer.",
  },
  {
    id: "de-identify",
    term: "Remove identifying details",
    plain:
      "Stripping names, student numbers and anything else that points at a particular person before the work is sent anywhere.",
    more: "Doing this reliably by hand is harder than it sounds, which is why the safer answer is usually to keep the work on campus instead.",
  },
  {
    id: "guardrail",
    term: "Guardrail",
    plain:
      "A specific thing to do, or not do, that makes a recommendation safe to follow in practice.",
    more: "For example: read every mark before it counts, or never paste anything with a student's name in it.",
  },

  // -------------------------------------------------------------- the plumbing
  {
    id: "prompt",
    term: "Prompt",
    plain: "What you type to an AI — the instruction and any material you give it to work on.",
    more: "Wording changes results more than most people expect, which is why we publish the exact wording behind every number we report.",
  },
  {
    id: "evidence-score",
    term: "Evidence score",
    plain:
      "How well the model we are suggesting actually did on the work most like yours, rather than on the benchmark as a whole.",
    more: "It is the number the recommendation rests on, so it is the one worth opening the proof for.",
  },
  {
    id: "cost",
    term: "Cost",
    plain:
      "What running the work would cost. Models on university hardware are free to you; outside services charge by the amount of text handled.",
  },
  {
    id: "token",
    term: "Token",
    plain:
      "The unit outside services bill by — roughly three quarters of a word, so a page of text is about five hundred of them.",
  },
  {
    id: "lms",
    term: "LMS",
    plain: "The course website your university already runs — Blackboard, Canvas, and the like.",
  },
  {
    id: "api",
    term: "API",
    plain:
      "A way of wiring a model directly into another piece of software, rather than typing into a web page.",
    more: "If nobody on your course is writing code, this is not the option you want, and the recommendation will not push you towards it.",
  },
];

export const GLOSSARY: Record<string, GlossaryEntry> = Object.fromEntries(
  ENTRIES.map((entry) => [entry.id, entry]),
);

/** Every term, in reading order. */
export const GLOSSARY_IDS: readonly string[] = ENTRIES.map((entry) => entry.id);

/**
 * A task kind, in words a first-time reader can act on.
 *
 * ⚠ THE RAW VALUES ARE JARGON AND THEY WERE RENDERED BARE. `TaskKind` is
 * `"verifiable" | "subjective"` — internal vocabulary that leaked into the
 * catalogue's "Evidence" column and into the facet badges, where it told a
 * professor a fact about our taxonomy rather than what to do with the number.
 * "Subjective" is the worse of the two: it reads as "this result is a matter of
 * opinion", when what it actually means is "this work has no single right
 * answer, so a second AI marked it".
 *
 * ⚠ RETURNS PLAIN TEXT, NOT A COMPONENT, because both call sites are inside
 * `.table-scroll`, where an absolutely-positioned definition card is clipped by
 * `overflow-x`. The words have to do the whole job on their own.
 */
export function plainTaskKind(kind: "verifiable" | "subjective"): string {
  return kind === "verifiable" ? "Checked by a program" : "Marked by another AI";
}

export function lookup(id: string): GlossaryEntry | undefined {
  return GLOSSARY[id];
}

/**
 * The entries for a word list, in the order asked for, deduplicated.
 *
 * ⚠ SKIPS UNKNOWN IDS RATHER THAN THROWING. A typo in a page's word list must
 * cost one definition, not the whole page — a glossary that can crash the
 * leaderboard is worse than no glossary. `tests/glossary.test.ts` proves every
 * shipped list resolves, so the skip is a safety net rather than a licence.
 */
export function glossaryFor(ids: readonly string[]): GlossaryEntry[] {
  const seen = new Set<string>();
  const entries: GlossaryEntry[] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    const entry = GLOSSARY[id];
    if (!entry) continue;
    seen.add(id);
    entries.push(entry);
  }
  return entries;
}

/**
 * The `title` string for a term — what a hover gives you before you click.
 *
 * Leads with the word itself because a tooltip appears detached from whatever
 * you were pointing at, and a definition with no subject is a puzzle.
 */
export function tooltip(id: string): string {
  const entry = GLOSSARY[id];
  if (!entry) return "";
  return entry.more ? `${entry.term} — ${entry.plain} ${entry.more}` : `${entry.term} — ${entry.plain}`;
}

/* -------------------------------------------------------------------------- */
/* Per-page word lists                                                        */
/*                                                                            */
/* ⚠ EXPORTED SO THEY CAN BE TESTED. A "?" that opens nothing is worse than no */
/* "?" at all, because it promised help. These lists are what the panel        */
/* renders, and `tests/glossary.test.ts` proves every id in them resolves.     */
/* -------------------------------------------------------------------------- */

export const LEADERBOARD_TERMS = [
  "learning-outcome",
  "score",
  "overall-score",
  "confidence",
  "verifiable",
  "judged",
  "not-measured",
  "sample",
  "errored-sample",
  "task",
  "use-mode",
  "model",
  "on-campus",
  "test-stub",
  "receipt",
] as const;

export const REPORT_CARD_TERMS = [
  "overall-score",
  "score",
  "confidence",
  "verifiable",
  "judged",
  "not-measured",
  "learning-outcome",
  "sample",
  "errored-sample",
  "task",
  "on-campus",
  "receipt",
  "cost",
] as const;

export const RECOMMEND_TERMS = [
  "model",
  "evidence-score",
  "confidence",
  "verifiable",
  "judged",
  "guardrail",
  "on-campus",
  "ferpa",
  "de-identify",
  "prompt",
  "cost",
  "token",
  "lms",
  "api",
  "receipt",
] as const;

export const RUNS_TERMS = [
  "run",
  "task",
  "model",
  "sample",
  "errored-sample",
  "score",
  "not-measured",
  "receipt",
] as const;
