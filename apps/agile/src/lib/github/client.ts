import { config } from '@/lib/env';
import { ghHeaders, type Fetcher } from '@/lib/auth/github-oauth';

export interface TeamMember {
  login: string;
  name: string | null;
  avatarUrl: string;
}

export interface PullRequestSummary {
  repoFullName: string;
  number: number;
  url: string;
  title: string;
  state: string;
  merged: boolean;
  draft: boolean;
  author: string;
  headRef: string;
  baseRef: string;
  checksState: string | null;
  body: string;
}

/** A PR plus any work-item references found in its title/body. */
export interface AnnotatedPullRequest extends PullRequestSummary {
  suggestedItemIds: number[];
}

export interface CommitInfo {
  sha: string;
  message: string;
  authorLogin: string | null;
  authorName: string;
  url: string;
  committedAt: string;
}

export class GitHubError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'GitHubError';
  }
}

/**
 * Small in-process TTL cache. This is a pure latency/rate-limit optimisation:
 * every value here is re-derivable from GitHub, so losing it when a pod dies
 * costs nothing. No durable state is ever kept in memory.
 */
class TtlCache<T> {
  private entries = new Map<string, { value: T; expiresAt: number }>();
  constructor(private readonly ttlMs: number) {}

  get(key: string): T | undefined {
    const hit = this.entries.get(key);
    if (!hit) return undefined;
    if (hit.expiresAt <= Date.now()) {
      this.entries.delete(key);
      return undefined;
    }
    return hit.value;
  }
  set(key: string, value: T): void {
    this.entries.set(key, { value, expiresAt: Date.now() + this.ttlMs });
  }
  clear(): void {
    this.entries.clear();
  }
}

const membersCache = new TtlCache<TeamMember[]>(5 * 60 * 1000);
const prCache = new TtlCache<AnnotatedPullRequest[]>(60 * 1000);
/**
 * A repo's default branch changes approximately never, and three call sites
 * now need it — `createBranch`, `compareWithDefault` and the commit walk. Left
 * uncached it cost one `GET /repos/{repo}` per item per poll cycle, all
 * returning the same immutable string against a shared org rate budget.
 */
const defaultBranchCache = new TtlCache<string>(30 * 60 * 1000);

export function clearGitHubCaches(): void {
  membersCache.clear();
  prCache.clear();
  defaultBranchCache.clear();
}

// ---------------------------------------------------------------- members

export async function listTeamMembers(
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<TeamMember[]> {
  // No credential: return empty rather than calling GitHub unauthenticated.
  if (!token) return [];
  const key = config.teamLabel;
  const cached = membersCache.get(key);
  if (cached) return cached;

  const members: TeamMember[] = [];
  for (let page = 1; page <= 5; page++) {
    const res = await fetchImpl(
      `https://api.github.com/orgs/${config.githubOrg}/teams/${config.githubTeam}/members?per_page=100&page=${page}`,
      { headers: ghHeaders(token) },
    );
    if (!res.ok) {
      if (members.length === 0) return [];
      break;
    }
    const batch = (await res.json()) as Array<{ login: string; avatar_url?: string }>;
    if (!Array.isArray(batch) || batch.length === 0) break;
    for (const m of batch) members.push({ login: m.login, name: null, avatarUrl: m.avatar_url ?? '' });
    if (batch.length < 100) break;
  }

  members.sort((a, b) => a.login.localeCompare(b.login));
  membersCache.set(key, members);
  return members;
}

// ------------------------------------------------------------ pull requests

/** Open PRs across every configured repo. */
export async function listOpenPullRequests(
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<PullRequestSummary[]> {
  if (!token) return [];
  const out: PullRequestSummary[] = [];
  for (const repo of config.githubRepos) {
    const res = await fetchImpl(
      `https://api.github.com/repos/${repo}/pulls?state=open&per_page=100&sort=updated&direction=desc`,
      { headers: ghHeaders(token) },
    );
    if (!res.ok) continue;
    const body = (await res.json()) as unknown;
    if (!Array.isArray(body)) continue;
    for (const pr of body) out.push(mapPr(repo, pr as Record<string, unknown>));
  }
  return out;
}

export async function fetchPullRequest(
  repoFullName: string,
  number: number,
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<PullRequestSummary | null> {
  const res = await fetchImpl(`https://api.github.com/repos/${repoFullName}/pulls/${number}`, {
    headers: ghHeaders(token),
  });
  if (!res.ok) return null;
  const pr = (await res.json()) as Record<string, unknown>;
  const summary = mapPr(repoFullName, pr);

  const sha = (pr.head as { sha?: string } | undefined)?.sha;
  if (sha) summary.checksState = await fetchCombinedStatus(repoFullName, sha, token, fetchImpl);
  return summary;
}

export async function fetchCombinedStatus(
  repoFullName: string,
  sha: string,
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<string | null> {
  try {
    const res = await fetchImpl(`https://api.github.com/repos/${repoFullName}/commits/${sha}/status`, {
      headers: ghHeaders(token),
    });
    if (!res.ok) return null;
    const status = (await res.json()) as { state?: string };
    return status.state ?? null;
  } catch {
    return null;
  }
}

export function mapPr(repoFullName: string, pr: Record<string, unknown>): PullRequestSummary {
  const user = pr.user as { login?: string } | undefined;
  const head = pr.head as { ref?: string } | undefined;
  const base = pr.base as { ref?: string } | undefined;
  const merged = Boolean(pr.merged_at) || pr.merged === true;
  return {
    repoFullName,
    number: Number(pr.number ?? 0),
    url: String(pr.html_url ?? ''),
    title: String(pr.title ?? ''),
    state: merged ? 'merged' : String(pr.state ?? 'open'),
    merged,
    draft: pr.draft === true,
    author: user?.login ?? '',
    headRef: head?.ref ?? '',
    baseRef: base?.ref ?? '',
    checksState: null,
    body: typeof pr.body === 'string' ? pr.body : '',
  };
}

// ------------------------------------------------------------------ branches

export async function getRepoDefaultBranch(
  repoFullName: string,
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<string> {
  const cached = defaultBranchCache.get(repoFullName);
  if (cached) return cached;

  const res = await fetchImpl(`https://api.github.com/repos/${repoFullName}`, {
    headers: ghHeaders(token),
  });
  // Deliberately NOT cached on failure: a 403 rate-limit must not pin a wrong
  // answer (or an absence) for half an hour.
  if (!res.ok) throw new GitHubError(`Could not read repository ${repoFullName}.`, res.status);
  const body = (await res.json()) as { default_branch?: string };
  const branch = body.default_branch ?? 'main';
  defaultBranchCache.set(repoFullName, branch);
  return branch;
}

export async function getRefSha(
  repoFullName: string,
  ref: string,
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<string | null> {
  const res = await fetchImpl(
    `https://api.github.com/repos/${repoFullName}/git/ref/heads/${encodeURIComponent(ref)}`,
    { headers: ghHeaders(token) },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new GitHubError(`Could not read ref ${ref}.`, res.status);
  const body = (await res.json()) as { object?: { sha?: string } };
  return body.object?.sha ?? null;
}

/**
 * Creates a branch off the repo's default branch.
 * Returns `existed: true` when the ref is already present, so the caller can
 * treat "start work" as idempotent rather than an error.
 */
export async function createBranch(
  repoFullName: string,
  branch: string,
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<{ branch: string; sha: string; existed: boolean; url: string }> {
  const existing = await getRefSha(repoFullName, branch, token, fetchImpl);
  const url = `https://github.com/${repoFullName}/tree/${branch}`;
  if (existing) return { branch, sha: existing, existed: true, url };

  const base = await getRepoDefaultBranch(repoFullName, token, fetchImpl);
  const baseSha = await getRefSha(repoFullName, base, token, fetchImpl);
  if (!baseSha) {
    throw new GitHubError(
      `Repository ${repoFullName} has no commits on ${base}; cannot branch from an empty repo.`,
      422,
    );
  }

  const res = await fetchImpl(`https://api.github.com/repos/${repoFullName}/git/refs`, {
    method: 'POST',
    headers: { ...ghHeaders(token), 'content-type': 'application/json' },
    body: JSON.stringify({ ref: `refs/heads/${branch}`, sha: baseSha }),
  });

  if (res.status === 422) {
    // Lost a race, or the name is otherwise taken: treat as already existing.
    const sha = await getRefSha(repoFullName, branch, token, fetchImpl);
    if (sha) return { branch, sha, existed: true, url };
    throw new GitHubError(`GitHub rejected the branch name "${branch}".`, 422);
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new GitHubError(
      `Could not create branch "${branch}" in ${repoFullName} (HTTP ${res.status}). ${detail.slice(0, 200)}`,
      res.status,
    );
  }

  const body = (await res.json()) as { object?: { sha?: string } };
  return { branch, sha: body.object?.sha ?? baseSha, existed: false, url };
}

/** How far behind the default branch a branch is; null when unknown. */
export async function compareWithDefault(
  repoFullName: string,
  branch: string,
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<{ behindBy: number; aheadBy: number } | null> {
  try {
    const base = await getRepoDefaultBranch(repoFullName, token, fetchImpl);
    const res = await fetchImpl(
      `https://api.github.com/repos/${repoFullName}/compare/${encodeURIComponent(base)}...${encodeURIComponent(branch)}`,
      { headers: ghHeaders(token) },
    );
    if (!res.ok) return null;
    const body = (await res.json()) as { behind_by?: number; ahead_by?: number };
    return { behindBy: body.behind_by ?? 0, aheadBy: body.ahead_by ?? 0 };
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------- commits

/** GitHub's maximum page size for the compare endpoint. */
const COMPARE_PAGE_SIZE = 100;

/**
 * The most recent `limit` commits on `branch` that are NOT already on the
 * repo's base branch — i.e. the work done ON this branch.
 *
 * This deliberately does NOT use `GET /commits?sha={branch}`, which returns the
 * branch's whole ANCESTRY. A board branch is cut from the base branch, so its
 * tip IS the base's tip until someone pushes: listing it returned the base's
 * last 50 commits, every one of which was then ingested and attributed to the
 * item. A research spike whose branch was never touched displayed
 * `commitCount: 20` — main's history, wearing the item's name (AB#25).
 *
 * `compare/base...branch` answers the question a human is actually asking:
 * `commits` there is exactly the ahead-set, so a freshly-cut branch is 0.
 *
 * PAGINATION. `commits` is ordered OLDEST-FIRST and is capped at one page, so
 * on a branch more than a page ahead the first response holds the OLDEST 100
 * commits and slicing its tail yields the middle of the branch, never the
 * newest. `total_commits` is the authoritative ahead-count regardless of page
 * size, so it is used to walk to the end and take the genuinely newest ones.
 *
 * FAILURE. The compare call fails soft (empty list): a display count must not
 * break reconciliation. The base-branch lookup deliberately does NOT — a
 * rate-limited or unreachable GitHub would otherwise be indistinguishable from
 * "this branch is 0 commits ahead", which is exactly the wrong-looking-right
 * answer AB#25 was. The poller wraps this call and surfaces the throw as a
 * warning, which is the louder and more honest outcome.
 */
export async function listCommitsAheadOfBase(
  repoFullName: string,
  branch: string,
  token: string,
  fetchImpl: Fetcher = fetch,
  limit = 50,
): Promise<CommitInfo[]> {
  const base = await getRepoDefaultBranch(repoFullName, token, fetchImpl);
  // A branch compared with itself is zero ahead; skip the round-trip and never
  // let the base branch's own history be attributed to an item.
  if (base === branch) return [];

  const compare = `https://api.github.com/repos/${repoFullName}/compare/${encodeURIComponent(base)}...${encodeURIComponent(branch)}`;

  const page = async (n: number): Promise<{ total: number; commits: unknown[] } | null> => {
    const res = await fetchImpl(`${compare}?per_page=${COMPARE_PAGE_SIZE}&page=${n}`, {
      headers: ghHeaders(token),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { commits?: unknown; total_commits?: unknown };
    if (!Array.isArray(body.commits)) return null;
    const total = typeof body.total_commits === 'number' ? body.total_commits : body.commits.length;
    return { total, commits: body.commits };
  };

  const first = await page(1);
  if (!first) return [];

  let commits = first.commits;
  const lastPage = Math.ceil(first.total / COMPARE_PAGE_SIZE);
  if (lastPage > 1) {
    // Walk to the end. Two pages always cover any `limit` <= COMPARE_PAGE_SIZE,
    // because the final page may hold as few as one commit.
    const tail: unknown[] = [];
    for (const n of [lastPage - 1, lastPage]) {
      if (n <= 1) continue;
      const p = await page(n);
      if (p) tail.push(...p.commits);
    }
    if (tail.length) commits = lastPage === 2 ? [...first.commits, ...tail] : tail;
  }

  // Oldest-first, so the newest `limit` are at the end.
  return commits.slice(-limit).map((c) => mapCommit(c as Record<string, unknown>));
}

export function mapCommit(c: Record<string, unknown>): CommitInfo {
  const commit = (c.commit ?? {}) as Record<string, unknown>;
  const author = (commit.author ?? {}) as Record<string, unknown>;
  const ghAuthor = c.author as { login?: string } | null | undefined;
  return {
    sha: String(c.sha ?? ''),
    message: String(commit.message ?? ''),
    authorLogin: ghAuthor?.login ?? null,
    authorName: String(author.name ?? ''),
    url: String(c.html_url ?? ''),
    committedAt: String(author.date ?? new Date(0).toISOString()),
  };
}

// ------------------------------------------------------------- PR backlinks

/** Marker so the app can find and update its own comment instead of spamming. */
export const BACKLINK_MARKER = '<!-- ida-agile:backlink -->';

export async function upsertPrBacklinkComment(
  repoFullName: string,
  prNumber: number,
  bodyMarkdown: string,
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<{ action: 'created' | 'updated' | 'skipped'; id?: number }> {
  const body = `${BACKLINK_MARKER}\n${bodyMarkdown}`;

  // Find a previous comment of ours to edit.
  const listRes = await fetchImpl(
    `https://api.github.com/repos/${repoFullName}/issues/${prNumber}/comments?per_page=100`,
    { headers: ghHeaders(token) },
  );
  if (listRes.ok) {
    const comments = (await listRes.json()) as Array<{ id: number; body?: string }>;
    const mine = Array.isArray(comments)
      ? comments.find((c) => typeof c.body === 'string' && c.body.includes(BACKLINK_MARKER))
      : undefined;
    if (mine) {
      const patch = await fetchImpl(
        `https://api.github.com/repos/${repoFullName}/issues/comments/${mine.id}`,
        {
          method: 'PATCH',
          headers: { ...ghHeaders(token), 'content-type': 'application/json' },
          body: JSON.stringify({ body }),
        },
      );
      if (!patch.ok) throw new GitHubError('Could not update the backlink comment.', patch.status);
      return { action: 'updated', id: mine.id };
    }
  }

  const res = await fetchImpl(
    `https://api.github.com/repos/${repoFullName}/issues/${prNumber}/comments`,
    {
      method: 'POST',
      headers: { ...ghHeaders(token), 'content-type': 'application/json' },
      body: JSON.stringify({ body }),
    },
  );
  if (!res.ok) throw new GitHubError('Could not post the backlink comment.', res.status);
  const created = (await res.json()) as { id?: number };
  return { action: 'created', id: created.id };
}

export async function setCommitStatus(
  repoFullName: string,
  sha: string,
  status: { state: 'success' | 'pending' | 'failure'; description: string; targetUrl?: string },
  token: string,
  fetchImpl: Fetcher = fetch,
): Promise<boolean> {
  const res = await fetchImpl(`https://api.github.com/repos/${repoFullName}/statuses/${sha}`, {
    method: 'POST',
    headers: { ...ghHeaders(token), 'content-type': 'application/json' },
    body: JSON.stringify({
      state: status.state,
      description: status.description.slice(0, 140),
      target_url: status.targetUrl,
      context: 'ida-agile/work-item',
    }),
  });
  return res.ok;
}
