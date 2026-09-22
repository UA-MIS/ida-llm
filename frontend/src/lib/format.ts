/**
 * Display helpers.
 *
 * The rule these all encode: **null is not zero.** A run with `mean_score:
 * null` has not been scored (it is subjective, or every sample errored).
 * Rendering that as `0.00` would read as "this model failed", which is a
 * different and false claim. Every formatter here returns an em-dash or an
 * explicit label for null rather than a number.
 */

export function formatScore(value: number | null): string {
  if (value === null) return "—";
  return formatScoreValue(value);
}

/** Course exploration uses whole scores out of 100, preserving the ceiling rule. */
export function formatScore100(value: number | null): string {
  return value === null ? "—" : String(Math.round(Number(formatScoreValue(value)) * 100));
}

/**
 * A score, to two places — and **never rounded up into a perfect 1.00**.
 *
 * ⚠ THE ONE ASYMMETRY IN THIS FILE, AND IT IS DELIBERATE. `toFixed(2)` rounds
 * to nearest, which is right everywhere except at the ceiling: it turned a
 * measured 0.9958 into the front door's headline "1.00", a perfect score on a
 * benchmark that did not measure one. To a sceptical reader "1.00" reads as
 * either fabricated or as "the AI is flawless at this" — and neither is what
 * the data says. A benchmark must not be able to print a result it did not get.
 *
 * So: round as normal, then refuse the ceiling. A value below 1 floors to 0.99
 * rather than rounding to 1.00; only an exact 1 prints as 1.00.
 *
 * ⚠ NOT MIRRORED AT THE BOTTOM, ON PURPOSE. Rendering 0.001 as "0.00" rounds
 * *against* the model, which is the conservative direction — the direction this
 * whole file already leans. It is the flattering rounding that has to be
 * refused, not every rounding.
 *
 * ⚠ THE RULE LIVES HERE, NOT AT A CALL SITE. It was a one-line bug in
 * `lib/specimen.ts` that shipped it, and a second `toFixed(2)` somewhere else
 * would ship it again. Every score in the product renders through this.
 */
export function formatScoreValue(value: number): string {
  const rounded = value.toFixed(2);
  if (value < 1 && Number(rounded) >= 1) {
    return (Math.floor(value * 100) / 100).toFixed(2);
  }
  return rounded;
}

export function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return `${(value * 100).toFixed(0)}%`;
}

export function formatCost(usd: number): string {
  if (usd === 0) return "free";
  if (usd < 0.01) return `<$0.01`;
  return `$${usd.toFixed(2)}`;
}

export function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatDuration(
  startedAt: string | null,
  finishedAt: string | null,
): string {
  if (!startedAt || !finishedAt) return "—";
  const ms = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  if (Number.isNaN(ms) || ms < 0) return "—";
  return formatLatency(ms);
}

export function shortSha(sha: string | null): string {
  if (!sha) return "—";
  return sha.slice(0, 7);
}

const FULL_SHA = /^[0-9a-f]{40}$/;

/**
 * Render `run.harness_version` — the build that executed the run.
 *
 * ⚠ THIS FIELD CHANGED SHAPE, AND BOTH SHAPES ARE LIVE. It used to be a
 * hardcoded `"0.1.0"` that no release step ever wrote to, so it identified
 * nothing while looking like it did. It now carries the build's git SHA, or the
 * honest string `"unknown"` when the build cannot be identified. Rows written
 * before that change keep their old literal — nobody can know today which build
 * produced them, and inventing one would replace a visible lie with an invisible
 * one — so the UI has to read both.
 *
 * A SHA is abbreviated like the other two SHAs on this page (the full value goes
 * in the `title`); anything else is shown verbatim, because a `"0.1.0"` or an
 * `"unknown"` truncated to seven characters would be actively misleading.
 *
 * No `v` prefix: it used to render as `v{harness_version}`, which turns a commit
 * SHA into `v1a2b3c4` — a version string that does not exist.
 */
export function formatBuildIdentity(value: string | null): string {
  if (!value) return "—";
  return FULL_SHA.test(value) ? value.slice(0, 7) : value;
}
