import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { adminConsoleEnabled } from "@/lib/admin/env";

import "./admin.css";

/**
 * The outer admin shell: shared by the console and the two data-free auth
 * pages (sign-in, denied). It renders NOTHING when the console is switched
 * off: `ADMIN_CONSOLE_ENABLED` unset (base, preview) makes every `/admin`
 * URL a 404, as if the console had never been built.
 *
 * The admin stylesheet is imported here, not in the root layout, so the public
 * pages' CSS is unchanged byte for byte.
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Admin · Coursework Benchmark",
  robots: { index: false, follow: false },
};

export default function AdminShell({ children }: { children: React.ReactNode }) {
  if (!adminConsoleEnabled()) notFound();
  return <div className="adm">{children}</div>;
}
