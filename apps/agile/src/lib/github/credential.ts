import { config } from '@/lib/env';
import { getInstallationToken } from './app';

/**
 * Where a GitHub credential comes from, and what that means for attribution.
 *
 * Under Dex OIDC the board never receives a GitHub token — that is the point,
 * since a team no longer registers its own GitHub OAuth app. Every
 * GitHub-touching path therefore has to say explicitly which credential it
 * uses, rather than assuming the session carries one.
 *
 * ── Precedence, in order ────────────────────────────────────────────────────
 *  1. **The acting user's own token.** Preferred whenever present, because an
 *     action performed with it is genuinely theirs — "alice created this
 *     branch", not "the board created it for alice". Only GitHub-backed
 *     sessions and GitHub-token API callers have one.
 *  2. **The board's GitHub App installation token.** Minted on demand from the
 *     App private key (see `./app`). This is what makes the board work for a
 *     Dex user at all, and it is the default for a platform-provisioned board.
 *  3. **`GITHUB_POLL_TOKEN`.** A static PAT. Still honoured so an existing
 *     deployment that set one keeps working, but no longer the thing a new
 *     board depends on — a static token that nobody rotates is how this board
 *     ended up running against a placeholder.
 *  4. **Nothing.** The feature degrades with a message that names what to set.
 *
 * Reads and actions resolve the SAME way. The difference is that an action
 * caller must not discard `source`: when it is anything but `user`, the item
 * history has to say so, or the board is quietly claiming a person did
 * something the board did.
 */

export interface HasGitHubToken {
  githubToken: string | null;
}

export type CredentialSource = 'user' | 'app' | 'poll-token' | 'none';

export interface GitHubCredential {
  token: string | null;
  source: CredentialSource;
}

/**
 * Resolves the credential for a GitHub call.
 *
 * Never throws: an unreachable GitHub or an unusable App key resolves to the
 * next source down, and ultimately to `{ token: null, source: 'none' }`.
 */
export async function githubActionCredential(
  principal: HasGitHubToken | null | undefined,
): Promise<GitHubCredential> {
  if (principal?.githubToken) return { token: principal.githubToken, source: 'user' };

  if (config.githubAppConfigured) {
    const appToken = await getInstallationToken();
    if (appToken) return { token: appToken, source: 'app' };
    // Minting failed. Fall through rather than fail: a deployment that also has
    // the legacy token should keep working through a GitHub App hiccup.
  }

  if (config.githubPollToken) return { token: config.githubPollToken, source: 'poll-token' };

  return { token: null, source: 'none' };
}

/**
 * The token for a read-only call, or null.
 * Same precedence — reads simply have no attribution to get wrong.
 */
export async function githubReadToken(
  principal: HasGitHubToken | null | undefined,
): Promise<string | null> {
  return (await githubActionCredential(principal)).token;
}

/**
 * The credential for UNATTENDED work — the background poller, a webhook — where
 * there is no user in context at all.
 */
export async function backgroundCredential(): Promise<string | null> {
  return githubReadToken(null);
}

/**
 * The note appended to item history when the board's own credential performed
 * an action. Returns undefined for a user credential, so the common case adds
 * no noise.
 */
export function attributionNote(source: CredentialSource): string | undefined {
  return source === 'app' || source === 'poll-token'
    ? 'performed with the board’s GitHub credential'
    : undefined;
}

/**
 * The user-facing explanation when NO credential is available at all.
 *
 * Always actionable: it names the variables an owner has to set. It never
 * interpolates a configured value, so it is safe to render anywhere.
 */
export function missingCredentialMessage(action: string): string {
  // Names the App variables FIRST, because that is the supported path and the
  // one a platform-provisioned board already has values for. GITHUB_POLL_TOKEN
  // is mentioned second, as the legacy escape hatch it now is.
  const fix =
    'an owner should configure the platform GitHub App (GITHUB_APP_ID, ' +
    'GITHUB_APP_PRIVATE_KEY, GITHUB_APP_INSTALLATION_ID), or set GITHUB_POLL_TOKEN ' +
    'as a fallback';
  return `${action} needs a GitHub credential and none is available. ${
    config.authProvider === 'oidc'
      ? `This board signs you in through Dex, which does not provide one — ${fix}.`
      : `Sign in with GitHub, or ${fix}.`
  }`;
}

/**
 * A one-line, NON-SECRET description of the credential this board will use.
 *
 * Logged at startup. The failure this whole module exists to fix was silent:
 * a placeholder token produced empty pickers and no error anywhere. An
 * unmissable startup line naming the credential source turns the next
 * occurrence into a five-second diagnosis.
 *
 * Only public identifiers appear here — an App id and an installation id are
 * not secrets. The private key and any token never are.
 */
export function credentialSummary(): string {
  if (config.githubAppConfigured) {
    return `GitHub App (app id ${config.githubAppId}, installation ${config.githubAppInstallationId})`;
  }
  if (config.githubPollToken) {
    return 'static GITHUB_POLL_TOKEN (legacy fallback; the GitHub App is preferred)';
  }
  return (
    'NONE — the assignee picker, branch creation and PR backlink comments are ' +
    'inert. Set GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY and GITHUB_APP_INSTALLATION_ID.'
  );
}
