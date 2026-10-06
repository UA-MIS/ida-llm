/**
 * The tool-page chrome, rendered.
 *
 * ⚠ QA-25. `<header>` and `<nav>` used to live inside `<main>`, which strips
 * `<header>` of its implicit `banner` landmark role (HTML-AAM: `header` is
 * `banner` only when it is NOT a descendant of `article`/`aside`/`main`/
 * `nav`/`section`) — so neither the page's own chrome nor its one piece of
 * real content had a landmark role a screen-reader user could jump to. There
 * was also no skip link, and no visual or semantic way to tell which nav item
 * was the current page.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const usePathname = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ usePathname }));

const { default: SiteLayout } = await import("@/app/(site)/layout");

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the tool-page chrome's landmarks", () => {
  it("keeps <header> and <nav> as siblings of <main>, not descendants", () => {
    usePathname.mockReturnValue("/leaderboard");
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const main = container.querySelector("main");
    expect(main, "no <main> rendered").not.toBeNull();
    expect(main!.querySelector("header"), "header nested inside main").toBeNull();
    expect(main!.querySelector("nav"), "nav nested inside main").toBeNull();
    expect(container.querySelector("header")).not.toBeNull();
    expect(container.querySelector("nav")).not.toBeNull();
  });

  it("renders the page content inside <main id=\"main-content\">", () => {
    usePathname.mockReturnValue("/leaderboard");
    const { container, getByText } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const main = container.querySelector("main")!;
    expect(main.id).toBe("main-content");
    expect(main.contains(getByText("page content"))).toBe(true);
  });

  it("puts a skip link first, pointing at the main content", () => {
    usePathname.mockReturnValue("/leaderboard");
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const skipLink = container.querySelector("a.skip-link");
    expect(skipLink, "no skip link rendered").not.toBeNull();
    expect(skipLink!.getAttribute("href")).toBe("#main-content");
  });

  it("marks the current nav item with aria-current, and no other", () => {
    usePathname.mockReturnValue("/methodology");
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const links = Array.from(container.querySelectorAll("nav a"));
    const current = links.filter((a) => a.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]!.getAttribute("href")).toBe("/methodology");
  });

  it("marks nothing current on a route with no matching nav item", () => {
    usePathname.mockReturnValue("/models/luna");
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const links = Array.from(container.querySelectorAll("nav a"));
    expect(links.some((a) => a.getAttribute("aria-current") === "page")).toBe(false);
  });
});
