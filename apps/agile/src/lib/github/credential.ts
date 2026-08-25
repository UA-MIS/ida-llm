import { config } from '@/lib/env';

/**
 * Where a GitHub credential comes from, per operation.
 *
 * Under Dex OIDC the board never receives a GitHub token — that is the point,
 * since a team no longer registers its own GitHub OAuth app. Every
 * GitHub-touching path therefore has to say explicitly which credential it
 * uses, rather than assuming the session carries one.
 *
 * Two kinds of call:
 *
 *  - **Read** — list team members, read a pull request, reconcile state.
 *    Nothing is written to GitHub, so the shared app credential is fine.
 *  - **Action** — create a branch, comment on a PR, set a commit status.
 *    These write, so *who* performed them matters. The user's own token is
 *    preferred; the app credential is used as a fallback so the feature works
 *    for Dex users, and the caller is told which was used so the item history
 *    can record it truthfully instead of implying the user did it.
 */

export interface HasGitHubToken {
  githubToken: string | null;
}

export type CredentialSource = 'user' | 'app' | 'none';

export interface GitHubCredential {
  token: string | null;
  source: CredentialSource;
}

/** Read-only calls. Returns null when nothing is configured. */
export function githubReadToken(principal: HasGitHubToken | null | undefined): string | null {
  return principal?.githubToken || config.githubPollToken || null;
}

/**
 * Credential for a call that WRITES to GitHub.
 *
 * Prefers the acting user's own token so the action is genuinely theirs; falls
 * back to the app credential so the feature still works under Dex. `source`
 * tells the caller which happened — never discard it, because it is the
 * difference between "alice created this branch" and "the board created it on
 * alice's behalf".
 */
export function githubActionCredential(
  principal: HasGitHubToken | null | undefined,
): GitHubCredential {
  if (principal?.githubToken) return { token: principal.githubToken, source: 'user' };
  if (config.githubPollToken) return { token: config.githubPollToken, source: 'app' };
  return { token: null, source: 'none' };
}

/** Note appended to history when the app credential acted for someone. */
export function attributionNote(source: CredentialSource): string | undefined {
  return source === 'app' ? 'performed with the board’s GitHub credential' : undefined;
}

/**
 * User-facing explanation when NO credential is available at all.
 * Always actionable: it names the variable an owner has to set.
 */
export function missingCredentialMessage(action: string): string {
  return (
    `${action} needs a GitHub credential and none is configured. ` +
    (config.authProvider === 'oidc'
      ? 'This board signs you in through Dex, which does not provide one — an owner should set GITHUB_POLL_TOKEN (a token with write access to the configured repos).'
      : 'Sign in with GitHub, or ask an owner to set GITHUB_POLL_TOKEN.')
  );
}
