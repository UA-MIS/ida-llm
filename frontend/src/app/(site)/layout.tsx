import Link from "next/link";

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
    <main>
      <header>
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
        <nav className="nav">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
        </nav>
      </header>
      {children}
    </main>
  );
}
