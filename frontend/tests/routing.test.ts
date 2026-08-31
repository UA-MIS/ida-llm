/**
 * The route map, checked against the filesystem and the sources.
 *
 * ⚠ THIS TEST EXISTS BECAUSE THE MOVE IT GUARDS IS SILENT WHEN IT BREAKS. `/`
 * became the landing page and the leaderboard moved to `/leaderboard`. Every
 * link that still points at `/` expecting a table now lands a professor on the
 * pitch instead — and nothing crashes, nothing 404s, no type fails. The page
 * just quietly shows the wrong thing to the visitor who had already decided to
 * trust us enough to click.
 *
 * Reading the sources rather than rendering them is deliberate: this is a claim
 * about every route at once, and there is no component to render that would
 * make it.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const APP = fileURLToPath(new URL("../src/app", import.meta.url));

/** Every `page.tsx` under src/app, as the URL path Next will serve it at. */
function routes(dir = APP, prefix = ""): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (!statSync(full).isDirectory()) {
      if (entry === "page.tsx") found.push(prefix === "" ? "/" : prefix);
      continue;
    }
    // A parenthesised directory is a route GROUP: it adds a layout boundary and
    // no path segment. `(site)/leaderboard` is served at `/leaderboard`.
    const segment = /^\(.*\)$/.test(entry) ? "" : `/${entry}`;
    found.push(...routes(full, prefix + segment));
  }
  return found;
}

/** Every .tsx under src/app, with its repo-relative path. */
function sources(dir = APP, acc: [string, string][] = []): [string, string][] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) sources(full, acc);
    else if (entry.endsWith(".tsx")) acc.push([full.slice(APP.length + 1), readFileSync(full, "utf8")]);
  }
  return acc;
}

const ROUTES = routes();
const SOURCES = sources();

describe("the route map after the landing-page move", () => {
  it("serves the landing at /", () => {
    expect(ROUTES).toContain("/");
  });

  it("serves the leaderboard at /leaderboard, not at /", () => {
    expect(ROUTES).toContain("/leaderboard");
  });

  it("keeps the dashboard and every other tool page reachable", () => {
    // The report card and the run detail are the dense views the landing's
    // primary door promises. Losing one in a directory move is the easiest way
    // for this change to do real damage.
    for (const route of ["/models/[key]", "/runs", "/runs/[runId]", "/recommend", "/compare"]) {
      expect(ROUTES, `lost ${route}`).toContain(route);
    }
  });

  it("adds no path segment for the (site) route group", () => {
    expect(ROUTES.some((route) => route.includes("(site)"))).toBe(false);
  });
});

describe("no link points at / expecting the leaderboard", () => {
  /** The landing is `/`; only a wordmark or a "home" link may target it. */
  const HOME_LINK_OK = /className="ld-logo"|color: "inherit"/;

  it.each(SOURCES.filter(([, body]) => body.includes('href="/"')))(
    "%s only uses href=\"/\" for a home link",
    (_path, body) => {
      for (const line of body.split("\n")) {
        if (!line.includes('href="/"')) continue;
        expect(HOME_LINK_OK.test(line), `bare href="/" here: ${line.trim()}`).toBe(true);
      }
    },
  );

  it("routes every task deep-link through /leaderboard", () => {
    // `/?task=…` was how the catalogue linked into a single task. Left alone it
    // now opens the landing page with an ignored query string.
    for (const [path, body] of SOURCES) {
      expect(body, `${path} still deep-links tasks at /`).not.toMatch(/href=\{`\/\?task=/);
    }
  });

  it("submits the leaderboard's filter form to /leaderboard", () => {
    const leaderboard = SOURCES.find(([path]) => path.endsWith("leaderboard/page.tsx"));
    expect(leaderboard).toBeDefined();
    // A GET form still posting to "/" would drop the professor on the pitch
    // every time they applied a filter.
    expect(leaderboard![1]).toContain('action="/leaderboard"');
    expect(leaderboard![1]).not.toContain('action="/"');
  });
});

describe("the chrome sits below the landing, not above it", () => {
  it("keeps the app header out of the root layout", () => {
    const root = SOURCES.find(([path]) => path === "layout.tsx")![1];
    // The landing is full-bleed and brings its own masthead. If the nav returns
    // to the root layout, every landing visitor gets two headers.
    expect(root).not.toContain("<nav");
    expect(root).not.toContain("resolveVersion");
  });

  it("puts the header, nav and version badge in the (site) layout", () => {
    const site = SOURCES.find(([path]) => path.startsWith("(site)") && path.endsWith("layout.tsx"));
    expect(site).toBeDefined();
    expect(site![1]).toContain("<nav");
    expect(site![1]).toContain("resolveVersion");
    // And its nav names the real paths.
    expect(site![1]).toContain('href: "/leaderboard"');
    // The grid is a top-level destination; if it is only reachable from a link
    // buried in the leaderboard's browse panel, almost nobody will find it.
    expect(site![1]).toContain('href: "/compare"');
  });

  it("loads both landing typefaces from the root layout", () => {
    const root = SOURCES.find(([path]) => path === "layout.tsx")![1];
    // The CSS consumes these variable names; renaming one drops the landing
    // silently back to the fallback stack, which is a visual-only regression no
    // other test would catch.
    expect(root).toContain("--font-display");
    expect(root).toContain("--font-body");
  });
});
