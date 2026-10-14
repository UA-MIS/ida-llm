import type { Metadata } from "next";
import { Figtree } from "next/font/google";

import "./globals.css";

/**
 * ⚠ THE ROOT LAYOUT CARRIES NO CHROME. The product header, nav and `<main>`
 * wrapper live one level down in `(site)/layout.tsx`, behind a `(site)` route
 * group that adds no path segment. See that file for why.
 */

/**
 * ⚠ ONE FAMILY, SELF-HOSTED AT BUILD TIME. The "Organic" design the human's
 * mockup specifies uses Figtree for everything — body text and headings alike,
 * headings simply set at weight 700. `next/font/google` downloads it during
 * `next build` and serves it same-origin under `/_next/static/media`, so the
 * browser makes NO request to fonts.gstatic.com at runtime (no third party
 * watching who reads the page, no render-blocking round trip, and nothing for a
 * future CSP to break). The cost is that `next build` needs egress to
 * fonts.gstatic.com — the Docker build already reaches the network for `npm ci`,
 * so this adds no new class of dependency; an airgapped build would fail here and
 * the fix is `next/font/local` with the .woff2 vendored in.
 *
 * ⚠ THE VARIABLE NAME IS THE CONTRACT. `--font-body` is consumed throughout
 * globals.css; `--font-display` is aliased to it there (headings are the same
 * family, heavier), so renaming this silently drops the page to the fallback.
 */
const figtree = Figtree({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
  variable: "--font-body",
});

/**
 * ⚠ NO-FLASH THEME. The toggle writes the reader's choice to localStorage and
 * sets `data-theme` on <html>; this inline script replays that choice BEFORE the
 * first paint, so a reader who picked dark does not see a flash of light (or vice
 * versa) on every navigation. With no stored choice it does nothing and the
 * `@media (prefers-color-scheme)` default in globals.css decides. It is tiny,
 * self-contained, and must run before CSS applies, which is why it is inlined
 * here rather than shipped as a component.
 */
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t);}}catch(e){}})();`;

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
    <html lang="en" className={figtree.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
