/**
 * The admin API contract (design §9), hand-mirrored from
 * `services/api/ida_api/admin/schemas.py`. Shared by server pages and the
 * `components/admin` client components, so it holds TYPES ONLY: nothing here
 * may import a server module or carry a value.
 *
 * Wire conventions: snake_case JSON, ISO-8601 UTC timestamps, every mutable
 * resource carries `version` (sent back as `If-Match`), errors use the
 * `{detail: AdminError}` envelope.
 */

import type { RunDetail as PublicRunDetail, RunRecord as PublicRunRecord, ResultRecord } from "../types";

export type Version = number;

export interface Issue {
  path: string;
  message: string;
  severity: "error" | "warning";
}

export type AdminErrorCode =
  | "admin_disabled"
  | "unauthenticated"
  | "forbidden"
  | "actor_required"
  | "not_found"
  | "version_conflict"
  | "validation_failed"
  | "conflict"
  | "spend_confirmation_required"
  | "cap_exceeded"
  | "kek_missing";

export interface AdminError {
  code: AdminErrorCode;
  message: string;
  issues?: Issue[];
  current?: unknown;
}

export interface ModelFamily {
  key: string;
  display_name: string;
  member_keys: string[];
  version: Version;
}

export interface Sampling {
  temperature: number | null;
  top_p: number | null;
  max_tokens: number;
  seed: number | null;
}

export interface Serving {
  model_id: string;
  serving_stack: string;
  serving_version: string | null;
  quantization: string;
  revision?: string | null;
  context_window: number | null;
  hardware: string | null;
  sampling: Sampling;
  extra?: Record<string, unknown>;
}

export interface AdminModelInput {
  key: string;
  display_name: string;
  family_key: string | null;
  display_order: number | null;
  base_url: string | null;
  base_url_env: string | null;
  api_key_env: string | null;
  credential_ref: string | null;
  enabled: boolean;
  hidden: boolean;
  timeout_s: number;
  max_retries: number;
  tags: string[];
  serving: Serving;
  cost: { input_usd_per_mtok: number; output_usd_per_mtok: number };
}

export interface AdminModel extends AdminModelInput {
  uses: "env" | "credential" | "none";
  key_present: boolean;
  archived_at: string | null;
  updated_at: string;
  updated_by: string | null;
  version: Version;
}

export interface ModelTestResult {
  ok: boolean;
  latency_ms: number;
  error?: string | null;
}

export interface Credential {
  name: string;
  provider: string;
  kek_id: string;
  created_at: string;
  created_by: string;
  rotated_at: string | null;
  last_used_at: string | null;
  used_by_models: string[];
  version: Version;
}

/** `api_key` is write-only: it is sent, never received. */
export interface CredentialInput {
  name: string;
  provider: string;
  api_key: string;
}

export interface TaskFamily {
  key: string;
  title: string;
  description: string;
  provenance: "synthetic" | "private";
  task_count: number;
  sample_count: number;
  classes: string[];
  unit: { course: string; key: string } | null;
  version: Version;
}

export interface TaskFamilyInput {
  key: string;
  title: string;
  description: string;
  provenance: "synthetic" | "private";
}

export interface AdminTaskSummary {
  id: string;
  title: string;
  kind: "verifiable" | "subjective";
  sample_count: number;
  content_sha: string;
  source: "yaml_seed" | "form" | "upload";
  updated_at: string;
  updated_by: string | null;
  version: Version;
}

export type TaskSample = Record<string, unknown> & { id: string; input: string };

/** The whole task document; full shape in `tasks/SCHEMA.md`. */
export type TaskDocument = Record<string, unknown> & {
  version: 1;
  id: string;
  title: string;
  kind: string;
  samples: TaskSample[];
};

export interface AdminTask extends AdminTaskSummary {
  document: TaskDocument;
  issues: Issue[];
}

export interface ValidateResult {
  ok: boolean;
  issues: Issue[];
  content_sha?: string;
  sample_count?: number;
}

export interface UploadResult extends ValidateResult {
  task?: AdminTaskSummary;
  diff?: { samples_added: number; samples_removed: number; samples_changed: number };
}

export interface AdminUnit {
  id: string;
  course: string;
  key: string;
  n: number;
  title: string;
  covers: string[];
  blurb: string;
  source: string | null;
  caveat: string | null;
  families: string[];
  version: Version;
}

export interface UnitInput {
  key: string;
  n: number;
  title: string;
  covers: string[];
  blurb: string;
  source?: string | null;
  caveat?: string | null;
  families: string[];
}

export interface AdminClass {
  course: string;
  major_id: string | null;
  unassigned_reason: string | null;
  title: string | null;
  resolved_title: string | null;
  credit_hours: number | null;
  position: number;
  task_families: string[];
  units: AdminUnit[];
  version: Version;
}

export interface ClassInput {
  course: string;
  major_id: string | null;
  unassigned_reason: string | null;
  title?: string | null;
  credit_hours?: number | null;
  position: number;
}

export interface AdminMajor {
  id: string;
  name: string;
  department: string;
  subject_codes: string[];
  display_code: string | null;
  catalog: string | null;
  class_source: string;
  position: number;
  classes: AdminClass[];
  version: Version;
}

export interface MajorInput {
  id: string;
  name: string;
  department: string;
  subject_codes: string[];
  display_code: string | null;
  catalog: string | null;
  class_source: string;
  position: number;
}

export interface MajorsResponse {
  majors: AdminMajor[];
  unassigned: AdminClass[];
}

export interface SloDocument {
  yaml: string;
  version: Version;
  issues?: Issue[];
}

export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled";

export interface RunLaunchInput {
  model_keys: string[];
  family_keys?: string[];
  task_ids?: string[];
  label?: string;
  sampling_override?: Record<string, unknown>;
  confirm_spend_usd?: number;
}

export interface RunEstimate {
  runs: number;
  samples: number;
  est_usd_high: number;
  includes_judge: boolean;
  pairs: { task_id: string; model_key: string; samples: number; est_usd_high: number; basis: "history" | "ceiling" }[];
  warnings: string[];
  caps: { max_runs: number; max_samples: number; max_estimated_usd: number };
  needs_confirmation: boolean;
}

export interface EnqueueResponse {
  runs: AdminRunRecord[];
  sweep_id: string | null;
  estimate?: RunEstimate;
  [key: string]: unknown;
}

export interface SweepSummary {
  sweep_id: string;
  created_at: string;
  launched_by: string | null;
  label: string | null;
  run_count: number;
  by_status: Partial<Record<RunStatus, number>>;
  total_cost_usd: number;
}

/** The public `RunRecord` plus the admin-only columns, with `cancelled` allowed. */
export type AdminRunRecord = Omit<PublicRunRecord, "status"> & {
  status: RunStatus;
  launched_by: string | null;
  config_revision: number | null;
  cancel_requested_at: string | null;
};

/** UNREDACTED: explanations and errors are present. Rendered only after `requireAdmin()`. */
export interface AdminRunDetail {
  run: AdminRunRecord;
  results: ResultRecord[];
}

export type { PublicRunDetail };

export interface AuditEntry {
  id: number;
  at: string;
  actor_login: string;
  via_subject: string;
  action: string;
  entity_type: string;
  entity_id: string;
  before: unknown;
  after: unknown;
  config_revision: number | null;
}

export interface Page<T> {
  entries?: T[];
  runs?: T[];
  next_cursor: string | null;
}

export interface SystemInfo {
  config_source: "yaml" | "db";
  revision: number | null;
  revision_at: string | null;
  guards: {
    sweep_max_runs: number;
    sweep_max_samples: number;
    admin_run_max_estimated_usd: number;
    sweep_exclude_tags: string[];
    public_hide_tags: string[];
  };
  judge_model_key: string | null;
  kek_configured: boolean;
  kek_active_id: string | null;
  admin_group_hint?: string | null;
  /** Added by B6; until it is true the UI refuses `provenance=private`. */
  tasks_spec_gated?: boolean;
}
