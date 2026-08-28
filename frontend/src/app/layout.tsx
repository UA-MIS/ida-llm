import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Capstone-IDA",
  description:
    "Which AI can actually do the work — measured against real academic tasks, with the evidence behind every number.",
};

/**
 * Three destinations, in the order a professor needs them.
 *
 * Results first because it is the front door; the recommendation flow second
 * because it is where a visitor who does not know what they need should go; the
 * raw run log last, because it is the drill-down for someone who already
 * believes the numbers and wants to check them.
 */
const NAV = [
  { href: "/", label: "Results" },
  { href: "/recommend", label: "Get a recommendation" },
  { href: "/runs", label: "All runs" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <main>
          <header>
            <h1>
              <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
                Capstone-IDA
              </Link>
              <span className="badge badge-version">v0.1.4</span>
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
