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

import type { AdminModel, AdminModelInput, Credential, Issue, ModelFamily } from "@/lib/admin/types";

export interface FakeState {
  models: AdminModel[];
  families: ModelFamily[];
  credentials: Credential[];
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

export function createFakeAdminApi(seed: Partial<FakeState> = {}) {
  const state: FakeState = {
    models: seed.models ?? [sampleModel()],
    families: seed.families ?? [],
    credentials: seed.credentials ?? [],
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

    return problem(501, "not_implemented", "Not in the fake.");
  }

  const fetch = async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input), "https://admin.example.test");
    if (!url.pathname.startsWith("/admin/api/")) throw new Error(`fake admin API: unexpected fetch ${url.pathname}`);
    const path = url.pathname.slice("/admin/api".length);
    const headers = new Headers(init.headers);
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" && init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, ifMatch: headers.get("if-match"), body });
    return handle(method, path, headers.get("if-match"), body);
  };

  return { state, calls, fetch };
}
