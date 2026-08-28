import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

import { resolveVersion } from "@/lib/version";

export const metadata: Metadata = {
  title: "Capstone-IDA",
  description:
    "Which AI can actually do the work — measured against real academic tasks, with the evidence behind every number.",
};

/**
 * Three destinations, named for what a professor gets rather than what we call
 * it internally.
 *
 * "Results" was the front door's old label and it described a shape, not an
 * answer — a visitor could not tell it from "All runs". The front door is a
 * LEADERBOARD now, so it says so; the recommendation flow keeps its verb; and
 * the raw run log stays last because it is the drill-down for someone who
 * already believes the numbers and wants to check them.
 */
const NAV = [
  { href: "/", label: "Leaderboard" },
  { href: "/recommend", label: "Recommend a model" },
  { href: "/runs", label: "All runs" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // ⚠ Resolved, never typed. This badge used to be a hardcoded `v0.1.4` that no
  // release step ever wrote to — see lib/version.ts for both halves of the
  // wiring and for why the fallback is loudly labelled rather than empty.
  const version = resolveVersion();

  return (
    <html lang="en">
      <body>
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
      </body>
    </html>
  );
}
