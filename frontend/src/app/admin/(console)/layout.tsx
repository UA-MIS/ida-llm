import Link from "next/link";
import { notFound } from "next/navigation";

import { auth } from "@/auth";
import { SignOutButton } from "@/components/admin/auth-buttons";
import { AdminNav } from "@/components/admin/nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { adminConsoleEnabled } from "@/lib/admin/env";
import { adminFromSession } from "@/lib/admin/session";

/**
 * The signed-in console chrome.
 *
 * ⚠ THE LAYOUT IS NOT THE GUARD. Every page under `(console)` calls
 * `requireAdmin("<its own path>")` itself (pinned by admin-isolation.test.ts):
 * a layout does not re-run on client navigation and does not know the URL, so
 * redirecting from here would send everyone back to `/admin` after sign-in
 * instead of the page they asked for. As defence in depth, the chrome (which
 * names the signed-in user) renders only for a proven admin; anyone else gets
 * the bare page, whose own `requireAdmin()` redirects them.
 */
export const dynamic = "force-dynamic";

export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  if (!adminConsoleEnabled()) notFound();
  const admin = adminFromSession(await auth());
  if (!admin) return <>{children}</>;
  return (
    <>
      <a href="#admin-main" className="skip-link">
        Skip to content
      </a>
      <header className="adm-header">
        <Link href="/admin" className="brand" aria-label="Admin console home">
          <span className="brand-mark" aria-hidden="true">
            <span className="brand-dot" />
          </span>
          <span className="brand-text">
            <span className="brand-name">Coursework Benchmark</span>
            <span className="brand-sub">Admin console</span>
          </span>
        </Link>
        <span className="adm-user">
          Signed in as <strong>@{admin.login}</strong>
        </span>
        <SignOutButton />
        <ThemeToggle />
      </header>
      <div className="adm-body">
        <AdminNav />
        <main id="admin-main" className="adm-main">
          {children}
        </main>
      </div>
    </>
  );
}
