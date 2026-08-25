import { config } from '@/lib/env';

/**
 * Which GitHub credential to use for a given operation.
 *
 * Under Dex OIDC the board never receives a GitHub token — the whole point is
 * that a team does not have to register a GitHub OAuth app. That leaves the
 * GitHub-touching features without a credential, so they fall back to a
 * server-side token, but ONLY where doing so cannot misattribute anything:
 *
 *  - **Reads** (list team members, read pull requests, reconcile state) may use
 *    the shared `GITHUB_POLL_TOKEN`. Nothing is written to GitHub, so there is
 *    no author to get wrong.
 *  - **Writes** (creating a branch, posting a PR backlink comment) may NOT.
 *    A shared token would attribute a student's branch to a bot, which defeats
 *    the reason branches are created from the board in the first place. These
 *    require the acting user's own token and degrade with a clear message.
 */

export interface HasGitHubToken {
  githubToken: string | null;
}

/** A credential for read-only GitHub calls, or null if none is available. */
export function githubReadToken(principal: HasGitHubToken | null | undefined): string | null {
  return principal?.githubToken || config.githubPollToken || null;
}

/**
 * A credential for GitHub calls that WRITE as a person.
 * Deliberately never falls back to the shared token.
 */
export function githubWriteToken(principal: HasGitHubToken | null | undefined): string | null {
  return principal?.githubToken || null;
}

/** Explains, in the UI's voice, why a write-path feature is unavailable. */
export function writeCredentialHint(): string {
  return config.authProvider === 'oidc'
    ? 'This acts on GitHub as you, so it needs a GitHub credential. This board signs you in through Dex, which does not provide one — ask an owner to configure a GitHub App, or perform this step on GitHub directly.'
    : 'This acts on GitHub as you, so it requires a signed-in session rather than an API token.';
}
