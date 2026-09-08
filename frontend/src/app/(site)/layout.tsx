import Link from "next/link";

import { NavLinks } from "@/components/nav-links";
import { resolveVersion } from "@/lib/version";

/**
 * The product chrome: header, nav, and the 1080px column every tool page reads
 * inside. Lifted out of the root layout when the landing page arrived — see the
 * note there for why a route group rather than a conditional.
 *
 * Three destinations, named for what a professor gets rather than what we call
 * it internally.
 *
 * "Results" was the front door's old label and it described a shape, not an
 * answer — a visitor could not tell it from "All runs". The front door is a
 * LEADERBOARD now, so it says so; the recommendation flow keeps its verb; and
 * the raw run log stays last because it is the drill-down for someone who
 * already believes the numbers and wants to check them.
 *
 * ⚠ `/` IS NO LONGER THE LEADERBOARD. It is the landing page, and the
 * leaderboard has its own path — so this nav names `/leaderboard` explicitly
 * and the wordmark goes home to `/`. Anything still pointing a "back to the
 * results" link at `/` now lands a professor on the pitch instead of the data
 * they asked for.
 */
const NAV = [
  /* ⚠ FIRST, BECAUSE IT IS THE GUIDED DOOR. The client's verdict on the rest of
     this nav was "too much information, too many clicks" -- every other
     destination here drops a reader into a full catalogue and asks them to
     filter it down. `/explore` asks one question per screen instead. It is a
     CANDIDATE front door, offered alongside the others rather than in place of
     them, so the comparison the client needs to make is still there to make. */
  { href: "/explore", label: "Explore" },
  { href: "/leaderboard", label: "Leaderboard" },
  /* A top-level destination rather than a view-switch on the leaderboard: it
     answers "best at WHAT", which is a different question from "best", and the
     two do not share a filter bar sensibly. */
  { href: "/compare", label: "Compare by outcome" },
  { href: "/recommend", label: "Recommend a model" },
  { href: "/runs", label: "All runs" },
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
