/**
 * The single place the frontend talks to the API.
 *
 * ONE BASE URL, AND IT IS SERVER-SIDE ONLY. That is not a simplification of a
 * richer design -- it is the only design this deployment permits:
 *
 * - The api has NO INGRESS in any environment (`.devops/components.yaml` gives
 *   the python-app `path: ""`). A browser cannot reach it. Ever.
 * - `NEXT_PUBLIC_*` is inlined into the client bundle at BUILD time, but ONE
 *   frontend image is built and then promoted byte-identically through dev,
 *   staging and prod. A per-environment public API URL is therefore structurally
 *   impossible here, not merely discouraged.
 *
 * So every call runs server-side, against the in-namespace Service name the
 * platform supplies as `API_URL` (`http://ida-llm-api`, no port -- the Service
 * listens on :80). Anything the browser needs goes through a same-origin route
 * handler that proxies here; see src/app/api/runs/[runId]/results/... .
 *
 * `API_BASE_URL` is accepted as a fallback for older local .env files.
 */

import type {
  IntakeQuestion,
  LeaderboardResponse,
  RecommendationResponse,
  RunDetail,
  RunListResponse,
  SampleTranscript,
  TaskDetail,
} from "./types";

const SERVER_BASE =
  process.env.API_URL ?? process.env.API_BASE_URL ?? "http://localhost:8000";

export function apiBase(): string {
  return SERVER_BASE;
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
    // Status 0 means the request never reached the api -- DNS, connection
    // refused, timeout. Callers distinguish it from a real HTTP status; the
    // transcript proxy turns it into a 502, which is what it actually is.
    throw new ApiError(
      `Could not reach the API at ${url}: ${cause instanceof Error ? cause.message : String(cause)}`,
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

/**
 * The results front door.
 *
 * `taskId` narrows to one task; without it every task in the catalog comes
 * back, measured or not. An unbenchmarked task deliberately still appears --
 * dropping it would make "we have not measured this yet" indistinguishable
 * from "this does not exist", and saying the former is half the product.
 */
export function getLeaderboard(params?: {
  taskId?: string;
  family?: string;
  domain?: string;
  /** A Student Learning Outcome id, e.g. `SLO2`. */
  slo?: string;
  /** `capability` today; `assistive`/`instructional` are declared, not in use. */
  useMode?: string;
  /** Only tasks carrying `slo-benchmark` — one filter, the whole benchmark. */
  benchmark?: boolean;
}): Promise<LeaderboardResponse> {
  const query = new URLSearchParams();
  if (params?.taskId) query.set("task_id", params.taskId);
  if (params?.family) query.set("family", params.family);
  if (params?.domain) query.set("domain", params.domain);
  if (params?.slo) query.set("slo", params.slo);
  if (params?.useMode) query.set("use_mode", params.useMode);
  if (params?.benchmark) query.set("benchmark", "true");
  const suffix = query.toString() ? `?${query}` : "";
  return getJson<LeaderboardResponse>(`/leaderboard${suffix}`);
}

/** One full task spec, including each sample's authored `metadata`. */
export function getTask(taskId: string): Promise<TaskDetail> {
  return getJson<TaskDetail>(`/tasks/${taskId}`, 60);
}

/**
 * The intake question tree.
 *
 * Fetched rather than hardcoded here so the questions the form asks and the
 * questions the engine gates on cannot drift apart. Cached briefly: the tree is
 * code-shaped data that changes on deploy, not per request.
 */
export function getIntakeQuestions(): Promise<IntakeQuestion[]> {
  return getJson<IntakeQuestion[]>("/recommend/questions", 60);
}

/**
 * Ask for a recommendation.
 *
 * A refusal ("I still need three things", "no model meets your constraint") is
 * a 200 with a status, not an error -- so this only throws when the API itself
 * failed. Server-side only; the browser reaches it through the same-origin
 * proxy at /api/recommend, for the reasons in this file's header.
 */
export async function postRecommendation(
  answers: Record<string, string>,
): Promise<RecommendationResponse> {
  const url = `${apiBase()}/recommend`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ answers }),
      cache: "no-store",
    });
  } catch (cause) {
    throw new ApiError(
      `Could not reach the API at ${url}: ${cause instanceof Error ? cause.message : String(cause)}`,
      0,
    );
  }
  if (!response.ok) {
    throw new ApiError(
      `POST /recommend failed: ${response.status} ${response.statusText}`,
      response.status,
    );
  }
  return (await response.json()) as RecommendationResponse;
}
