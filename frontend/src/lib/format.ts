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
