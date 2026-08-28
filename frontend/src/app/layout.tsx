import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Sans } from "next/font/google";

import "./globals.css";

/**
 * ⚠ THE ROOT LAYOUT CARRIES NO CHROME. It used to render the header, the nav
 * and the `<main>` wrapper, which meant every route in the app was inside a
 * 1080px column under a "Capstone-IDA" h1.
 *
 * The landing page is a full-bleed editorial page with its own masthead, so it
 * cannot live inside that column. Rather than conditionally suppress the chrome
 * from a layout that does not know which route it is rendering — the usual way
 * this goes wrong — the chrome moved down one level into `(site)/layout.tsx`,
 * and every product route moved into that route group with it.
 *
 * A route group `(site)` adds NO path segment: `/leaderboard` is still
 * `/leaderboard`. What it buys is exactly one thing — a layout boundary the
 * landing page sits outside of.
 */

/**
 * ⚠ SELF-HOSTED AT BUILD TIME, NOT LINKED TO GOOGLE AT RUNTIME.
 *
 * `next/font/google` downloads these during `next build` and emits them as
 * same-origin assets under `/_next/static/media`. The browser therefore makes
 * NO request to fonts.googleapis.com or fonts.gstatic.com, which matters for
 * three separate reasons:
 *
 *   1. There is no CSP on this app today, but `apps/agile` already ships one and
 *      pins it by test. When this app grows the same headers, a `<link>` to
 *      Google would break at that moment — and the failure would be a silent
 *      fallback to Times New Roman, not an error. Self-hosting is immune.
 *   2. No third-party request means no third party able to see who reads the
 *      page, which a site arguing about data residency should not concede.
 *   3. No render-blocking round trip to a host we do not control.
 *
 * The cost is that `next build` needs egress to fonts.gstatic.com. The Docker
 * build already reaches the network (`npm ci`), so this adds no new class of
 * dependency — but if a future airgapped build fails here, THIS is the reason,
 * and the fix is `next/font/local` with the .woff2 files vendored into the repo.
 *
 * ⚠ THE VARIABLE NAMES ARE THE CONTRACT. `--font-display` and `--font-body` are
 * consumed by the Landing block in globals.css; renaming one here silently
 * drops the page back to the fallback stack.
 */
const fraunces = Fraunces({
  subsets: ["latin"],
  display: "swap",
  // `opsz` is what lets one family work at both 60px and 14px; `SOFT` rounds the
  // terminals just enough to read warm rather than institutional. Both axes are
  // set per-rule in the stylesheet.
  //
  // ⚠ NO `weight` HERE, AND THAT IS REQUIRED, NOT AN OVERSIGHT. `next/font`
  // rejects `axes` combined with an explicit weight list — "Axes can only be
  // defined for variable fonts when the weight property is nonexistent or set
  // to `variable`" — because naming weights pins the static instances, which is
  // exactly what having axes means we do not want. Omitting it ships the full
  // variable weight range, which the stylesheet uses from 300 to 600.
  axes: ["SOFT", "WONK", "opsz"],
  style: ["normal", "italic"],
  variable: "--font-display",
});

const plex = IBM_Plex_Sans({
  subsets: ["latin"],
  display: "swap",
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "Capstone-IDA",
  description:
    "Which AI can actually do the work — measured against real academic tasks, with the evidence behind every number.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${fraunces.variable} ${plex.variable}`}>
      <body>{children}</body>
    </html>
  );
}
