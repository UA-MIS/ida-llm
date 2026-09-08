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
  const re = /import\s*\{([^}]*)\}\s*from\s*["']([^"']+)["']/g;
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

const { default: LandingPage } = await import("@/app/page");
const { default: OverviewPage } = await import("@/app/overview/page");
const { default: LeaderboardPage } = await import("@/app/(site)/leaderboard/page");
const { default: ComparePage } = await import("@/app/(site)/compare/page");
const { default: ModelReportPage } = await import("@/app/(site)/models/[key]/page");
const { default: ExplorePage } = await import("@/app/(site)/explore/page");
const { default: ClassesPage } = await import("@/app/(site)/explore/[major]/page");
const { default: OutcomesPage } = await import("@/app/(site)/explore/[major]/[course]/page");
const { default: EvidencePage } = await import(
  "@/app/(site)/explore/[major]/[course]/[slo]/page"
);

// The major that owns MIS 200 in `fixtures.ts`, and the class that claims the
// `slo2` family the seeded board below files its one result under. Both halves
// matter: a class that claimed no family would render an honest grid of dashes,
// the page would have no seeded score to disclose, and this guard would go
// green having proved nothing.
const MAJOR = "management-information-systems";
const CLASS = "mis-200";

/** One model, one task, entirely seeded — the shape every route must disclose. */
function seededBoard() {
  return board([
    task({
      task_id: "slo2/break-even",
      // ⚠ THE FAMILY MIS 200 CLAIMS. `/explore` attributes a result to a class
      // by task family, so a fixture whose family nothing claims would render
      // every level empty and make this whole guard vacuous.
      family: "slo2",
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
    route: "/",
    render: () => LandingPage(),
    // The front door doesn't badge a seeded finding — `lib/specimen.ts`
    // excludes a demonstration row from "the strongest measured result"
    // outright, so its own promise ("a number appears only when a real
    // finished run stands behind it") stays literally true. Disclosure here
    // means no verdict renders at all. See `specimen.test.ts`.
    assert: (root) => {
      expect(
        root.querySelector(".ld-verdict"),
        "the landing page rendered a Measured verdict from an all-seeded board",
      ).toBeNull();
    },
  },
  { route: "/overview", render: () => OverviewPage(), assert: assertIllustrative },
  {
    route: "/leaderboard",
    render: () => LeaderboardPage({ searchParams: Promise.resolve({}) }),
    assert: assertIllustrative,
  },
  { route: "/compare", render: () => ComparePage(), assert: assertIllustrative },
  {
    route: "/models/[key]",
    render: () => ModelReportPage({ params: Promise.resolve({ key: "luna" }) }),
    assert: assertIllustrative,
  },
  { route: "/explore", render: () => ExplorePage(), assert: assertIllustrative },
  {
    route: "/explore/[major]",
    render: () => ClassesPage({ params: Promise.resolve({ major: MAJOR }) }),
    assert: assertIllustrative,
  },
  {
    route: "/explore/[major]/[course]",
    render: () =>
      OutcomesPage({ params: Promise.resolve({ major: MAJOR, course: CLASS }) }),
    assert: assertIllustrative,
  },
  {
    route: "/explore/[major]/[course]/[slo]",
    render: () =>
      EvidencePage({
        params: Promise.resolve({ major: MAJOR, course: CLASS, slo: "slo2" }),
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

describe("the guard's own assertions are not vacuous", () => {
  it("assertIllustrative actually fails on content that discloses nothing", () => {
    const div = document.createElement("div");
    div.textContent = "0.72, ranked #1 of 4 models measured";
    expect(() => assertIllustrative(div)).toThrow();
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
