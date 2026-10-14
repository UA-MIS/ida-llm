/**
 * The tool-page chrome, rendered.
 *
 * ⚠ ONE LANDING, NO TOP NAV. The client asked for a true single landing page:
 * the landing (`/`) IS explore, so a top nav offering "Explore / How we test /
 * Help me choose" was three doors competing with the page itself. The top nav
 * is gone. What is left reachable without it: "Help me choose" is the standing
 * button on the landing, and "How we test" (`/methodology`) moves to the
 * footer. The header keeps only the wordmark home link.
 *
 * ⚠ QA-25 STILL HOLDS. `<header>` (and now `<footer>`) must stay SIBLINGS of
 * `<main>`, never descendants — a `<header>`/`<footer>` only earns its
 * `banner`/`contentinfo` landmark role when it is NOT inside
 * `article`/`aside`/`main`/`nav`/`section`. The skip link stays the first
 * focusable thing on the page.
 */

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

const { default: SiteLayout } = await import("@/app/(site)/layout");

afterEach(() => {
  cleanup();
});

describe("the tool-page chrome's landmarks", () => {
  it("keeps <header> and <footer> as siblings of <main>, not descendants", () => {
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const main = container.querySelector("main");
    expect(main, "no <main> rendered").not.toBeNull();
    expect(main!.querySelector("header"), "header nested inside main").toBeNull();
    expect(main!.querySelector("footer"), "footer nested inside main").toBeNull();
    expect(container.querySelector("header")).not.toBeNull();
    expect(container.querySelector("footer")).not.toBeNull();
  });

  it("renders the page content inside <main id=\"main-content\">", () => {
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
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const skipLink = container.querySelector("a.skip-link");
    expect(skipLink, "no skip link rendered").not.toBeNull();
    expect(skipLink!.getAttribute("href")).toBe("#main-content");
  });
});

describe("the header has no top nav, only the wordmark", () => {
  it("keeps the Coursework Benchmark brand as a link home", () => {
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const header = container.querySelector("header")!;
    const home = Array.from(header.querySelectorAll("a")).find(
      (a) => a.getAttribute("href") === "/",
    );
    expect(home, "no brand home link in the header").toBeTruthy();
    expect(home!.textContent).toContain("Coursework Benchmark");
  });

  it("renders no navigation links in the header", () => {
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const header = container.querySelector("header")!;
    // A <nav> landmark inside the header is exactly the top nav we removed.
    expect(header.querySelector("nav"), "a <nav> is back in the header").toBeNull();

    const labels = Array.from(header.querySelectorAll("a")).map((a) =>
      a.textContent?.trim(),
    );
    expect(labels).not.toContain("Explore");
    expect(labels).not.toContain("How we test");
    expect(labels).not.toContain("Help me choose");
  });

  it("offers no Explore link anywhere in the chrome", () => {
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const labels = Array.from(container.querySelectorAll("a")).map((a) =>
      a.textContent?.trim(),
    );
    expect(labels).not.toContain("Explore");
  });
});

describe("the footer keeps How-we-test reachable", () => {
  it("links How we test to /methodology from the footer", () => {
    const { container } = render(
      <SiteLayout>
        <p>page content</p>
      </SiteLayout>,
    );

    const footer = container.querySelector("footer")!;
    const methodology = Array.from(footer.querySelectorAll("a")).find(
      (a) => a.getAttribute("href") === "/methodology",
    );
    expect(methodology, "no /methodology link in the footer").toBeTruthy();
    expect(methodology!.textContent).toContain("How we test");
  });
});
