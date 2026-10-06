/**
 * The route map, checked against the filesystem and the sources.
 *
 * ⚠ THIS TEST EXISTS BECAUSE THE FAILURES IT GUARDS ARE SILENT. The site
 * collapsed to a single landing (`/`, the by-major grid) plus the drill-down,
 * the recommendation flow, how-we-test and the per-model and per-run detail.
 * Four pages were removed outright — `/overview`, `/leaderboard`, `/compare`
 * and the `/runs` browse list. A link still pointing at one of them does not
 * crash and does not 404 at build time; it just hands a professor a dead click.
 * So this reads every source and fails if a removed route is still linked, or a
 * kept one has gone missing.
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
    // no path segment. `(site)/recommend` is served at `/recommend`.
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

/** The routes removed in the single-page redesign. Nothing may link to one. */
const REMOVED_ROUTES = ["/overview", "/leaderboard", "/compare"];

describe("the single-page route map", () => {
  it("serves the landing at /, inside the (site) chrome", () => {
    expect(ROUTES).toContain("/");
    // The landing lives in the route group now, so it shares the one quiet
    // header rather than bringing its own masthead.
    expect(SOURCES.some(([path]) => path === "(site)/page.tsx")).toBe(true);
  });

  it("keeps every surviving tool page reachable", () => {
    for (const route of [
      "/recommend",
      "/methodology",
      "/models/[key]",
      "/runs/[runId]",
      "/explore/[major]",
      "/explore/[major]/[course]",
      "/explore/[major]/[course]/[slo]",
    ]) {
      expect(ROUTES, `lost ${route}`).toContain(route);
    }
  });

  it("removes the overview, leaderboard, compare and runs-browse pages", () => {
    for (const route of [...REMOVED_ROUTES, "/runs"]) {
      expect(ROUTES, `${route} should have been deleted`).not.toContain(route);
    }
  });

  it("adds no path segment for the (site) route group", () => {
    expect(ROUTES.some((route) => route.includes("(site)"))).toBe(false);
  });
});

describe("no source links a removed route", () => {
  it.each(SOURCES)("%s links no deleted page", (path, body) => {
    for (const route of REMOVED_ROUTES) {
      // A link target, not a prose mention in a comment: `href="/compare"`,
      // `href={`/leaderboard?...`}`, or a nav `href: "/overview"`.
      const linked =
        body.includes(`href="${route}"`) ||
        body.includes(`href={\`${route}`) ||
        body.includes(`href: "${route}"`);
      expect(linked, `${path} still links ${route}`).toBe(false);
    }
  });

  it("links no bare /runs browse list (the single-run receipt stays)", () => {
    for (const [path, body] of SOURCES) {
      // `/runs/<id>` is the kept receipt; a link to the removed browse list is
      // `href="/runs"` or `href={`/runs?...`}` with nothing after `/runs`.
      expect(body, `${path} links the removed /runs browse list`).not.toMatch(
        /href=(?:"\/runs"|\{`\/runs(?:\?|`))/,
      );
    }
  });

  it("deep-links no task at / (the old catalogue query string)", () => {
    for (const [path, body] of SOURCES) {
      expect(body, `${path} still deep-links tasks at /`).not.toMatch(/href=\{`\/\?task=/);
    }
  });
});

describe("the chrome sits below the landing", () => {
  it("keeps the wordmark, version badge, and a footer route to methodology", () => {
    const site = SOURCES.find(([path]) => path.startsWith("(site)") && path.endsWith("layout.tsx"));
    expect(site).toBeDefined();
    const body = site![1];
    expect(body).toContain("resolveVersion");
    // The wordmark doubles as the way home.
    expect(body).toContain('href="/"');
    // "How we test" survives in the footer, not the removed top nav.
    expect(body).toContain('href="/methodology"');
  });

  it("drops the old top nav — no NAV array, no chrome link to /recommend", () => {
    const body = SOURCES.find(
      ([path]) => path.startsWith("(site)") && path.endsWith("layout.tsx"),
    )![1];
    // The old top nav was a `NAV = [{ href: "/", label: ... }]` array. Its
    // object-literal `href:` entries are the tell that it is back.
    expect(body, "the top-nav NAV array is back in the layout").not.toMatch(/href:\s*"/);
    // "Help me choose" is now the landing's own CTA, so the chrome links
    // neither it nor the old "Explore" self-link.
    expect(body, "the chrome still links /recommend").not.toContain("/recommend");
  });

  it("keeps the nav out of the root layout, and the fonts in it", () => {
    const root = SOURCES.find(([path]) => path === "layout.tsx")![1];
    expect(root).not.toContain("<nav");
    expect(root).not.toContain("resolveVersion");
    // The CSS consumes these variable names; renaming one drops the type stack
    // silently, which no other test would catch.
    expect(root).toContain("--font-display");
    expect(root).toContain("--font-body");
  });
});
