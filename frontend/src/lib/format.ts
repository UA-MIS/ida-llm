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
  return value.toFixed(2);
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
