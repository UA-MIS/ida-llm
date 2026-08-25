/**
 * The single place the frontend talks to the API.
 *
 * Two base URLs, deliberately:
 *
 * - `API_BASE_URL` — used by React Server Components. In the cluster that is
 *   the in-namespace Service DNS name (`http://api:8000`), which is not
 *   resolvable from a browser.
 * - `NEXT_PUBLIC_API_BASE_URL` — used by client components. This is the public
 *   ingress hostname and is inlined into the browser bundle at build time.
 *
 * Collapsing these into one variable is the classic Next.js-in-k8s bug: it
 * works locally, where both happen to be `localhost`, and breaks on deploy.
 */

import type { RunDetail, RunListResponse, SampleTranscript } from "./types";

const SERVER_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
const BROWSER_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** True inside a React Server Component / route handler. */
const isServer = typeof window === "undefined";

export function apiBase(): string {
  return isServer ? SERVER_BASE : BROWSER_BASE;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, revalidateSeconds = 0): Promise<T> {
  const url = `${apiBase()}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { Accept: "application/json" },
      // Runs change while you watch them, so never serve a cached list.
      next: revalidateSeconds > 0 ? { revalidate: revalidateSeconds } : undefined,
      cache: revalidateSeconds > 0 ? undefined : "no-store",
    });
  } catch (cause) {
    throw new ApiError(
      `Could not reach the API at ${url}. Is it running? (\`make dev\`)`,
      0,
    );
  }
  if (!response.ok) {
    throw new ApiError(
      `GET ${path} failed: ${response.status} ${response.statusText}`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

export function listRuns(limit = 50): Promise<RunListResponse> {
  return getJson<RunListResponse>(`/runs?limit=${limit}`);
}

export function getRun(runId: string): Promise<RunDetail> {
  return getJson<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
}

export function getTranscript(
  runId: string,
  sampleId: string,
): Promise<SampleTranscript> {
  return getJson<SampleTranscript>(
    `/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(sampleId)}/transcript`,
  );
}
