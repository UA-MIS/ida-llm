"use client";

/**
 * Error boundary for the whole app.
 *
 * The common failure in the skeleton is "the API is not running", so that gets
 * an explicit, actionable message rather than a generic stack trace.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="notice notice-error">
      <h2 style={{ marginTop: 0 }}>Something went wrong</h2>
      <p className="mono">{error.message}</p>
      <p className="muted">
        If the API is not reachable, start the stack with <code>make dev</code>{" "}
        and reload.
      </p>
      <button onClick={reset}>Try again</button>
    </div>
  );
}
