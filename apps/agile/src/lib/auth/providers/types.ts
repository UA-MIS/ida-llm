/**
 * The identity provider seam.
 *
 * Web authentication is pluggable by configuration, not by rewrite: Dex OIDC is
 * the default (a per-instance GitHub OAuth app cannot be provisioned zero-touch,
 * because GitHub allows one callback URL per app), and direct GitHub OAuth
 * remains as a fallback implementation.
 */
export interface AuthIdentity {
  /** Stable login handle. Dex is configured with useLoginAsID, so this is the GitHub login. */
  login: string;
  name: string;
  avatarUrl: string;
  /** Groups/teams the provider asserts, e.g. ["UA-MIS:ida-llm"]. */
  groups: string[];
  /**
   * Upstream GitHub token, when the provider has one. Present for the GitHub
   * provider; absent for OIDC, where the board never sees a GitHub credential.
   */
  githubToken: string | null;
}

export interface AuthStartResult {
  /** Where to send the browser. */
  redirectUrl: string;
  /** Opaque value the callback must be able to verify (state, and PKCE verifier). */
  stateCookie: string;
}

export type AuthDenialReason =
  | 'not-a-member'
  | 'invitation-pending'
  | 'lookup-failed'
  | 'state-mismatch'
  | 'exchange-failed';

export type AuthCallbackResult =
  | { ok: true; identity: AuthIdentity; returnTo: string }
  | { ok: false; reason: AuthDenialReason; message: string; login?: string };

export interface AuthProvider {
  readonly id: 'oidc' | 'github';
  /** Human-readable, shown on the sign-in button. */
  readonly label: string;
  /** Begin the login redirect. */
  start(returnTo: string): Promise<AuthStartResult>;
  /** Handle the provider's callback and decide authorization. */
  callback(params: URLSearchParams, stateCookie: string | undefined): Promise<AuthCallbackResult>;
  /**
   * Re-check that an existing session still qualifies. Returning
   * `'unknown'` means "could not tell" and must NOT revoke access.
   */
  revalidate(identity: {
    login: string;
    groups: string[];
    githubToken: string | null;
  }): Promise<'ok' | 'denied' | 'unknown'>;
}
