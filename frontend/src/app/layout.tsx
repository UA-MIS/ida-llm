import type { Metadata } from "next";
import localFont from "next/font/local";

import "./globals.css";

/**
 * ⚠ THE ROOT LAYOUT CARRIES NO CHROME. The product header, nav and `<main>`
 * wrapper live one level down in `(site)/layout.tsx`, behind a `(site)` route
 * group that adds no path segment. See that file for why.
 */

/**
 * ⚠ ONE FAMILY, VENDORED IN THE REPO. The "Organic" design the human's mockup
 * specifies uses Figtree for everything — body text and headings alike, headings
 * simply set at weight 700. The variable-weight latin .woff2 files live in
 * `./fonts` (SIL OFL 1.1, licence alongside) and `next/font/local` serves them
 * same-origin under `/_next/static/media`, so the browser makes NO request to
 * fonts.gstatic.com at runtime AND `next build` needs no egress either. This
 * replaced `next/font/google`, whose build-time fetch flaked in CI
 * ("next/font: Cannot read properties of null") and blocked a release.
 *
 * ⚠ THE VARIABLE NAME IS THE CONTRACT. `--font-body` is consumed throughout
 * globals.css; `--font-display` is aliased to it there (headings are the same
 * family, heavier), so renaming this silently drops the page to the fallback.
 */
const figtree = localFont({
  src: [
    {
      path: "./fonts/figtree-latin-wght-normal.woff2",
      weight: "300 900",
      style: "normal",
    },
    {
      path: "./fonts/figtree-latin-wght-italic.woff2",
      weight: "300 900",
      style: "italic",
    },
  ],
  display: "swap",
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
