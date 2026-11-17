/**
 * Pure helpers for the material editor: turning form fields into a task
 * document and back. The document is the source of truth (design AD-8): the
 * form edits a handful of common fields and every other key (rubric,
 * normalisation, anything newer than this form) is carried over untouched.
 */

import type { TaskDocument, TaskSample } from "./types";

/** `family/name` → `family/name` with each segment URL-encoded, for API paths. */
export function taskPath(id: string): string {
  return id.split("/").map(encodeURIComponent).join("/");
}

export const TASK_NAME_RE = /^[a-z0-9][a-z0-9-]*$/;
export const SAMPLE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export interface TaskDetails {
  title: string;
  description: string;
  domain: string;
  system_prompt: string;
  scorer_kind: string;
  tolerance: string;
  tags: string;
}

const str = (v: unknown) => (typeof v === "string" ? v : v === undefined || v === null ? "" : String(v));

export function detailsOf(doc: TaskDocument): TaskDetails {
  const scorer = (doc.scorer ?? {}) as Record<string, unknown>;
  return {
    title: str(doc.title),
    description: str(doc.description),
    domain: str(doc.domain),
    system_prompt: str(doc.system_prompt),
    scorer_kind: str(scorer.kind) || (doc.kind === "subjective" ? "llm_judge" : "exact_match"),
    tolerance: str(scorer.tolerance),
    tags: Array.isArray(doc.tags) ? (doc.tags as unknown[]).map(String).join(", ") : "",
  };
}

const splitTags = (raw: string) => raw.split(",").map((t) => t.trim()).filter(Boolean);

/** The document with the form's fields applied. Keys the form does not show are kept. */
export function applyDetails(doc: TaskDocument, d: TaskDetails): TaskDocument {
  const next: TaskDocument = { ...doc, title: d.title.trim(), tags: splitTags(d.tags) };
  const setOrDrop = (key: string, value: string) => {
    if (value.trim()) next[key] = value;
    else delete next[key];
  };
  setOrDrop("description", d.description);
  setOrDrop("domain", d.domain.trim());
  setOrDrop("system_prompt", d.system_prompt);
  const scorer: Record<string, unknown> = { ...((doc.scorer ?? {}) as Record<string, unknown>), kind: d.scorer_kind };
  if (d.scorer_kind === "numeric_match" && d.tolerance.trim() !== "") scorer.tolerance = Number(d.tolerance);
  else delete scorer.tolerance;
  next.scorer = scorer;
  return next;
}

export interface NewTask extends TaskDetails {
  family: string;
  name: string;
  kind: "verifiable" | "subjective";
  rubric_description: string;
  sample_id: string;
  sample_input: string;
  sample_target: string;
}

/** A complete first draft of a task document, in the shape `tasks/SCHEMA.md` documents. */
export function newTaskDocument(t: NewTask): TaskDocument {
  const id = `${t.family}/${t.name}`;
  const tags = [t.family, ...splitTags(t.tags).filter((x) => x !== t.family)];
  const sample: TaskSample = { id: t.sample_id.trim(), input: t.sample_input };
  if (t.kind === "verifiable") sample.target = t.sample_target.trim();
  const doc: TaskDocument = { version: 1, id, title: t.title.trim(), kind: t.kind, tags, samples: [sample] };
  if (t.description.trim()) doc.description = t.description;
  if (t.domain.trim()) doc.domain = t.domain.trim();
  if (t.system_prompt.trim()) doc.system_prompt = t.system_prompt;
  if (t.kind === "verifiable") {
    const scorer: Record<string, unknown> = {
      kind: t.scorer_kind === "numeric_match" ? "numeric_match" : "exact_match",
      normalisation: { strip: true, collapse_whitespace: true, take_last_line: true },
    };
    if (scorer.kind === "numeric_match" && t.tolerance.trim()) scorer.tolerance = Number(t.tolerance);
    doc.scorer = scorer;
  } else {
    const rubricId = `${t.name}-v1`;
    doc.scorer = { kind: "llm_judge", rubric_id: rubricId };
    doc.rubric = {
      id: rubricId,
      scale_min: 0,
      scale_max: 1,
      criteria: [{ name: "overall", description: t.rubric_description, weight: 1 }],
    };
  }
  return doc;
}

/** Sample fields the sample editor shows; every other key on a sample is kept as is. */
export interface SampleFields {
  id: string;
  input: string;
  target: string;
  metadata: string;
}

export function sampleFieldsOf(s: TaskSample | null): SampleFields {
  return {
    id: s?.id ?? "",
    input: s?.input ?? "",
    target: s && s.target !== undefined && s.target !== null ? String(s.target) : "",
    metadata: s?.metadata && typeof s.metadata === "object" && Object.keys(s.metadata).length ? JSON.stringify(s.metadata, null, 2) : "",
  };
}

/** Build the sample to send, or return per-field problems. */
export function sampleFromFields(
  f: SampleFields,
  original: TaskSample | null,
  kind: string,
): { sample?: TaskSample; problems: Record<string, string> } {
  const problems: Record<string, string> = {};
  if (!SAMPLE_ID_RE.test(f.id.trim())) problems.id = "Use letters, digits, dots, dashes or underscores, e.g. q1 or item-07.";
  if (!f.input.trim()) problems.input = "Write the question the model will see.";
  if (kind === "verifiable" && !f.target.trim()) problems.target = "Give the correct answer, so the answer can be checked automatically.";
  let metadata: unknown = undefined;
  if (f.metadata.trim()) {
    try {
      metadata = JSON.parse(f.metadata);
      if (metadata === null || typeof metadata !== "object" || Array.isArray(metadata)) problems.metadata = "Extra details must be a { … } object.";
    } catch {
      problems.metadata = "This is not valid JSON. Check for missing quotes or commas, or leave it empty.";
    }
  }
  if (Object.keys(problems).length) return { problems };
  const sample: TaskSample = { ...(original ?? {}), id: f.id.trim(), input: f.input };
  if (kind === "verifiable") sample.target = f.target.trim();
  else if (!f.target.trim()) delete sample.target;
  else sample.target = f.target.trim();
  if (metadata) sample.metadata = metadata;
  else delete sample.metadata;
  return { sample, problems };
}
