/**
 * Questions, answers and the answer key must never reach a browser.
 *
 * ⚠ SECURITY-TOUCHING. We cannot publish the benchmark's prompts, the models'
 * answers or the gold answers: a published key stops measuring anything once it
 * is scraped. The public ingress serves ONLY this frontend (`path: /`), so every
 * route and every rendered field here is world-readable. These checks read the
 * sources for the same reason `routing.test.ts` does: the claim is about every
 * route at once.
 *
 * The leaks this pins closed:
 *  - `/api/runs/{run}/results/{sample}/transcript` — a same-origin proxy that
 *    returned the full prompt, completion and raw provider response.
 *  - the transcript viewer on the evidence page that called it.
 *  - the evidence page's "Explanation" column: `score.explanation` carries
 *    "got 'X', want 'Y'" (the answer AND the gold answer) for programmatic
 *    scorers and the judge's quoted rationale for rubric ones.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("../src", import.meta.url));

function files(dir = SRC): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    return statSync(full).isDirectory() ? files(full) : [full];
  });
}

const ALL = files().filter((f) => /\.(ts|tsx)$/.test(f));
const read = (f: string) => readFileSync(f, "utf8");
/** Source with comments stripped, so prose explaining the ban cannot trip it. */
const code = (f: string) => read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("no question/answer content is reachable from the public frontend", () => {
  it("has no route handler except the two ops endpoints", () => {
    const handlers = ALL.filter((f) => /\/route\.ts$/.test(f)).map((f) => f.slice(SRC.length));
    expect(handlers.sort()).toEqual(["/app/api/healthz/route.ts", "/app/api/metrics/route.ts"]);
  });

  it("has no transcript proxy, viewer or fetcher left", () => {
    expect(existsSync(join(SRC, "app/api/runs"))).toBe(false);
    for (const f of ALL) {
      expect(code(f), `${f} still touches transcripts`).not.toMatch(
        /getTranscript|SampleTranscript|<Transcript\b|\/transcript\b/,
      );
    }
  });

  it("ships no client component that is handed run content", () => {
    const clients = ALL.filter((f) => /^\s*["']use client["']/.test(read(f))).map((f) => f.slice(SRC.length));
    // The theme toggle and the error boundary hold no data. A new entry here
    // needs a deliberate look at what props cross the server/client boundary.
    expect(clients.sort()).toEqual(["/app/error.tsx", "/components/theme-toggle.tsx"]);
  });

  it("never renders a scorer's or judge's explanation, or a per-sample error string", () => {
    for (const f of ALL.filter((p) => p.endsWith(".tsx"))) {
      const body = code(f);
      expect(body, `${f} renders score.explanation`).not.toMatch(/\.explanation\b/);
      expect(body, `${f} renders score.details`).not.toMatch(/score\??\.details|\.criteria\b/);
      expect(body, `${f} renders a raw sample error`).not.toMatch(/result\.error\b(?!\s*[!=]==?\s*null)/);
      expect(body, `${f} renders raw_response/completion/messages`).not.toMatch(
        /raw_response|\.completion\b|\.messages\b/,
      );
    }
  });
});
