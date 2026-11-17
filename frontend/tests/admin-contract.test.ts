/**
 * Every admin API path this console calls exists in the backend's published
 * contract (`docs/admin-api.openapi.json`, dumped from
 * `services/api/ida_api/admin/schemas.py`). Paths are collected from the
 * sources: string literals handed to `adminGet`, `adminFetch` and `adminApi`.
 * Interpolations and `{param}` templates both compare as a single wildcard.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("../src", import.meta.url));
const OPENAPI = fileURLToPath(new URL("../../docs/admin-api.openapi.json", import.meta.url));

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((e) => {
    const full = join(dir, e);
    return statSync(full).isDirectory() ? files(full) : [full];
  });
}

/** `/admin/models/${key}/test?x=1` and `/admin/models/{key}/test` both → `/admin/models/*\/test`. */
export function normalise(path: string): string {
  // An interpolation glued to the previous segment (`/admin/models${query}`) is
  // a query-string suffix, not a path segment: drop it. One after a "/" is a
  // path parameter: a wildcard.
  const bare = path
    .replace(/(?<!\/)\$\{[^}]*\}/g, "")
    .replace(/\$\{[^}]*\}/g, "*")
    .split("?")[0]!
    .replace(/\{[^}]*\}/g, "*");
  return ("/" + bare.replace(/^\/+/, "")).replace(/^\/(?!admin\/)/, "/admin/").replace(/\/+$/, "");
}

export function usedPaths(): string[] {
  const sources = [join(SRC, "lib/admin"), join(SRC, "components/admin"), join(SRC, "app/admin")]
    .filter(existsSync)
    .flatMap(files)
    .filter((f) => /\.(ts|tsx)$/.test(f));
  const found = new Set<string>();
  const patterns = [
    // Template literals may contain quotes inside `${…}`, so they are matched to the closing backtick.
    /adminGet(?:<[^>]*>)?\(\s*(?:`([^`]+)`|"([^"]+)")/g,
    /adminFetch\(\s*(?:`(\/admin\/[^`]+)`|"(\/admin\/[^"]+)")/g,
    /adminApi(?:<[^>]*>)?\(\s*"[A-Z]+",\s*(?:`([^`]+)`|"([^"]+)")/g,
  ];
  for (const f of sources) {
    const body = readFileSync(f, "utf8");
    for (const re of patterns) {
      for (const m of body.matchAll(re)) {
        const raw = (m[1] ?? m[2])!;
        // A path built from a variable cannot be checked; refuse it so every call stays auditable.
        if (raw.startsWith("${")) throw new Error(`${f}: admin API path must start with a literal "/admin/…", got ${raw}`);
        found.add(normalise(raw));
      }
    }
  }
  return [...found].sort();
}

describe("the admin console calls only routes the API publishes", () => {
  it("normalises interpolations and templates alike", () => {
    expect(normalise("/admin/models/${encodeURIComponent(key)}/test?x=1")).toBe("/admin/models/*/test");
    expect(normalise("models/{key}/test")).toBe("/admin/models/*/test");
    expect(normalise('/admin/models${archived ? "?include_archived=true" : ""}')).toBe("/admin/models");
  });

  it("finds the paths it uses", () => {
    expect(usedPaths()).toContain("/admin/system");
  });

  // B1 publishes the dump; before it merges there is nothing to compare with.
  it.skipIf(!existsSync(OPENAPI))("every used path exists in docs/admin-api.openapi.json", () => {
    const spec = JSON.parse(readFileSync(OPENAPI, "utf8")) as { paths: Record<string, unknown> };
    const published = new Set(Object.keys(spec.paths).map(normalise));
    const missing = usedPaths().filter((p) => !published.has(p));
    expect(missing, "paths used by lib/admin that the API does not publish").toEqual([]);
  });
});
