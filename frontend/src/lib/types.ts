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

// ---------------------------------------------------------------------------
// The results view (`GET /leaderboard`)
//
// Task-first: one entry per TASK, with every model measured on it ranked
// inside. The cross-model comparison is what you read within a task, not the
// thing you start from -- a professor arrives asking "can it grade my
// quizzes?", never "rank these seven models".
// ---------------------------------------------------------------------------

/** How much one number supports itself. Never a claim about the model. */
export type Confidence = "high" | "moderate" | "low" | "none";

/**
 * The trust tell, computed server-side so one rule serves every consumer.
 *
 * `tier_label` is the badge; `headline` is the sentence that says what kind of
 * evidence this is; `caveats` is everything a reader should know before
 * repeating the number. A judged score can never be `high` confidence -- see
 * `ida_api/trust.py` for why.
 */
export interface TrustTell {
  kind: TaskKind;
  scorer: string;
  tier_label: string;
  headline: string;
  confidence: Confidence;
  confidence_label: string;
  confidence_reason: string;
  caveats: string[];
}

/** Where a prompt sent to this model physically goes. The FERPA-relevant fact. */
export type DataResidency =
  | "on_campus"
  | "third_party"
  | "not_a_real_model"
  | "unknown";

export interface ModelResult {
  model_key: string;
  display_name: string;
  model_tags: string[];
  data_residency: DataResidency;
  data_residency_label: string;
  enabled: boolean;
  /** False for test stubs. The recommendation engine must never return one. */
  recommendable: boolean;
  /** Null is never zero — `trust` says which kind of null it is. */
  mean_score: number | null;
  scored_count: number;
  sample_count: number;
  error_count: number;
  /**
   * What WE spent measuring this pair — **not** what a reader would pay.
   *
   * ⚠ NOT A PRICE. It scales with how many samples we chose to run, it is `0`
   * on a cache hit, and it is `0` for every row the dev seeder writes. Dividing
   * it by `scored_count` describes our benchmark, not the model — and on a
   * seeded environment it reports every model as free. Use `price` for anything
   * a reader is meant to budget against; see `lib/value.ts`.
   */
  total_cost_usd: number;
  /**
   * The registry's published rate card, or `null` for an unregistered key.
   *
   * `null` is not "free" — it means the model is not in `models.yaml`, so we
   * have nothing to quote.
   */
  price: CostNote | null;
  /**
   * Tokens behind `total_cost_usd`, so a per-million rate card can become a
   * figure a person can hold. All-zero means no token accounting was recorded,
   * which is not the same as a free run.
   */
  usage: TokenUsage;
  /**
   * True when this row was seeded for illustration and never actually measured.
   *
   * ⚠ PER ROW, NOT PER DEPLOYMENT. A dev database holds both kinds the moment
   * anyone runs a real model against a seeded catalogue, so a page-level
   * "this is demo data" banner would be false about half of it. It is also
   * self-clearing: the flag stops appearing when the row becomes real, so
   * nobody has to remember to take a disclaimer down.
   */
  demonstration: boolean;
  trust: TrustTell;
  /** THE receipt (D-3): one click to the transcripts, scorer and serving config. */
  run_id: string;
  run_status: RunStatus;
  task_content_sha: string | null;
  measured_at: string | null;
}

export interface TaskLeaderboard {
  task_id: string;
  title: string;
  description: string;
  kind: TaskKind;
  domain: string;
  scorer: string;
  family: string;
  tags: string[];
  /**
   * The Student Learning Outcome this task measures, e.g. `SLO2`.
   *
   * The grouping key. Its MEANING — title, statement, whether a text benchmark
   * can measure it at all — comes from `LeaderboardResponse.curriculum`, which
   * is read from `curriculum/slo.yaml`. Nothing in this frontend holds a copy
   * of the nine outcomes.
   */
  slo: string | null;
  /** `capability` today; `assistive` and `instructional` are declared but not in use. */
  use_mode: string | null;
  /** Carries the `slo-benchmark` tag — one filter selects the whole benchmark. */
  in_benchmark: boolean;
  sample_count: number;
  scorable: boolean;
  unscorable_reason: string | null;
  results: ModelResult[];
  /** False when no model has a finished run — distinct from "measured, all null". */
  has_results: boolean;
  /** Excludes test stubs, so the winner is never a fixture. */
  best_model_key: string | null;
}

export interface LeaderboardResponse {
  tasks: TaskLeaderboard[];
  task_count: number;
  measured_task_count: number;
  runs_considered: number;
  /** False on a fresh install: render an honest empty state, not an empty table. */
  has_any_results: boolean;
  /** `curriculum/slo.yaml`, read not retyped. See `CurriculumView`. */
  curriculum: CurriculumView;
  benchmark_task_count: number;
  /** Outcome ids present, in CURRICULUM order (SLO10 must not sort before SLO2). */
  slos: string[];
  use_modes: string[];
  families: string[];
  domains: string[];
}

/** One Student Learning Outcome, as the programme publishes it. */
export interface OutcomeView {
  id: string;
  title: string;
  statement: string;
  /**
   * False for the outcomes a single-turn text benchmark cannot measure (SLO5
   * Teamwork, SLO8 Oral Communication). Surfaced rather than filtered out: a
   * benchmark that silently covered seven of nine would read as though the
   * programme has seven.
   */
  text_benchmarkable: boolean;
  benchmark_note: string;
}

export interface UseModeView {
  id: string;
  title: string;
  statement: string;
  /** False declares the spelling without permitting a task to tag it yet. */
  in_use: boolean;
}

/**
 * `curriculum/slo.yaml`, served so no consumer holds its own copy.
 *
 * `available: false` is a legitimate state — a deployment without the map still
 * groups results by outcome id, it just cannot render the statements, and says
 * so rather than guessing at nine strings that are the registrar's to write.
 */
export interface CurriculumView {
  available: boolean;
  unavailable_reason: string | null;
  program: string | null;
  source: string | null;
  outcomes: OutcomeView[];
  use_modes: UseModeView[];
  /**
   * The published course x outcome grid, in the map's own order.
   *
   * The drill-down at `/explore` reads its two middle levels — which courses a
   * programme has, and which outcomes each course teaches — from here and
   * nowhere else. Empty when `available` is false: a deployment with no map has
   * no courses to name, and naming some would be inventing a curriculum.
   */
  coverage: CourseCoverageView[];
  /**
   * `curriculum/majors.yaml`, in the file's own order.
   *
   * ⚠ INDEPENDENTLY OPTIONAL FROM `available`. That flag is about the
   * curriculum MAP; the majors taxonomy is a second file with a second source
   * and a second revision date, and either can be absent without the other
   * being. An empty array means this deployment has no taxonomy — which
   * `/explore` states plainly and degrades to the outcome views over. It never
   * means the college has no majors, and nothing may render it as if it did.
   */
  majors: MajorView[];
  /** Coverage courses no single major owns. Reachable, just not drilled into. */
  unassigned_core: UnassignedCourseView[];
}

/**
 * One undergraduate major, and the classes it owns.
 *
 * ⚠ THE TOP OF THE DRILL-DOWN, AND WHY IT IS NOT THE PROGRAMME ANY MORE. The
 * flow used to open on a single programme — the shared business core — because
 * that is all the curriculum map describes. Nobody is a professor of "the
 * core": they teach Management Information Systems, and the flow has to start
 * where the reader already stands. Which classes exist and whose they are comes
 * from the course catalog, a different document from the curriculum map; the
 * two join on the course code, here as in the files.
 */
export interface MajorView {
  /** The URL segment. Authored in the file, never slugified from `name`. */
  id: string;
  name: string;
  /** The department that owns it — one department owns four of the eleven. */
  department: string;
  catalog: string | null;
  /** `catalog` / `core-only` / `none` — how far the class list got. */
  class_source: string;
  /**
   * That same fact in the words a reader gets.
   *
   * Served rather than derived so a short class list reads as an incomplete
   * transcription rather than as a small department.
   */
  class_source_label: string;
  classes: MajorClassView[];
}

/** One class a major owns. */
export interface MajorClassView {
  /** The course code as the catalog prints it — the join key into `coverage`. */
  course: string;
  /**
   * Already resolved on the wire: the catalog's title where it has one, the
   * curriculum map's otherwise. One implementation of the precedence rule, in
   * `ida_core.majors`, so no two clients can disagree about a course's name.
   */
  title: string;
  credit_hours: number | null;
  /**
   * Task families whose results are ABOUT this class's own material.
   *
   * ⚠ THE FIELD THAT KEEPS "MEASURED" A CLAIM ABOUT A CLASS. Results are filed
   * by OUTCOME — a task carries `slo:SLO2`, never `course:MIS 200`. Score a
   * class from "the outcomes it teaches" and the number you get is identical
   * for every other class the map marks against those outcomes: run the three
   * MIS 200 families and AC 210, ST 260, GBA 300, OM 300 and FI 302 would each
   * light up with an exam score from a course none of them is. Filtering on
   * these families is what makes the grid's central promise — every score is
   * real, everything else says "not measured yet" — structural rather than a
   * caveat somebody has to remember to print.
   *
   * Empty means no result can be attributed to this class. That is the default
   * and it is correct: a class shows a number only once tasks about it exist.
   */
  task_families: string[];
}

/** A course in the coverage grid that no single major owns, and why. */
export interface UnassignedCourseView {
  course: string;
  reason: string;
}

/** One row of the published course-by-outcome grid. */
export interface CourseCoverageView {
  /** The course code as the map spells it, e.g. `MIS 200`. */
  course: string;
  title: string;
  /**
   * Outcome id to the published level (`I`/`R`/`M`/`A`/`M+A`).
   *
   * ⚠ AN ABSENT KEY IS NOT A ZERO. It means the published map does not mark
   * that (course, outcome) pair at all — not that the level is unknown, and
   * certainly not that the course covers the outcome badly.
   */
  outcomes: Record<string, string>;
}

// ---------------------------------------------------------------------------
// The recommendation flow (`GET /recommend/questions`, `POST /recommend`)
// ---------------------------------------------------------------------------

export interface IntakeOption {
  value: string;
  label: string;
  detail: string | null;
}

/** "Ask this only if `question_id` was answered with one of `values`." */
export interface IntakeCondition {
  question_id: string;
  values: string[];
}

export interface IntakeQuestion {
  id: string;
  prompt: string;
  detail: string | null;
  options: IntakeOption[];
  /** Required *when it applies*. An unmet condition makes it never required. */
  required: boolean;
  why_it_matters: string;
  depends_on: IntakeCondition | null;
  /** Shown when the question appears because of a previous answer (the FERPA branch). */
  branch_note: string | null;
}

/**
 * Three refusals and one answer, and they are genuinely different things.
 *
 * `need_more_context`   we were not told enough — the gaps are named
 * `no_eligible_model`   a hard constraint you stated rules out every model
 * `insufficient_evidence` nothing resembling your task has been benchmarked
 */
export type RecommendationStatus =
  | "ok"
  | "need_more_context"
  | "no_eligible_model"
  | "insufficient_evidence";

export interface Gap {
  question_id: string;
  prompt: string;
  why_it_matters: string;
}

export interface Receipt {
  task_id: string;
  task_title: string;
  task_kind: TaskKind;
  model_key: string;
  run_id: string;
  mean_score: number | null;
  scored_count: number;
  sample_count: number;
  confidence: Confidence;
  trust_label: string;
}

export interface CostNote {
  tier: "free" | "campus_hosted" | "paid";
  label: string;
  detail: string;
  input_usd_per_mtok: number;
  output_usd_per_mtok: number;
}

export interface Constraint {
  label: string;
  detail: string;
  /** Hard constraints eliminate models outright; soft ones only reorder. */
  hard: boolean;
}

export interface Recommendation {
  model_key: string;
  display_name: string;
  headline: string;
  why: string[];
  surface: string;
  surface_label: string;
  surface_rationale: string;
  cost: CostNote;
  data_residency: DataResidency;
  data_residency_label: string;
  prompt_template: string;
  guardrails: string[];
  caveats: string[];
  receipts: Receipt[];
  /** Shown, not hidden: a ranking whose basis is invisible is a black box. */
  evidence_score: number | null;
  verifiable_evidence: boolean;
}

export interface ContextItem {
  label: string;
  value: string;
}

export interface RecommendationResponse {
  status: RecommendationStatus;
  message: string;
  context_summary: ContextItem[];
  gaps: Gap[];
  constraints: Constraint[];
  primary: Recommendation | null;
  alternatives: Recommendation[];
  matched_task_ids: string[];
  missing_benchmarks: string[];
  what_would_change_this: string[];
}

/**
 * One sample as `GET /tasks/{id}` exposes it.
 *
 * `metadata` is the task author's own dict. For SLO-benchmark tasks it repeats
 * the task's two axes un-prefixed (`slo`, `use_mode`) alongside the sample's own
 * `skill` and `provenance` — that is the per-sample drill-down, and the task
 * validator requires it to agree with the tags so the two never disagree.
 */
export interface SampleView {
  id: string;
  input: string;
  metadata: Record<string, unknown>;
  /** Null when redacted OR genuinely absent — consult `has_target`. */
  target: string | null;
  has_target: boolean;
}

export interface TaskDetail {
  id: string;
  title: string;
  description: string;
  kind: TaskKind;
  domain: string;
  system_prompt: string | null;
  tags: string[];
  content_sha: string;
  samples: SampleView[];
  sample_count: number;
  scorable: boolean;
  unscorable_reason: string | null;
  /** True when gold answers were withheld — the default for an anonymous read. */
  targets_redacted: boolean;
}
