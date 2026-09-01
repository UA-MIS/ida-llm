/**
 * The register, as a test.
 *
 * ⚠ THIS IS THE ONLY GUARD ON A DIFF MADE ENTIRELY OF WORDS. A voice pass has
 * no compiler and no type to break: every sentence cut here could be typed back
 * in tomorrow and everything would still build, lint and pass. It also comes
 * back the way it left — one sentence at a time, each of them locally
 * reasonable — which is exactly the failure a sweep catches and a reviewer does
 * not.
 *
 * The reader these are measured against is the one PR #67 named: a professor,
 * an expert who does not need the page narrated to them, and for whom the sound
 * of us proving we are careful actively undercuts the evidence that we are.
 *
 * Three classes, and they fail for different reasons:
 *
 *   META_NARRATION — the page announcing what it is about to do, or telling the
 *     reader how to read. Spends attention before saying anything.
 *   DEFENSIVE — copy whose job is to prove our own good character rather than
 *     state the method. The receipts already prove it; saying it out loud reads
 *     as someone who expects not to be believed.
 *   SHELF_LIFE — a hardcoded quantity that was true the day it was written and
 *     silently false later. `/overview` had one ("Most of this benchmark has not
 *     been run yet"); it turned out to have three siblings, on three surfaces.
 *
 * ⚠ EVERY PATTERN HERE IS A SENTENCE THAT WAS ACTUALLY ON THE SITE. This is not
 * a style opinion applied to hypothetical copy — the list is the diff. Adding a
 * pattern for prose nobody ever wrote makes the sweep a lint nobody trusts.
 *
 * `tests/overview.dom.test.tsx` keeps its own inline copy of the tics from #67;
 * it is narrower than this list and still green, so it is left alone.
 */

export const META_NARRATION: readonly RegExp[] = [
  /here is the short version/i,
  /the short version/i,
  /read this first/i,
  /only if you want to/i,
  /they are not small print/i,
  /rather than fill this page/i,
  /where would you like to/i,
  /if you would rather just be told/i,
  /if you read nothing else/i,
  /want the detail\?/i,
  /new here\?/i,
  /what do these words mean/i,
  /in plain english/i,
  /here is how to read it/i,
];

export const DEFENSIVE: readonly RegExp[] = [
  /we would rather/i,
  /we will not invent/i,
  /as loudly as/i,
  /not meant to keep anyone out/i,
  /is not a poor result/i,
  /rather than show you a placeholder/i,
];

/**
 * ⚠ NOT "MOST OF THIS BENCHMARK IS UNMEASURED", WHICH IS STILL TRUE TODAY. The
 * defect is stating a PROPORTION in fixed text at all: it needs no code change
 * to become a lie, and nothing anywhere counts the day it turns. Say the rule,
 * or render the count — both are already done, in the trust block and in the
 * coverage line respectively.
 */
export const SHELF_LIFE: readonly RegExp[] = [/most of this benchmark/i];

/** Every class at once, which is how a page should be swept. */
export function expectPeerVoice(
  body: string,
  expect: (actual: unknown, message?: string) => { not: { toMatch(re: RegExp): void } },
): void {
  for (const tic of META_NARRATION) {
    expect(body, `meta-narration is back: ${tic}`).not.toMatch(tic);
  }
  for (const tic of DEFENSIVE) {
    expect(body, `defensive copy is back: ${tic}`).not.toMatch(tic);
  }
  for (const tic of SHELF_LIFE) {
    expect(body, `a claim with a shelf life is back: ${tic}`).not.toMatch(tic);
  }
}
