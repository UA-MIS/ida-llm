/**
 * TypeScript mirrors of the `ida_core.contracts` pydantic models.
 *
 * These are hand-written on purpose for the skeleton: the surface is small and
 * a generator would be one more thing to keep running. The moment this drifts
 * from the API, generate them instead --
 *   `npx openapi-typescript http://localhost:8000/openapi.json -o lib/api-types.ts`
 * -- and delete this file. The API already publishes the schema at /openapi.json.
 *
 * Field names and nullability match the Python contracts exactly. `| null` here
 * means the Python side is `X | None`, and every one of those nulls carries
 * meaning -- see the comments.
 */

export type RunStatus =
  | "queued"
  | "running"
  /** Every sample completed. Does NOT imply every sample was scored — a
   *  subjective run succeeds with zero scores, because not-yet-scorable is
   *  not a failure. */
  | "succeeded"
  /** Some samples errored, some completed. `mean_score` covers only the
   *  survivors; `error_count` says how many are missing. */
  | "partial"
  /** The run measured nothing: setup failed, or every sample errored. */
  | "failed";

export type TaskKind = "verifiable" | "subjective";

export type ScorerKind = "exact_match" | "numeric_match" | "llm_judge";

export interface SamplingParams {
  temperature: number;
  top_p: number;
  max_tokens: number;
  /** Null when the endpoint does not support seeding (most hosted APIs). */
  seed: number | null;
  stop: string[];
}

/** D-1: the full reproducibility payload, copied by value onto every result. */
export interface ServingConfig {
  model_id: string;
  registry_key: string;
  serving_stack: string;
  serving_version: string | null;
  quantization: string;
  revision: string | null;
  context_window: number | null;
  sampling: SamplingParams;
  /** Free text, e.g. "2x DGX Spark GB10". Null for hosted APIs. */
  hardware: string | null;
  extra: Record<string, unknown>;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
}

/** One rubric criterion's contribution to a judged score. */
export interface CriterionScore {
  name: string;
  value: number;
  weight: number;
  explanation: string;
}

export interface Score {
  scorer: ScorerKind;
  /** Always in [0, 1] so scores from different scorers aggregate. */
  value: number;
  /** The binary reading, or null when a binary reading is not meaningful.
   *  A rubric-weighted judge score is graded, not pass/fail — null there means
   *  "this scorer makes no pass/fail claim", which is NOT the same as false. */
  passed: boolean | null;
  /** Why. Shown in the UI so a reviewer need not open the transcript. */
  explanation: string;
  /** Per-criterion breakdown. Empty for programmatic scorers. */
  criteria: CriterionScore[];
  details: Record<string, unknown>;
}

export interface ResultRecord {
  id: string;
  run_id: string;
  task_id: string;
  sample_id: string;
  /** Which repetition of this sample. 0 unless repeated sampling is on. */
  repeat_index: number;
  model_key: string;
  /** D-1: what answered the prompt. */
  serving_config: ServingConfig;
  /** D-1 applied to the GRADE: what judged this sample, if anything did. */
  judge_serving_config: ServingConfig | null;
  /** SHA-256 of the task's canonicalised definition — the comparability key. */
  task_content_sha: string | null;

  /** Null when the sample errored, OR when the task is not yet scorable.
   *
   *  ⚠ Never branch on this alone. The two causes are completely different and
   *  are distinguished by `scorable` + `error`:
   *
   *    scorable: false, error: null   → not yet scorable (subjective task)
   *    scorable: true,  error: "..."  → the sample FAILED; nothing was measured
   *
   *  Collapsing them is what made the UI describe a run of failed API calls as
   *  "a subjective task". Use the helpers in lib/outcome.ts. */
  score: Score | null;
  /** False for subjective samples: the LLM judge is not implemented yet. */
  scorable: boolean;
  /** True when served from cache: cost and latency are 0 because this run
   *  incurred neither. */
  cached: boolean;
  usage: TokenUsage;
  /** Money spent producing THIS record. 0 on a cache hit. */
  cost_usd: number;
  /** Wall-clock observed on THIS run. 0 on a cache hit. */
  latency_ms: number;
  /** `s3://bucket/key` pointer to the archived transcript. */
  transcript_uri: string | null;
  /** Set when the sample succeeded but its transcript could not be archived. */
  archive_error: string | null;
  error: string | null;
  created_at: string;
}

export interface RunRecord {
  id: string;
  status: RunStatus;
  task_id: string;
  model_key: string;
  label: string | null;
  /** Groups every run created by one POST /runs — the comparison view's key. */
  sweep_id: string | null;
  /** D-1: git SHA of the repo. Null means unreproducible. */
  task_git_sha: string | null;
  /** SHA-256 of this task's canonicalised text. Finer-grained than the repo
   *  SHA, which changes on every unrelated commit. */
  task_content_sha: string | null;
  /** D-1: the git SHA of the build that executed this run, or `"unknown"`.
   *  Rows written before that change still carry the old hardcoded `"0.1.0"`;
   *  see `formatBuildIdentity` in lib/format.ts. */
  harness_version: string;
  /** Null while the run is still queued (no runner has claimed it). */
  serving_config: ServingConfig | null;
  sample_count: number;
  scored_count: number;
  /** Samples that failed outright. This is what disambiguates
   *  `scored_count < sample_count` between "calls failed" and "not scorable". */
  error_count: number;
  /** Null when nothing was scored — NOT zero. Both a subjective run and a
   *  totally failed one have null here; `error_count` tells them apart. */
  mean_score: number | null;
  total_usage: TokenUsage;
  total_cost_usd: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunDetail {
  run: RunRecord;
  results: ResultRecord[];
}

export interface RunListResponse {
  runs: RunRecord[];
  /** Rows matching the filters, ignoring pagination. */
  total: number;
  limit: number;
  offset: number;
}

export interface TaskSummary {
  id: string;
  title: string;
  description: string;
  kind: TaskKind;
  domain: string;
  scorer: string;
  sample_count: number;
  scorable: boolean;
  /** Populated when `scorable` is false, e.g. "requires LLM-as-judge...". */
  unscorable_reason: string | null;
  tags: string[];
}

export interface ModelSummary {
  key: string;
  display_name: string;
  base_url: string;
  enabled: boolean;
  requires_api_key: boolean;
  serving_stack: string;
  model_id: string;
  quantization: string;
  tags: string[];
}

export interface SampleTranscript {
  run_id: string;
  task_id: string;
  sample_id: string;
  model_key: string;
  messages: { role: string; content: string }[];
  completion: string;
  usage: TokenUsage;
  latency_ms: number;
  request_id: string | null;
  raw_response: Record<string, unknown>;
}
