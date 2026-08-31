"use client";

/**
 * The site nav's links, split into their own client component for one reason:
 * `aria-current="page"` needs to know which route is active, and that is only
 * knowable from `usePathname()`, which needs a client boundary. Everything
 * else about `(site)/layout.tsx` stays a server component — this is the one
 * sliver of it that cannot be.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

export function NavLinks({ items }: { items: { href: string; label: string }[] }) {
  const pathname = usePathname();
  return (
    <>
      {items.map((item) => {
        const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
        return (
          <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined}>
            {item.label}
          </Link>
        );
      })}
    </>
  );
}
