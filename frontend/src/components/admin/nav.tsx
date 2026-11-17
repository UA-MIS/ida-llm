"use client";

/**
 * The console's section list. A client component only to mark the current
 * section (`usePathname`); it receives no data.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

export const ADMIN_SECTIONS: { href: string; label: string }[] = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/models", label: "Models" },
  { href: "/admin/model-families", label: "Model families" },
  { href: "/admin/credentials", label: "API keys" },
  { href: "/admin/material", label: "Course material" },
  { href: "/admin/classes", label: "Majors and classes" },
  { href: "/admin/runs", label: "Runs" },
  { href: "/admin/audit", label: "Activity log" },
  { href: "/admin/system", label: "System" },
];

export function AdminNav() {
  const pathname = usePathname() ?? "/admin";
  return (
    <nav className="adm-nav" aria-label="Admin sections">
      <ul>
        {ADMIN_SECTIONS.map((s) => {
          const current = s.href === "/admin" ? pathname === "/admin" : pathname === s.href || pathname.startsWith(`${s.href}/`);
          return (
            <li key={s.href}>
              <Link href={s.href} aria-current={current ? "page" : undefined} className={current ? "is-current" : undefined}>
                {s.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
