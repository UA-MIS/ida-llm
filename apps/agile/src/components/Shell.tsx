import Link from 'next/link';
import type { SessionPayload } from '@/lib/auth/session';
import { config } from '@/lib/env';
import { ToastProvider } from './Toast';

/** App chrome: brand, primary nav, current user. Title/accent come from config. */
export function Shell({
  session,
  active,
  children,
}: {
  session: SessionPayload;
  active: 'board' | 'backlog' | 'sprints' | 'tokens' | 'item';
  children: React.ReactNode;
}) {
  const nav = [
    { key: 'board', href: '/board', label: 'Board' },
    { key: 'backlog', href: '/backlog', label: 'Backlog' },
    { key: 'sprints', href: '/sprints', label: 'Sprints' },
  ] as const;

  const initials =
    config.boardTitle
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]!.toUpperCase())
      .join('') || 'AB';

  return (
    <ToastProvider>
      <div className="shell">
        <header className="topbar">
          <Link href="/board" className="brand">
            <span className="brand-mark" aria-hidden="true">{initials}</span>
            {config.boardTitle}
          </Link>
          <nav className="nav" aria-label="Primary">
            {nav.map((n) => (
              <Link key={n.key} href={n.href} aria-current={active === n.key ? 'page' : undefined}>
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="who">
            {session.avatarUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img className="avatar" src={session.avatarUrl} alt="" />
            ) : null}
            <span className="mono nowrap">{session.login}</span>
            <Link className="btn btn-sm btn-ghost" href="/tokens" aria-current={active === 'tokens' ? 'page' : undefined}>
              Tokens
            </Link>
            <a className="btn btn-sm btn-ghost" href="/api/auth/logout">Sign out</a>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </ToastProvider>
  );
}
