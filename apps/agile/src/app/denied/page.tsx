import { teamLabel, denialMessage, type DenialReason } from '@/lib/auth/team';

export const dynamic = 'force-dynamic';

const KNOWN: DenialReason[] = ['not-a-member', 'invitation-pending', 'lookup-failed'];

export default async function DeniedPage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string; login?: string }>;
}) {
  const { reason, login } = await searchParams;
  const TEAM_LABEL = teamLabel();
  const safeReason: DenialReason = KNOWN.includes(reason as DenialReason)
    ? (reason as DenialReason)
    : 'not-a-member';

  return (
    <div className="centered">
      <div className="auth-card">
        <div className="auth-mark" aria-hidden="true" style={{ background: 'var(--text-faint)' }}>
          !
        </div>
        <h1>You&rsquo;re not on this team</h1>
        <p>{denialMessage(safeReason)}</p>

        {login ? (
          <div className="alert">
            Signed in to GitHub as <strong className="mono">{login}</strong>, which is not an active
            member of <strong>{TEAM_LABEL}</strong>.
          </div>
        ) : null}

        <p className="muted" style={{ fontSize: 13 }}>
          If you think this is a mistake, ask a maintainer of {TEAM_LABEL} to add you to the team on
          GitHub, then sign in again.
        </p>

        <a className="btn" style={{ width: '100%', justifyContent: 'center' }} href="/api/auth/logout">
          Sign in as someone else
        </a>
      </div>
    </div>
  );
}
