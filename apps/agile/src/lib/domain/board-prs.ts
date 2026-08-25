import { extractWorkItemRefs } from '@/lib/github/prs';
import type { PullRequestLink } from './workitem';

/**
 * Shaping the board's attached pull requests for `GET /api/v1/prs`.
 *
 * Kept apart from the query so the shape is testable without a database, and
 * so the endpoint's contract lives somewhere a reader can see all of it.
 *
 * The board stores ONE ROW PER ATTACHMENT (`pull_request_links` is unique on
 * item + repo + number), so a PR touching three items is three rows. Callers of
 * this endpoint want pull requests, not attachment rows, so the rows are
 * collapsed to one entry per distinct PR carrying every item it is attached to.
 */

/** A `pull_request_links` row joined to the work item it hangs off. */
export interface LinkedPullRequest extends PullRequestLink {
  itemTitle: string;
}

export interface BoardPullRequestItem {
  id: number;
  title: string;
}

export interface BoardPullRequest {
  repoFullName: string;
  prNumber: number;
  url: string;
  title: string;
  prState: string;
  merged: boolean;
  draft: boolean;
  checksState: string | null;
  behindBy: number | null;
  headRef: string;
  baseRef: string;
  lastSyncedAt: string | null;
  /** Items this PR is ACTUALLY attached to. Authoritative. */
  items: BoardPullRequestItem[];
  /**
   * `AB#<id>` references found in the PR title: a hint about items the PR
   * mentions but is not attached to. Never confuse it with `items`.
   */
  suggestedItemIds: number[];
}

/** How recently GitHub last confirmed a row. Never-synced and unparseable sort last. */
function parseSyncedAt(iso: string | null): number {
  if (!iso) return Number.NEGATIVE_INFINITY;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}

const syncedAt = (link: LinkedPullRequest): number => parseSyncedAt(link.lastSyncedAt);

function prKey(link: LinkedPullRequest): string {
  // GitHub treats owner/repo case-insensitively and the board accepts whatever
  // a person pasted, so two spellings of one repo must not become two PRs.
  return `${link.repoFullName.toLowerCase()}#${link.prNumber}`;
}

/**
 * Collapses attachment rows into pull requests.
 *
 * Ordering and fact-selection are computed here rather than assumed from the
 * caller's ORDER BY, so the result is identical for any input permutation:
 *
 *  - a PR's facts come from its most recently synced row, because two rows for
 *    one PR can disagree after a partial sync and the newer one is the truth;
 *  - results are newest-synced first, then repo name, then PR number desc.
 */
export function groupLinkedPullRequests(links: LinkedPullRequest[]): BoardPullRequest[] {
  const groups = new Map<string, LinkedPullRequest[]>();
  for (const link of links) {
    const key = prKey(link);
    const bucket = groups.get(key);
    if (bucket) bucket.push(link);
    else groups.set(key, [link]);
  }

  const out: BoardPullRequest[] = [];
  for (const bucket of groups.values()) {
    // Stable: `reduce` keeps the earliest row on a tie.
    const newest = bucket.reduce((best, row) => (syncedAt(row) > syncedAt(best) ? row : best));

    const items = new Map<number, BoardPullRequestItem>();
    for (const row of bucket) {
      if (!items.has(row.itemId)) items.set(row.itemId, { id: row.itemId, title: row.itemTitle });
    }

    out.push({
      repoFullName: newest.repoFullName,
      prNumber: newest.prNumber,
      url: newest.url,
      title: newest.title,
      prState: newest.prState,
      merged: newest.merged,
      draft: newest.draft,
      checksState: newest.checksState,
      behindBy: newest.behindBy,
      headRef: newest.headRef,
      baseRef: newest.baseRef,
      lastSyncedAt: newest.lastSyncedAt,
      items: [...items.values()].sort((a, b) => a.id - b.id),
      suggestedItemIds: extractWorkItemRefs(newest.title),
    });
  }

  return out.sort((a, b) => {
    // Subtraction is wrong here: two never-synced rows would give
    // -Infinity - -Infinity = NaN, and a NaN comparator silently produces an
    // arbitrary order. Compare, do not subtract.
    const ra = parseSyncedAt(a.lastSyncedAt);
    const rb = parseSyncedAt(b.lastSyncedAt);
    if (ra !== rb) return rb > ra ? 1 : -1;
    const byRepo = a.repoFullName.toLowerCase().localeCompare(b.repoFullName.toLowerCase());
    if (byRepo !== 0) return byRepo;
    return b.prNumber - a.prNumber;
  });
}
