import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";

/**
 * The product chrome: a quiet wordmark header, the column every page reads
 * inside, and a thin footer. The landing lives in this group too, so the whole
 * site shares one header.
 *
 * ⚠ NO TOP NAV, DELIBERATELY. The client asked for a true single landing page.
 * The old nav offered three front doors — "Explore / How we test / Help me
 * choose" — competing with the landing itself, and the client's verdict was
 * "too much information, too many clicks, too many options". So there is no top
 * nav. The three destinations are still reachable, just not as nav items:
 * "Explore" was only ever the landing (`/`), which IS the by-major grid you
 * drill, so it needs no link to itself; "Help me choose" is the standing CTA on
 * the landing; and "How we test" (`/methodology`) moves to the footer below —
 * reachable for anyone who wants it, out of the way of the professor who does
 * not. The header keeps only the wordmark, which doubles as the way home.
 */
export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      {/* ⚠ QA-25. The first focusable thing on every tool page, invisible
          until it is focused (`.skip-link` in globals.css) — so a keyboard
          user lands straight on the content they came for. It predates the nav
          removal and still earns its place: it skips the wordmark header and,
          on the drill-down, the breadcrumb trail each page renders. */}
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      {/* ⚠ QA-25: `<header>` (and `<footer>`) must be SIBLINGS of `<main>`, not
          descendants. A `<header>` earns the implicit `banner` role — and a
          `<footer>` the `contentinfo` role — only when it is NOT inside
          `article`/`aside`/`main`/`nav`/`section`. `.site-header`/`.site-footer`
          in globals.css carry the page width and padding. */}
      {/* ⚠ THE BRAND IS THE WAY HOME. The mockup's masthead: a terracotta
          dot-in-circle mark, the product name, and the college under it — the
          whole thing a link to `/`. The light/dark toggle sits at the far right,
          vertically centred on the mark. (The build-version pill was removed
          from the header for the advisory-board demo; `lib/version.ts` still
          resolves the build string for anything that wants it.) */}
      <header className="site-header">
        <Link href="/" className="brand" aria-label="Coursework Benchmark — home">
          <span className="brand-mark" aria-hidden="true">
            <span className="brand-dot" />
          </span>
          <span className="brand-text">
            <span className="brand-name">Coursework Benchmark</span>
            <span className="brand-sub">Culverhouse College of Business</span>
          </span>
        </Link>
        <ThemeToggle />
      </header>
      <main id="main-content">{children}</main>
      {/* The secondary way to "how we test". It left the top nav so the landing
          could be a single front door; it lives here so it stays reachable from
          every page without competing with the page's own content. */}
      <footer className="site-footer">
        <nav className="site-footer-links" aria-label="Secondary">
          <Link href="/methodology">How we test</Link>
        </nav>
      </footer>
    </>
  );
}
