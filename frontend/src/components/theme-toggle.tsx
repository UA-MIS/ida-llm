"use client";

/**
 * The light/dark switch in the header — the mockup's moon/sun button.
 *
 * ⚠ THE SOURCE OF TRUTH IS `data-theme` ON <html>, NOT REACT STATE. An inline
 * script in the root layout sets it before first paint from localStorage, and
 * `@media (prefers-color-scheme)` in globals.css decides when nothing is stored.
 * This button only flips the attribute and records the choice, then mirrors it
 * into its own state so the icon matches. It renders a stable, deterministic icon
 * on the server (and on the first client render) and resolves the real theme
 * after mount, so there is no hydration mismatch — only the icon updates, never
 * the page the script already themed.
 */

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

function currentTheme(): Theme {
  if (typeof document !== "undefined") {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr === "light" || attr === "dark") return attr;
  }
  return systemPrefersDark() ? "dark" : "light";
}

export function ThemeToggle() {
  // Deterministic on the server and the first client paint; the effect resolves
  // the real value after mount so the icon can never cause a hydration mismatch.
  const [theme, setTheme] = useState<Theme>("light");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setTheme(currentTheme());
    setReady(true);
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
    } catch {
      // Private mode or blocked storage: the attribute still flips for this
      // page; the choice just will not survive a reload. Nothing to recover.
    }
  }

  const dark = theme === "dark";
  const label = dark ? "Switch to light mode" : "Switch to dark mode";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={label}
      title={label}
      // Until the effect has resolved the stored/system theme, the pressed state
      // is unknown; announce it only once it is real.
      aria-pressed={ready ? dark : undefined}
    >
      {dark ? (
        // Sun — click to go light.
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
      ) : (
        // Moon — click to go dark.
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
        </svg>
      )}
    </button>
  );
}
