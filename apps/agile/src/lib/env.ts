/**
 * Configuration for one board instance.
 *
 * NOTHING about a particular org, team or repo is hardcoded: a second instance
 * for another class is a different set of environment variables and no code
 * change. Values are read from process.env on access (not captured at import)
 * so tests and the OpenAPI generator can vary them.
 *
 * Secrets arrive as env vars (Vault -> External Secrets Operator -> pod env).
 */

function required(name: string): string {
  const v = process.env[name];
  if (!v || v.trim() === '') {
    throw new Error(
      `Missing required environment variable ${name}. See apps/agile/README.md.`,
    );
  }
  return v;
}

function optional(name: string, fallback: string): string {
  const v = process.env[name];
  return v && v.trim() !== '' ? v : fallback;
}

function flag(name: string, fallback: boolean): boolean {
  const v = process.env[name];
  if (v === undefined || v.trim() === '') return fallback;
  return /^(1|true|yes|on)$/i.test(v.trim());
}

function integer(name: string, fallback: number): number {
  const v = Number(process.env[name]);
  return Number.isFinite(v) ? v : fallback;
}

/** Validates a Postgres identifier; never interpolate an unchecked name. */
export function assertSafeIdentifier(name: string): string {
  if (!/^[a-z_][a-z0-9_]*$/.test(name)) {
    throw new Error(`Unsafe SQL identifier: ${JSON.stringify(name)}`);
  }
  return name;
}

const REPO_RE = /^[\w.-]+\/[\w.-]+$/;

export const config = {
  // ---------------------------------------------------------------- identity
  /** GitHub org that owns the team and repos. */
  get githubOrg(): string {
    return optional('GITHUB_ORG', 'UA-MIS');
  },
  /** Team slug whose members may use this board. GITHUB_TEAM_SLUG is a legacy alias. */
  get githubTeam(): string {
    return optional('GITHUB_TEAM', optional('GITHUB_TEAM_SLUG', 'ida-llm'));
  },
  get teamLabel(): string {
    return `${this.githubOrg}/${this.githubTeam}`;
  },

  /**
   * Repos this board links pull requests and branches against.
   * GITHUB_REPOS is a comma-separated list; GITHUB_REPO is a single-repo alias.
   * Bare names are qualified with the org.
   */
  get githubRepos(): string[] {
    const raw = optional('GITHUB_REPOS', optional('GITHUB_REPO', ''));
    const org = this.githubOrg;
    const repos = raw
      .split(',')
      .map((r) => r.trim())
      .filter(Boolean)
      .map((r) => (r.includes('/') ? r : `${org}/${r}`))
      .filter((r) => REPO_RE.test(r));
    return repos.length ? [...new Set(repos)] : [`${org}/${this.githubTeam}`];
  },
  /** The repo used for branch creation and the open-PR picker. */
  get primaryRepo(): string {
    return this.githubRepos[0]!;
  },
  isKnownRepo(fullName: string): boolean {
    return this.githubRepos.some((r) => r.toLowerCase() === fullName.toLowerCase());
  },

  /**
   * Scopes every row to this instance. One deploy = one board today; the column
   * exists so a future multi-board mode is a query change, not a migration.
   */
  get instanceKey(): string {
    return optional('BOARD_INSTANCE', `${this.githubOrg}/${this.githubTeam}`);
  },

  // ---------------------------------------------------------------- branding
  get boardTitle(): string {
    return optional('BOARD_TITLE', 'Agile Board');
  },
  get boardAccent(): string {
    const v = optional('BOARD_ACCENT', '#9e1b32');
    // Only a hex colour is ever interpolated into CSS.
    return /^#[0-9a-fA-F]{6}$/.test(v) ? v : '#9e1b32';
  },

  // ---------------------------------------------------------------- database
  get databaseUrl(): string {
    return required('DATABASE_URL');
  },
  get dbSchema(): string {
    return assertSafeIdentifier(optional('AGILE_DB_SCHEMA', 'agile'));
  },
  get pgPoolMax(): number {
    return integer('PGPOOL_MAX', 10);
  },

  // -------------------------------------------------------------------- auth
  get githubClientId(): string {
    return required('GITHUB_CLIENT_ID');
  },
  get githubClientSecret(): string {
    return required('GITHUB_CLIENT_SECRET');
  },
  get sessionSecret(): string {
    const s = required('SESSION_SECRET');
    if (s.length < 32) throw new Error('SESSION_SECRET must be at least 32 characters.');
    return s;
  },
  /** Public origin, e.g. https://ida-agile.capstone.uamishub.com */
  get appUrl(): string {
    return required('APP_URL').replace(/\/+$/, '');
  },
  get isProduction(): boolean {
    return process.env.NODE_ENV === 'production';
  },

  // ---------------------------------------------------------------- webhooks
  /** Empty means webhooks are not configured; the poller becomes the only path. */
  get webhookSecret(): string {
    return optional('GITHUB_WEBHOOK_SECRET', '');
  },
  get webhooksEnabled(): boolean {
    return this.webhookSecret !== '';
  },
  /** Background reconciliation interval. 0 disables the background poller. */
  get pollIntervalSeconds(): number {
    return integer('POLL_INTERVAL_SECONDS', 300);
  },
  /**
   * Credential for the BACKGROUND poller. A webhook has no user in context and
   * neither does a timer, so unattended polling needs its own token (a PAT or
   * GitHub App installation token) with read access to the configured repos.
   * Without it the background loop stays off and reconciliation happens
   * on-view instead, using the viewing member's own token.
   */
  get githubPollToken(): string {
    return optional('GITHUB_POLL_TOKEN', '');
  },
  get backgroundPollEnabled(): boolean {
    return this.pollIntervalSeconds > 0 && this.githubPollToken !== '';
  },
  /** Minimum seconds between on-view reconciliations of the same resource. */
  get onViewRefreshSeconds(): number {
    return integer('ONVIEW_REFRESH_SECONDS', 120);
  },

  // ------------------------------------------------------------------ OIDC
  /**
   * Identity provider. `oidc` (Dex) is the default because a per-instance
   * GitHub OAuth app cannot be provisioned zero-touch — GitHub allows one
   * callback URL per app, so twelve teams would mean twelve manual
   * registrations. `github` remains as a fallback implementation.
   */
  get authProvider(): 'oidc' | 'github' {
    const explicit = optional('AUTH_PROVIDER', '').toLowerCase();
    if (explicit === 'oidc' || explicit === 'github') return explicit;
    return this.oidcIssuer ? 'oidc' : 'github';
  },
  get oidcIssuer(): string {
    return optional('OIDC_ISSUER', '').replace(/\/+$/, '');
  },
  get oidcClientId(): string {
    return required('OIDC_CLIENT_ID');
  },
  get oidcClientSecret(): string {
    return optional('OIDC_CLIENT_SECRET', '');
  },
  get oidcRedirectUri(): string {
    return optional('OIDC_REDIRECT_URI', `${this.appUrl}/api/auth/callback`);
  },
  get oidcScopes(): string {
    return optional('OIDC_SCOPES', 'openid profile email groups');
  },
  /**
   * The group that grants access, as it appears in the `groups` claim.
   * Dex's GitHub connector emits `org:team`. Defaults to the configured
   * org/team so a standard deployment needs no extra variable.
   */
  get requiredGroup(): string {
    return optional('REQUIRED_GROUP', `${this.githubOrg}:${this.githubTeam}`);
  },

  // ------------------------------------------------------------ automation
  get autoBranch(): boolean {
    return flag('AUTO_BRANCH', true);
  },
  /** e.g. "story/42-judge-calibration-refresh" */
  get branchPattern(): string {
    return optional('BRANCH_PATTERN', '{type}/{id}-{slug}');
  },
  get autoProgress(): boolean {
    return flag('AUTO_PROGRESS', true);
  },
  get autoProgressOnCommit(): boolean {
    return this.autoProgress && flag('AUTO_PROGRESS_ON_COMMIT', true);
  },
  get autoProgressOnPrOpen(): boolean {
    return this.autoProgress && flag('AUTO_PROGRESS_ON_PR_OPEN', true);
  },
  get autoProgressOnPrMerge(): boolean {
    return this.autoProgress && flag('AUTO_PROGRESS_ON_PR_MERGE', true);
  },
  /** Post/maintain a backlink comment on linked PRs. */
  get prBacklinkComments(): boolean {
    return flag('PR_BACKLINK_COMMENTS', true);
  },
  /** Publish a commit status on PRs showing the linked work item. */
  get prCommitStatus(): boolean {
    return flag('PR_COMMIT_STATUS', false);
  },

  // ------------------------------------------------- trunk-based signals
  /**
   * Delivery here is trunk-based, so a board branch is short-lived by
   * definition. These thresholds drive a "branch stale" badge; 0 disables
   * either check. Progress is always measured by merged PRs, never commits.
   */
  get staleBranchDays(): number {
    return integer('STALE_BRANCH_DAYS', 5);
  },
  get staleBranchBehind(): number {
    return integer('STALE_BRANCH_BEHIND', 20);
  },

  // ----------------------------------------------------------- dependencies
  /** Allow an explicit, logged override of the dependency gate. */
  get allowDependencyOverride(): boolean {
    return flag('ALLOW_DEPENDENCY_OVERRIDE', true);
  },

  // ------------------------------------------------------------- attachments
  /**
   * Object storage for attachments. The MINIO_* names match the convention the
   * rest of this repo already uses; the S3_* names are accepted as aliases so a
   * different deployment can point at any S3-compatible endpoint.
   */
  get s3Endpoint(): string {
    const explicit = optional('S3_ENDPOINT', '');
    if (explicit) return explicit;
    const host = optional('MINIO_ENDPOINT', '');
    if (!host) return '';
    const port = optional('MINIO_PORT', '9000');
    const scheme = flag('MINIO_USE_SSL', false) ? 'https' : 'http';
    return /^https?:\/\//.test(host) ? host : `${scheme}://${host}:${port}`;
  },
  get s3Bucket(): string {
    return optional('S3_BUCKET', optional('MINIO_BUCKET', ''));
  },
  get s3AccessKeyId(): string {
    return optional('S3_ACCESS_KEY_ID', optional('MINIO_ACCESS_KEY', ''));
  },
  get s3SecretAccessKey(): string {
    return optional('S3_SECRET_ACCESS_KEY', optional('MINIO_SECRET_KEY', ''));
  },
  get s3Region(): string {
    return optional('S3_REGION', 'us-east-1');
  },
  get s3ForcePathStyle(): boolean {
    return flag('S3_FORCE_PATH_STYLE', true);
  },
  /** Attachments are only offered when object storage is fully configured. */
  get attachmentsEnabled(): boolean {
    return Boolean(this.s3Endpoint && this.s3Bucket && this.s3AccessKeyId && this.s3SecretAccessKey);
  },
  get maxUploadBytes(): number {
    return integer('MAX_UPLOAD_BYTES', 25 * 1024 * 1024);
  },
};

/** Values safe to render into the client bundle. Never add a secret here. */
export interface PublicConfig {
  boardTitle: string;
  boardAccent: string;
  teamLabel: string;
  primaryRepo: string;
  repos: string[];
  autoBranch: boolean;
  attachmentsEnabled: boolean;
}

export function publicConfig(): PublicConfig {
  return {
    boardTitle: config.boardTitle,
    boardAccent: config.boardAccent,
    teamLabel: config.teamLabel,
    primaryRepo: config.primaryRepo,
    repos: config.githubRepos,
    autoBranch: config.autoBranch,
    attachmentsEnabled: config.attachmentsEnabled,
  };
}
