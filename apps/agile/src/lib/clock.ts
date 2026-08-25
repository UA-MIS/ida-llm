/**
 * Server-side clock reads.
 *
 * Kept out of component bodies on purpose: reading the clock during a React
 * render is impure, and a value derived in the browser can disagree with the
 * server and cause a hydration mismatch. Server components call this and pass
 * the result down as a prop, so "now" is decided once, on the server.
 */
export function serverNow(): number {
  return Date.now();
}

/** Today as YYYY-MM-DD, for date-only comparisons. */
export function serverToday(): string {
  return new Date().toISOString().slice(0, 10);
}
