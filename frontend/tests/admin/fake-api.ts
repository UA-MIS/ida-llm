/**
 * An in-memory stand-in for the admin API as seen THROUGH THE BFF
 * (`/admin/api/...`), for DOM tests of the admin components. MSW-free on
 * purpose (design §9): it is a `fetch` replacement, installed with
 * `vi.stubGlobal("fetch", fake.fetch)`.
 *
 * It implements the wire conventions the components rely on: `version` +
 * `If-Match` (409 `version_conflict` with `current`, 428 when missing), the
 * `{detail: {code, message, issues}}` envelope, and 204 on delete. Domain
 * rules are only the few the tests exercise.
 */

import type { AdminModel, AdminModelInput, AdminTask, Credential, Issue, ModelFamily, TaskDocument, TaskFamily } from "@/lib/admin/types";

export interface FakeState {
  models: AdminModel[];
  families: ModelFamily[];
  credentials: Credential[];
  taskFamilies: TaskFamily[];
  tasks: AdminTask[];
  /** Raw upload bodies that were committed (the fake's "MinIO"). */
  stored: string[];
  /** Every key ever sent to POST/PUT credentials. Tests assert it never renders. */
  receivedSecrets: string[];
}

export interface FakeCall {
  method: string;
  path: string;
  ifMatch: string | null;
  body: unknown;
}

const json = (status: number, body: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const problem = (status: number, code: string, message: string, extra: Record<string, unknown> = {}) =>
  json(status, { detail: { code, message, ...extra } });

export function sampleModel(over: Partial<AdminModel> = {}): AdminModel {
  return {
    key: "gpt-5-mini",
    display_name: "GPT-5 mini",
    family_key: null,
    display_order: 10,
    base_url: "https://api.example.test/v1",
    base_url_env: null,
    api_key_env: "OPENAI_API_KEY",
    credential_ref: null,
    enabled: true,
    hidden: false,
    timeout_s: 120,
    max_retries: 3,
    tags: ["cloud"],
    serving: { model_id: "gpt-5-mini", serving_stack: "openai_api", quantization: "unknown", sampling: { temperature: 0, top_p: 1, max_tokens: 1024, seed: null } },
    cost: { input_usd_per_mtok: 0.25, output_usd_per_mtok: 2 },
    uses: "env",
    key_present: true,
    archived_at: null,
    updated_at: "2026-11-17T12:00:00Z",
    updated_by: "someone",
    version: 1,
    ...over,
  };
}

export function sampleTaskFamily(over: Partial<TaskFamily> = {}): TaskFamily {
  return { key: "quiz", title: "Quiz", description: "", provenance: "synthetic", task_count: 1, sample_count: 2, classes: [], unit: null, archived_at: null, version: 1, ...over };
}

export function sampleTask(over: Partial<AdminTask> = {}): AdminTask {
  const document: TaskDocument = {
    version: 1,
    id: "quiz/l1-add",
    title: "Adding",
    kind: "verifiable",
    system_prompt: "Answer with a number.",
    scorer: { kind: "numeric_match", tolerance: 0.01, normalisation: { strip: true } },
    tags: ["quiz"],
    samples: [
      { id: "q1", input: "2+2?", target: "4" },
      { id: "q2", input: "3+4?", target: "7", metadata: { skill: "addition" } },
    ],
  };
  return {
    id: "quiz/l1-add", family_key: "quiz", title: "Adding", kind: "verifiable", sample_count: 2, content_sha: "abc", source: "yaml_seed",
    updated_at: "2026-11-17T12:00:00Z", updated_by: null, archived_at: null, version: 1, document, issues: [], ...over,
  };
}

export function createFakeAdminApi(seed: Partial<FakeState> = {}) {
  const state: FakeState = {
    models: seed.models ?? [sampleModel()],
    families: seed.families ?? [],
    credentials: seed.credentials ?? [],
    taskFamilies: seed.taskFamilies ?? [sampleTaskFamily()],
    tasks: seed.tasks ?? [sampleTask()],
    stored: [],
    receivedSecrets: [],
  };
  const calls: FakeCall[] = [];

  function checkVersion(ifMatch: string | null, current: { version: number }): Response | null {
    if (ifMatch === null) return problem(428, "precondition_required", "If-Match is required.");
    const v = Number(ifMatch.replace(/^W\//, "").replace(/"/g, ""));
    if (v !== current.version) return problem(409, "version_conflict", "This item changed since you loaded it.", { current });
    return null;
  }

  function validateModel(input: AdminModelInput): Issue[] {
    const issues: Issue[] = [];
    if (!input.display_name) issues.push({ path: "display_name", message: "display_name is required", severity: "error" });
    if (input.serving?.model_id === "rejected-by-api") {
      issues.push({ path: "serving.model_id", message: "unknown model id for this provider", severity: "error" });
    }
    if (input.tags?.includes("bogus")) issues.push({ path: "tags[0]", message: "unknown tag", severity: "error" });
    return issues;
  }

  async function handle(method: string, path: string, ifMatch: string | null, body: unknown): Promise<Response> {
    const seg = path.split("/").filter(Boolean).map(decodeURIComponent);
    const [resource, id, sub] = seg;

    if (resource === "models") {
      if (method === "GET" && !id) return json(200, state.models);
      if (method === "POST" && id === "reorder") {
        const order = (body as { order: string[] }).order;
        order.forEach((key, i) => {
          const m = state.models.find((x) => x.key === key);
          if (m) Object.assign(m, { display_order: (i + 1) * 10, version: m.version + 1 });
        });
        return json(200, state.models);
      }
      if (method === "POST" && !id) {
        const input = body as AdminModelInput;
        if (state.models.some((m) => m.key === input.key)) return problem(409, "conflict", `A model with id ${input.key} already exists (or once did).`);
        const issues = validateModel(input);
        if (issues.length) return problem(422, "validation_failed", "Model failed validation", { issues });
        const created = sampleModel({ ...input, version: 1, uses: input.credential_ref ? "credential" : input.api_key_env ? "env" : "none" });
        state.models.push(created);
        return json(201, created);
      }
      const m = state.models.find((x) => x.key === id);
      if (!m) return problem(404, "not_found", "No such model.");
      if (method === "GET" && !sub) return json(200, m);
      if (method === "POST" && sub === "test") return json(200, { ok: true, latency_ms: 321 });
      const stale = checkVersion(ifMatch, m);
      if (stale) return stale;
      if (method === "PUT") {
        const issues = validateModel(body as AdminModelInput);
        if (issues.length) return problem(422, "validation_failed", "Model failed validation", { issues });
        Object.assign(m, body, { version: m.version + 1 });
        return json(200, m);
      }
      if (method === "PATCH") {
        Object.assign(m, body, { version: m.version + 1 });
        return json(200, m);
      }
      if (method === "DELETE") {
        Object.assign(m, { archived_at: "2026-11-17T13:00:00Z", version: m.version + 1 });
        return json(204, undefined);
      }
    }

    if (resource === "model-families") {
      if (method === "GET") return json(200, state.families);
      if (method === "POST") {
        const input = body as { key: string; display_name: string };
        if (state.families.some((f) => f.key === input.key)) {
          return problem(422, "validation_failed", "Family failed validation", { issues: [{ path: "key", message: "that id is taken", severity: "error" }] });
        }
        const fam = { ...input, member_keys: [], version: 1 };
        state.families.push(fam);
        return json(201, fam);
      }
      const f = state.families.find((x) => x.key === id);
      if (!f) return problem(404, "not_found", "No such family.");
      const stale = checkVersion(ifMatch, f);
      if (stale) return stale;
      if (method === "PUT") return json(200, Object.assign(f, body, { version: f.version + 1 }));
      if (method === "DELETE") {
        if (f.member_keys.length) return problem(409, "conflict", "The family still has models.");
        state.families = state.families.filter((x) => x !== f);
        return json(204, undefined);
      }
    }

    if (resource === "credentials") {
      if (method === "GET") return json(200, state.credentials);
      if (method === "POST") {
        const input = body as { name: string; provider: string; api_key: string };
        state.receivedSecrets.push(input.api_key);
        const cred: Credential = {
          name: input.name, provider: input.provider, kek_id: "k1", created_at: "2026-11-17T12:00:00Z", created_by: "ccsmith33",
          rotated_at: null, last_used_at: null, used_by_models: [], version: 1,
        };
        state.credentials.push(cred);
        return json(201, cred);
      }
      const c = state.credentials.find((x) => x.name === id);
      if (!c) return problem(404, "not_found", "No such key.");
      const stale = checkVersion(ifMatch, c);
      if (stale) return stale;
      if (method === "PUT" && sub === "secret") {
        state.receivedSecrets.push((body as { api_key: string }).api_key);
        return json(200, Object.assign(c, { rotated_at: "2026-11-17T13:00:00Z", version: c.version + 1 }));
      }
      if (method === "DELETE") {
        state.credentials = state.credentials.filter((x) => x !== c);
        return json(204, undefined);
      }
    }

    if (resource === "task-families") {
      if (method === "GET") return json(200, state.taskFamilies);
      if (method === "POST") {
        const input = body as TaskFamily;
        const fam = sampleTaskFamily({ ...input, task_count: 0, sample_count: 0 });
        state.taskFamilies.push(fam);
        return json(201, fam);
      }
      const f = state.taskFamilies.find((x) => x.key === id);
      if (!f) return problem(404, "not_found", "No such family.");
      const stale = checkVersion(ifMatch, f);
      if (stale) return stale;
      if (method === "PUT") {
        if ((body as TaskFamily).provenance === "private") {
          return problem(422, "validation_failed", "Family failed validation", { issues: [{ path: "provenance", message: "private needs B6", severity: "error" }] });
        }
        return json(200, Object.assign(f, body, { version: f.version + 1 }));
      }
      if (method === "DELETE") {
        if (f.classes.length) return problem(409, "conflict", `The family is used by ${f.classes.join(", ")}.`);
        f.archived_at = "2026-11-17T13:00:00Z";
        return json(204, undefined);
      }
    }

    if (resource === "tasks") {
      if (method === "GET" && !id) {
        return json(200, state.tasks.map((t) => {
          const summary: Partial<AdminTask> = { ...t };
          delete summary.document;
          delete summary.issues;
          return summary;
        }));
      }
      if (method === "POST" && id === "validate") {
        const yaml = (body as { yaml?: string }).yaml ?? "";
        if (yaml.includes("BROKEN")) return json(200, { ok: false, issues: [{ path: "line 3, col 1", message: "could not parse", severity: "error" }] });
        return json(200, { ok: true, issues: [], sample_count: 2, content_sha: "def" });
      }
      if (method === "POST" && !id) {
        const doc = (body as { document: TaskDocument }).document;
        const issues: Issue[] = [];
        if (doc.samples?.[0]?.target === "leak") issues.push({ path: "samples[0].target", message: "target leaks into metadata", severity: "error" });
        if (String(doc.tags).includes("slo:typo")) issues.push({ path: "tags[1]", message: "unknown slo tag", severity: "error" });
        if (issues.length) return problem(422, "validation_failed", "Task failed validation", { issues });
        const task = sampleTask({ id: doc.id, family_key: doc.id.split("/")[0]!, title: doc.title, document: doc, source: "form", sample_count: doc.samples.length });
        state.tasks.push(task);
        return json(201, task);
      }
      // Task ids contain "/": everything up to an optional "samples" segment is the id.
      const at = seg.indexOf("samples", 1);
      const taskId = seg.slice(1, at < 0 ? undefined : at).join("/");
      const sampleId = at < 0 ? undefined : seg[at + 1];
      const t = state.tasks.find((x) => x.id === taskId);
      if (!t) return problem(404, "not_found", "No such task.");
      if (method === "GET" && at < 0) return json(200, t);
      const stale = checkVersion(ifMatch, t);
      if (stale) return stale;
      const bump = (doc: TaskDocument) => {
        Object.assign(t, { document: doc, version: t.version + 1, sample_count: doc.samples.length, title: doc.title });
        return json(200, t);
      };
      if (at < 0 && method === "PUT") return bump((body as { document: TaskDocument }).document);
      if (at < 0 && method === "DELETE") {
        t.archived_at = "2026-11-17T13:00:00Z";
        return json(204, undefined);
      }
      const sample = (body as { sample?: TaskDocument["samples"][number] } | undefined)?.sample;
      if (sample && t.kind === "verifiable" && !sample.target) {
        return problem(422, "validation_failed", "Task failed validation", { issues: [{ path: "samples[2].target", message: "verifiable sample needs a target", severity: "error" }] });
      }
      if (method === "POST") return bump({ ...t.document, samples: [...t.document.samples, sample!] });
      if (method === "PUT") return bump({ ...t.document, samples: t.document.samples.map((s) => (s.id === sampleId ? sample! : s)) });
      if (method === "DELETE") return bump({ ...t.document, samples: t.document.samples.filter((s) => s.id !== sampleId) });
    }

    return problem(501, "not_implemented", "Not in the fake.");
  }

  async function upload(form: FormData): Promise<Response> {
    const file = form.get("file") as Blob;
    // jsdom's Blob has no .text(); FileReader works in both jsdom and browsers.
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(file);
    });
    const commit = form.get("commit") === "true";
    calls.push({ method: "POST", path: "/material/upload", ifMatch: null, body: { mode: form.get("mode"), commit, text } });
    if (text.includes("BROKEN")) return json(200, { ok: false, committed: false, issues: [{ path: "line 3, col 1", message: "could not parse", severity: "error" }] });
    if (commit) state.stored.push(text);
    const task = state.tasks[0]!;
    return json(200, {
      ok: true, committed: commit, issues: [], sample_count: 2, content_sha: "def",
      task: { ...task, document: undefined }, diff: { samples_added: 1, samples_removed: 0, samples_changed: 2 },
    });
  }

  const fetch = async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input), "https://admin.example.test");
    if (!url.pathname.startsWith("/admin/api/")) throw new Error(`fake admin API: unexpected fetch ${url.pathname}`);
    const path = url.pathname.slice("/admin/api".length);
    const headers = new Headers(init.headers);
    const method = (init.method ?? "GET").toUpperCase();
    if (init.body instanceof FormData) return upload(init.body);
    const body = typeof init.body === "string" && init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, ifMatch: headers.get("if-match"), body });
    return handle(method, path, headers.get("if-match"), body);
  };

  return { state, calls, fetch };
}
