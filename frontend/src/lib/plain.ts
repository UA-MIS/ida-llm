/**
 * The last translation layer before an API sentence reaches a professor.
 *
 * ⚠ WHY THIS FILE EXISTS. The API writes one string for two readers. A caveat
 * like "no judge model is configured for this deployment (set
 * IDA_JUDGE_MODEL_KEY to a key in models.yaml)" is exactly right for whoever is
 * on call, and it was rendering verbatim on 228 professor-facing result cards.
 * An environment variable name on a results page does not just fail to inform —
 * it tells the reader this page was not written for them, on the one product
 * whose entire argument is that it was.
 *
 * The proper fix is upstream: the API should emit an operator diagnostic and a
 * reader caveat as two fields. This is the frontend holding the line until it
 * does, and it should keep holding it afterwards — a page that renders whatever
 * arrives will leak the next config key too.
 *
 * ⚠ TWO LAYERS, AND THE ORDER MATTERS. First, whole known sentences are
 * replaced wholesale, because a good reader-facing sentence is not a
 * word-for-word swap of an operator one — it says a different, shorter thing.
 * Then a set of last-resort scrubs runs over whatever is left, so a phrasing
 * this file has never seen still cannot print a config key or an internal noun.
 *
 * ⚠ NOTHING HERE INVENTS A FACT. Every replacement below says the same thing as
 * the string it replaces, minus the vocabulary. Where the operator sentence
 * carries a real qualification ("the transcripts are archived, so it can be
 * graded later"), the plain one carries it too — dropping it would be a
 * different and worse defect than the jargon.
 */

/**
 * Whole sentences we recognise, replaced with what a professor needs to know.
 *
 * Matched loosely in the middle (`[\s\S]*?`) so a wording tweak upstream does
 * not silently fall through to the scrubs — the distinctive opening and closing
 * clauses are what anchor them.
 */
const KNOWN_SENTENCES: { match: RegExp; plain: string }[] = [
  {
    // trust.py: a score exists on a task this deployment calls unscorable.
    match:
      /This run carries a score, but the platform cannot grade this task today[\s\S]*?would not reproduce it\.?/g,
    plain:
      "This score was produced while the AI marker was switched on. It is switched off in this deployment now, so this number cannot be re-checked until somebody turns it back on. Everything the model wrote was kept, so it can be re-marked then.",
  },
  {
    // harness runner.py: the same fact arriving on its own, as a reason.
    match:
      /subjective task: scoring it needs an LLM judge[\s\S]*?once one is\.?/g,
    plain:
      "This kind of work has no single right answer, so a second AI has to mark it — and no marker is switched on in this deployment. Everything the model wrote was kept, so it can be marked later.",
  },
];

/**
 * Last-resort scrubs.
 *
 * These fire on strings the list above did not recognise. They are deliberately
 * blunt: a slightly clumsy sentence is a far smaller failure than a printed
 * environment variable, and the clumsiness is a signal that a sentence needs
 * adding above.
 */
const SCRUBS: { match: RegExp; plain: string }[] = [
  // The parenthetical instruction to an operator, removed whole — a reader has
  // no setting to set, so there is nothing here for them to act on.
  { match: /\s*\(set [A-Z][A-Z0-9_]* to a key in [\w.]+\)/g, plain: "" },
  { match: /\s*\([A-Z][A-Z0-9_]* is unset\)/g, plain: "" },
  { match: /\bIDA_[A-Z0-9_]+\b/g, plain: "a setting an administrator controls" },
  { match: /\bmodels\.yaml\b/g, plain: "the model registry" },
  { match: /\bslo\.yaml\b/g, plain: "the curriculum map" },
  { match: /\bLLM-as-judge scoring\b/g, plain: "marking by a second AI" },
  { match: /\bLLM-as-judge\b/g, plain: "marking by a second AI" },
  { match: /\ban LLM judge\b/g, plain: "a second AI marker" },
  { match: /\bLLM judge\b/g, plain: "AI marker" },
  { match: /\bjudge model\b/g, plain: "AI marker" },
  { match: /\bthe walking skeleton\b/g, plain: "this early version" },
  { match: /\bwalking skeleton\b/g, plain: "early version" },
  { match: /\bmake lint-tasks\b/g, plain: "the task validator" },
];

/**
 * `4 sample(s)` → `4 samples`, `1 sample(s)` → `1 sample`.
 *
 * The parenthetical plural is a Python-side convenience that reads as unfinished
 * on a page where everything else pluralises properly. The count is right there
 * in the string, so there is nothing to guess.
 */
const PARENTHETICAL_PLURAL = /(\d+)\s+([A-Za-z]+)\(s\)/g;

function fixPlurals(text: string): string {
  return text.replace(PARENTHETICAL_PLURAL, (_whole, count: string, noun: string) =>
    Number(count) === 1 ? `${count} ${noun}` : `${count} ${noun}s`,
  );
}

/** Tidy the seams a removed parenthetical leaves behind. */
function tidy(text: string): string {
  return text
    .replace(/\(\s*\)/g, "")
    .replace(/\s+([,.;])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/**
 * Turn one API sentence into one a professor can read.
 *
 * Idempotent: running it over already-plain text changes nothing, which is what
 * makes it safe to apply at every render rather than at one chosen boundary.
 */
export function plainLanguage(text: string): string {
  let out = text;
  for (const { match, plain } of KNOWN_SENTENCES) out = out.replace(match, plain);
  for (const { match, plain } of SCRUBS) out = out.replace(match, plain);
  return tidy(fixPlurals(out));
}

/** The same, over a list — the shape `TrustTell.caveats` arrives in. */
export function plainCaveats(caveats: readonly string[]): string[] {
  return caveats.map(plainLanguage).filter((caveat) => caveat.length > 0);
}

/**
 * Whether a string still carries vocabulary a reader has no use for.
 *
 * Exported for the test that guards this file: the point is not that these
 * particular patterns are gone, it is that no professor-facing string carries
 * an identifier, a filename or a build command at all.
 */
export const OPERATOR_VOCABULARY: RegExp =
  /\b(IDA_[A-Z0-9_]+|[a-z_]+\.yaml|make [a-z-]+|LLM[- ]as[- ]judge|walking skeleton)\b/;
