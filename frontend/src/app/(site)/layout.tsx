import Link from "next/link";

import { NavLinks } from "@/components/nav-links";
import { resolveVersion } from "@/lib/version";

/**
 * The product chrome: header, nav, and the column every page reads inside. The
 * landing lives in this group too now, so the whole site shares one quiet
 * header.
 *
 * ⚠ THREE DESTINATIONS, DELIBERATELY. The client's verdict on the old nav was
 * "too much information, too many clicks, too many options" — it had a landing,
 * a leaderboard, a compare grid, a run log and a recommend flow all competing as
 * front doors. Those are gone. What is left is the three things a professor
 * actually does: explore the grid (the landing, `/`), read how we test it, and
 * ask for an answer. Named for what they get, not for what we call it inside.
 */
const NAV = [
  { href: "/", label: "Explore" },
  { href: "/methodology", label: "How we test" },
  { href: "/recommend", label: "Help me choose" },
];

export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // ⚠ Resolved, never typed. This badge used to be a hardcoded `v0.1.4` that no
  // release step ever wrote to — see lib/version.ts for both halves of the
  // wiring and for why the fallback is loudly labelled rather than empty.
  const version = resolveVersion();

  return (
    <>
      {/* ⚠ QA-25. The first focusable thing on every tool page, invisible
          until it is focused (`.skip-link` in globals.css) — so a keyboard
          user does not have to tab through four nav links on every single
          page just to reach the content they came for. */}
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      {/* ⚠ QA-25: `<header>`/`<nav>` USED TO BE INSIDE `<main>`. A `<header>`
          only gets the implicit `banner` landmark role when it is NOT a
          descendant of `article`/`aside`/`main`/`nav`/`section` — nested
          inside `<main>` the way this was, it had no landmark role at all,
          and neither did the page's one piece of content actually worth the
          `main` landmark. They are siblings now; `.site-header` in
          globals.css carries the same width/padding `main` used to give it
          for free, so this is a markup change with no visual one. */}
      <header className="site-header">
        <h1>
          <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
            Capstone-IDA
          </Link>
          <span
            className={`badge badge-version${version.identified ? "" : " badge-version-unknown"}`}
            title={version.detail}
          >
            {version.label}
          </span>
        </h1>
        <nav className="nav" aria-label="Primary">
          <NavLinks items={NAV} />
        </nav>
      </header>
      <main id="main-content">{children}</main>
    </>
  );
}
