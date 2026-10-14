/**
 * The structural guard: a score-rendering page cannot ship without disclosing
 * a seeded row.
 *
 * ⚠ WHY THIS FILE EXISTS. Gap #69 (`9ec394a`) hand-added the demonstration
 * caveat to `/leaderboard`, `/compare` and `/models/[key]`, one page at a
 * time, with a DOM test per page. It shipped with no guard against a FOURTH
 * page doing the same thing — and `/explore/[major]/[course]` did exactly
 * that: real code, real tests everywhere else, one route quietly skipped. A
 * per-page test only proves the page it was written for; it says nothing
 * about the next one. This file is the thing that would have caught both.
 *
 * ⚠ TWO INDEPENDENT LAYERS, ON PURPOSE:
 *
 *   1. STATIC — `getLeaderboard()` is the only place in this codebase a
 *      `ModelResult` (and its per-row `demonstration` flag) enters the
 *      frontend at all; `RunRecord`/`ResultRecord` behind `/runs` carry no
 *      such flag, which is why those pages are correctly absent below. Every
 *      `page.tsx` under `src/app` that imports `getLeaderboard` is discovered
 *      by walking the filesystem — nobody has to remember to list it.
 *   2. RUNTIME — the REGISTRY below renders each discovered route against an
 *      all-seeded board and asserts it actually shows the disclosure a reader
 *      would see. `it("keeps the registry in step...")` cross-checks the
 *      REGISTRY's route list against layer 1's discovery, so a new page that
 *      calls `getLeaderboard()` without a REGISTRY entry fails immediately —
 *      it cannot silently sit outside the guard the way the course page did.
 *
 * A new page therefore has exactly two ways to go red here: skip the
 * registry (layer 2 catches it), or register it and skip the disclosure
 * (layer 3, further down, catches it). Neither failure requires anyone to
 * have remembered this file exists.
 *
 * ⚠ THE DEV-PREVIEW EXEMPTION, AND WHY IT DOES NOT WEAKEN THE INVARIANT. The
 * dev demo deployment fills the grid with seeded rows on purpose, and the human
 * does not want the per-row/column/banner tells shouting "illustrative" on a
 * preview everyone already knows is illustrative. So the tells are suppressed —
 * but ONLY when `IDA_DEMO_CURRICULUM=1`, the gate that only the dev overlay
 * sets (see `lib/preview.ts`). The true contract is therefore sharper than
 * "every seeded row discloses": it is "every PROD-REACHABLE seeded row
 * discloses, and the provably-dev-only preview may read clean". Both halves are
 * pinned below — layer 3 renders with the gate OFF (prod-reachable) and demands
 * the disclosure; layer 4 renders the SAME routes with the gate ON and demands
 * they come up clean. Suppress a prod banner by hand and layer 3 fails; leak a
 * tell into the dev preview and layer 4 fails.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { board, result, task } from "./fixtures";

/* -------------------------------------------------------------------------- */
/* Layer 1 — discover every route that can carry a seeded score               */
/* -------------------------------------------------------------------------- */

// `import.meta.dirname` (this file's own directory, `frontend/tests`) rather
// than `import.meta.url` + `fileURLToPath` — vitest's module runner does not
// always hand test files a `file://` URL, and `dirname` sidesteps that.
const PROJECT_ROOT = join(import.meta.dirname, "..");
const APP_DIR = join(PROJECT_ROOT, "src", "app");

function findPageFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      findPageFiles(full, out);
    } else if (entry === "page.tsx") {
      out.push(full);
    }
  }
  return out;
}

interface ImportSpec {
  module: string;
  names: string[];
}

/**
 * A deliberately narrow import parser: named imports only (`import { a, b }
 * from "..."`), which is the only form this codebase uses for `getLeaderboard`
 * and every disclosure primitive it is paired with (`grep -n "^import"
 * src/app/**\/page.tsx` has no default- or namespace-import counterexample).
 * A page written in a shape this cannot parse fails LOUD (zero imports found,
 * so it reads as out of scope) rather than silently — `it("parses every real
 * page.tsx without finding zero imports")` below is what catches that.
 */
function parseNamedImports(source: string): ImportSpec[] {
  const out: ImportSpec[] = [];
  // `import { … }` and `import type { … }` both — a page whose only brace
  // import is a type-only `import type { Metadata }` must still read as parsed,
  // or the "no zero imports" guard below flags it as unparseable.
  const re = /import\s+(?:type\s+)?\{([^}]*)\}\s*from\s*["']([^"']+)["']/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source))) {
    const names = m[1]!
      .split(",")
      .map((s) => s.trim().split(/\s+as\s+/)[0]!.trim())
      .filter(Boolean);
    out.push({ module: m[2]!, names });
  }
  return out;
}

function fetchesLeaderboard(imports: ImportSpec[]): boolean {
  return imports.some((i) => i.module === "@/lib/api" && i.names.includes("getLeaderboard"));
}

/** `src/app/(site)/explore/[major]/[course]/page.tsx` → `/explore/[major]/[course]`. */
function routeFromPageFile(file: string): string {
  let rel = file.slice(APP_DIR.length).replace(/\\/g, "/");
  rel = rel.replace(/\/page\.tsx$/, "");
  // Route groups — `(site)` — are a Next.js organisational device and are not
  // part of the URL, so they must not be part of the route this test names.
  rel = rel.replace(/\/\([^/]+\)/g, "");
  return rel === "" ? "/" : rel;
}

function discoverScoreRoutes(): string[] {
  return findPageFiles(APP_DIR)
    .filter((file) => fetchesLeaderboard(parseNamedImports(readFileSync(file, "utf8"))))
    .map(routeFromPageFile)
    .sort();
}

/* -------------------------------------------------------------------------- */
/* Layer 2/3 — render every discovered route against seeded data              */
/* -------------------------------------------------------------------------- */

const getLeaderboard = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  getLeaderboard,
  ApiError: class ApiError extends Error {},
}));

const { default: LandingPage } = await import("@/app/(site)/page");
const { default: ModelReportPage } = await import("@/app/(site)/models/[key]/page");
const { default: ClassesPage } = await import("@/app/(site)/explore/[major]/page");
const { default: ClassPage } = await import("@/app/(site)/explore/[major]/[course]/page");
const { default: EvidencePage } = await import(
  "@/app/(site)/explore/[major]/[course]/[slo]/page"
);

// The major that owns MIS 200 in `fixtures.ts`, the class that claims the
// `mis200-is-concepts` family the seeded board below files its one result
// under, and the content category that claims that family. All three matter: a
// class that claimed no family, or a category whose family nothing scored,
// would render an honest grid of dashes — the page would have no seeded score
// to disclose, and this guard would go green having proved nothing.
const MAJOR = "management-information-systems";
const CLASS = "mis-200";
const CATEGORY = "information-systems-business-models";

/** One model, one task, entirely seeded — the shape every route must disclose. */
function seededBoard() {
  return board([
    task({
      task_id: "mis200-is-concepts/l1-core",
      // ⚠ THE FAMILY MIS 200 CLAIMS, AND THE ONE THE "IS concepts" CATEGORY
      // MAPS TO. `/explore` attributes a result to a class by task family and
      // the class page buckets those families into content categories, so a
      // fixture whose family nothing claims would render every level empty and
      // make this whole guard vacuous.
      family: "mis200-is-concepts",
      slo: "SLO2",
      has_results: true,
      best_model_key: "luna",
      results: [
        result({
          model_key: "luna",
          display_name: "Luna",
          mean_score: 0.72,
          scored_count: 20,
          sample_count: 20,
          demonstration: true,
        }),
      ],
    }),
  ]);
}

/** The shared shape: somewhere on the page, the same words every disclosing page uses. */
function assertIllustrative(root: HTMLElement) {
  expect(
    root.textContent,
    "an all-seeded board rendered no 'illustrative' disclosure anywhere on the page",
  ).toMatch(/illustrative/i);
}

/** The dev-preview shape: the SAME all-seeded board, rendered clean. */
function assertClean(root: HTMLElement) {
  expect(
    root.textContent,
    "the dev preview still painted an 'illustrative' tell the human asked to suppress",
  ).not.toMatch(/illustrative/i);
  // …and the page did not go clean by rendering nothing: the grid is still here.
  expect(root.textContent?.length ?? 0, "the dev preview rendered an empty page").toBeGreaterThan(0);
}

/**
 * Every route `discoverScoreRoutes()` can find today, with how to render it
 * and what "it disclosed" looks like there.
 *
 * ⚠ THIS TABLE IS NOT THE GUARD; `discoverScoreRoutes()` is. This only teaches
 * the guard, for each route IT found, how to drive that specific page — the
 * "keeps the registry in step" test below is what stops this table from being
 * able to quietly fall behind the filesystem.
 */
const REGISTRY: {
  route: string;
  render: () => Promise<React.ReactElement>;
  assert: (root: HTMLElement) => void;
}[] = [
  {
    // The front door is the by-major grid now, so it discloses exactly the way
    // every other grid does — the page-level "some figures are illustrative"
    // notice above the matrix.
    route: "/",
    render: () => LandingPage(),
    assert: assertIllustrative,
  },
  {
    route: "/models/[key]",
    render: () => ModelReportPage({ params: Promise.resolve({ key: "luna" }) }),
    assert: assertIllustrative,
  },
  {
    route: "/explore/[major]",
    render: () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }),
    assert: assertIllustrative,
  },
  {
    route: "/explore/[major]/[course]",
    render: () => ClassPage({ params: Promise.resolve({ major: MAJOR, course: CLASS }) }),
    assert: assertIllustrative,
  },
  {
    // Drilled to one content category's evidence — the page that replaced the
    // SLO breakdown. It must disclose a seeded score the same as every level
    // above it.
    route: "/explore/[major]/[course]/[slo]",
    render: () =>
      EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: CLASS, slo: CATEGORY }),
      }),
    assert: assertIllustrative,
  },
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("every page that fetches the leaderboard is registered", () => {
  it("keeps the registry in step with what the filesystem actually finds", () => {
    // If this fails, either a new page.tsx started calling getLeaderboard()
    // and needs a REGISTRY entry above (with an assertion for what disclosure
    // looks like on it), or a REGISTRY entry has gone stale. Either way, the
    // fix is to make the two sides agree — never to delete this test.
    expect(discoverScoreRoutes()).toEqual(REGISTRY.map((e) => e.route).sort());
  });

  it("parses every real page.tsx without finding zero imports", () => {
    // Guards the parser itself: a page written with default/namespace imports
    // only would make `parseNamedImports` return `[]`, which reads as "fetches
    // nothing" and would silently drop that page out of layer 1 entirely.
    for (const file of findPageFiles(APP_DIR)) {
      expect(parseNamedImports(readFileSync(file, "utf8")).length, file).toBeGreaterThan(0);
    }
  });
});

describe("every registered route discloses an all-seeded board", () => {
  for (const entry of REGISTRY) {
    it(`discloses on ${entry.route}`, async () => {
      getLeaderboard.mockResolvedValue(seededBoard());
      const { container } = render(await entry.render());
      entry.assert(container.ownerDocument.body);
    });
  }
});

/* -------------------------------------------------------------------------- */
/* Layer 4 — the dev preview reads clean, without weakening prod               */
/* -------------------------------------------------------------------------- */

describe("the dev preview suppresses the tells it is exempt from", () => {
  // ⚠ ONLY THE GATE THE DEV OVERLAY SETS. `IDA_DEMO_CURRICULUM=1` is the one
  // signal `lib/preview.ts` keys off; prod and staging never set it, so the
  // block above (which runs with it unset) is the prod-reachable case and this
  // is the dev-only one. Same seeded board, same routes — only the environment
  // differs.
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  for (const entry of REGISTRY) {
    it(`reads clean on ${entry.route} under the dev gate`, async () => {
      vi.stubEnv("IDA_DEMO_CURRICULUM", "1");
      getLeaderboard.mockResolvedValue(seededBoard());
      const { container } = render(await entry.render());
      assertClean(container.ownerDocument.body);
    });
  }
});

describe("the guard's own assertions are not vacuous", () => {
  it("assertIllustrative actually fails on content that discloses nothing", () => {
    const div = document.createElement("div");
    div.textContent = "0.72, ranked #1 of 4 models measured";
    expect(() => assertIllustrative(div)).toThrow();
  });

  it("assertClean actually fails on content that still shows a tell, and on an empty page", () => {
    const tell = document.createElement("div");
    tell.textContent = "Some figures here are illustrative.";
    expect(() => assertClean(tell)).toThrow();

    const empty = document.createElement("div");
    empty.textContent = "";
    expect(() => assertClean(empty)).toThrow();
  });

  it("the static detector flags a synthetic page that fetches scores and discloses nothing", () => {
    const guiltyPage = `
      import { getLeaderboard } from "@/lib/api";
      import { ExploreTile } from "@/components/explore-tile";

      export default async function GuiltyPage() {
        const board = await getLeaderboard();
        return <ExploreTile aggregate={board.tasks[0].results[0]} />;
      }
    `;
    expect(fetchesLeaderboard(parseNamedImports(guiltyPage))).toBe(true);

    const innocentPage = `
      import { getRun, listRuns } from "@/lib/api";
      export default async function RunsPage() {
        return null;
      }
    `;
    expect(fetchesLeaderboard(parseNamedImports(innocentPage))).toBe(false);
  });
});
