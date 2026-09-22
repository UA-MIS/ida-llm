import Link from "next/link";
import { NavLinks } from "@/components/nav-links";
import { resolveVersion } from "@/lib/version";

const NAV = [
  { href: "/", label: "Explore" },
  { href: "/methodology", label: "How we test" },
  { href: "/recommend", label: "Help me choose" },
];

/** Shared, deliberately quiet chrome for the faculty-facing pages. */
export function FacultyShell({ children }: { children: React.ReactNode }) {
  const version = resolveVersion();
  return (
    <div className="faculty-site">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <header className="faculty-header">
        <Link href="/" className="faculty-wordmark">Capstone-IDA</Link>
        <nav aria-label="Primary"><NavLinks items={NAV} /></nav>
      </header>
      <main id="main-content" className="faculty-main">{children}</main>
      <footer className="faculty-footer">
        <span>University of Alabama · Institute of Data Analytics</span>
        <nav aria-label="Research resources">
          <Link href="/leaderboard">Leaderboard</Link>
          <Link href="/compare">Compare by outcome</Link>
          <Link href="/runs">All runs</Link>
          <Link href="/about">About IDA</Link>
        </nav>
        <details><summary>Build information</summary><p title={version.detail}>{version.label}</p></details>
      </footer>
    </div>
  );
}
