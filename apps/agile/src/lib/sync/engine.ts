import { config } from '@/lib/env';
import {
  findItemByBranch,
  findItemsByPullRequest,
  getWorkItem,
  linkPullRequest,
  recordCommits,
  recordPrLinkActivity,
  updateWorkItem,
} from '@/lib/domain/queries';
import { extractWorkItemRefs } from '@/lib/github/prs';
import type { WorkItem } from '@/lib/domain/workitem';
import { decideProgression, progressionPath, type ProgressionTrigger } from './progression';
import { syncBacklinkComment } from './backlink';

/**
 * Applies git activity to the board.
 *
 * Shared by the webhook receiver and the polling fallback, so both paths
 * produce identical results and only the *transport* differs.
 */

export interface SyncOutcome {
  itemsTouched: number[];
  transitions: Array<{ itemId: number; from: string; to: string; note: string }>;
  warnings: string[];
}

const empty = (): SyncOutcome => ({ itemsTouched: [], transitions: [], warnings: [] });

/** Applies a progression decision, walking legal intermediate states. */
async function applyProgression(
  item: WorkItem,
  trigger: ProgressionTrigger,
  outcome: SyncOutcome,
): Promise<void> {
  const decision = decideProgression(item, trigger);
  if (decision.warning) outcome.warnings.push(decision.warning);
  if (!decision.toState) return;

  const path = progressionPath(item.state, decision.toState);
  let current = item.state;
  for (const next of path) {
    const updated = await updateWorkItem(
      item.id,
      { state: next },
      { login: 'github', source: 'github', note: decision.note },
    );
    if (!updated) break;
    outcome.transitions.push({ itemId: item.id, from: current, to: next, note: decision.note });
    current = next;
  }
}

/** Items referenced by `AB#12` / `agile#12` in free text. */
async function itemsFromText(...texts: Array<string | null | undefined>): Promise<WorkItem[]> {
  const ids = extractWorkItemRefs(...texts);
  const items: WorkItem[] = [];
  for (const id of ids) {
    const item = await getWorkItem(id);
    if (item) items.push(item);
  }
  return items;
}

export interface PushPayload {
  repoFullName: string;
  branch: string;
  commits: Array<{
    sha: string;
    message: string;
    authorLogin: string | null;
    authorName: string;
    url: string;
    committedAt: string;
  }>;
}

export async function handlePush(payload: PushPayload): Promise<SyncOutcome> {
  const outcome = empty();
  if (!config.isKnownRepo(payload.repoFullName) || !payload.commits.length) return outcome;

  // Primary join key: the branch this board created for the item.
  const byBranch = await findItemByBranch(payload.repoFullName, payload.branch);

  // Secondary: commits on ANY branch can name an item in their message.
  const byMessage = await itemsFromText(...payload.commits.map((c) => c.message));

  const targets = new Map<number, WorkItem>();
  if (byBranch) targets.set(byBranch.id, byBranch);
  for (const item of byMessage) targets.set(item.id, item);

  for (const item of targets.values()) {
    // A branch match attributes every commit; a message match attributes only
    // the commits that actually mention the item.
    const commits =
      byBranch && byBranch.id === item.id
        ? payload.commits
        : payload.commits.filter((c) => extractWorkItemRefs(c.message).includes(item.id));
    if (!commits.length) continue;

    const inserted = await recordCommits(item.id, payload.repoFullName, payload.branch, commits);
    outcome.itemsTouched.push(item.id);

    if (inserted > 0) {
      await applyProgression(
        item,
        { kind: 'commit', branch: payload.branch, count: item.commitCount + inserted },
        outcome,
      );
    }
  }

  return outcome;
}

export interface PrPayload {
  repoFullName: string;
  number: number;
  url: string;
  title: string;
  body: string;
  state: string;
  merged: boolean;
  draft: boolean;
  headRef: string;
  baseRef: string;
  checksState?: string | null;
  action: string;
}

export async function handlePullRequest(
  pr: PrPayload,
  githubToken: string | null = null,
): Promise<SyncOutcome> {
  const outcome = empty();
  if (!config.isKnownRepo(pr.repoFullName)) return outcome;

  const targets = new Map<number, WorkItem>();

  // 1. The branch this board created carries the item id.
  const byBranch = await findItemByBranch(pr.repoFullName, pr.headRef);
  if (byBranch) targets.set(byBranch.id, byBranch);

  // 2. Explicit AB#<id> references in the title or body.
  for (const item of await itemsFromText(pr.title, pr.body)) targets.set(item.id, item);

  // 3. Anything already linked to this PR stays in sync.
  for (const item of await findItemsByPullRequest(pr.repoFullName, pr.number)) {
    targets.set(item.id, item);
  }

  for (const item of targets.values()) {
    const alreadyLinked = item.pullRequests.some(
      (p) => p.repoFullName === pr.repoFullName && p.prNumber === pr.number,
    );

    await linkPullRequest(
      item.id,
      {
        repoFullName: pr.repoFullName,
        prNumber: pr.number,
        url: pr.url,
        title: pr.title,
        prState: pr.merged ? 'merged' : pr.state,
        merged: pr.merged,
        draft: pr.draft,
        checksState: pr.checksState ?? null,
        headRef: pr.headRef,
        baseRef: pr.baseRef,
      },
      { login: 'github', source: 'github', note: `PR #${pr.number} ${pr.action}` },
    );

    if (!alreadyLinked) {
      await recordPrLinkActivity(
        item.id,
        { login: 'github', source: 'github', note: `auto-linked from ${pr.headRef || 'PR reference'}` },
        pr.number,
        pr.repoFullName,
      );
    }
    outcome.itemsTouched.push(item.id);

    const trigger: ProgressionTrigger | null = pr.merged
      ? { kind: 'pr-merged', prNumber: pr.number, repo: pr.repoFullName }
      : pr.state === 'closed'
        ? { kind: 'pr-closed-unmerged', prNumber: pr.number, repo: pr.repoFullName }
        : pr.action === 'opened' || pr.action === 'reopened' || pr.action === 'ready_for_review'
          ? { kind: 'pr-opened', prNumber: pr.number, repo: pr.repoFullName }
          : null;

    if (trigger) await applyProgression(item, trigger, outcome);

    // Backlink comment reflects the item's state AFTER any transition.
    const fresh = await getWorkItem(item.id);
    if (fresh) await syncBacklinkComment(fresh, pr.repoFullName, pr.number, githubToken);
  }

  return outcome;
}

/** check_suite / check_run: refresh the stored checks state for a PR. */
export async function handleCheckState(
  repoFullName: string,
  prNumbers: number[],
  checksState: string | null,
): Promise<SyncOutcome> {
  const outcome = empty();
  if (!config.isKnownRepo(repoFullName)) return outcome;

  for (const number of prNumbers) {
    const items = await findItemsByPullRequest(repoFullName, number);
    for (const item of items) {
      const existing = item.pullRequests.find(
        (p) => p.repoFullName === repoFullName && p.prNumber === number,
      );
      if (!existing) continue;
      await linkPullRequest(
        item.id,
        {
          repoFullName,
          prNumber: number,
          url: existing.url,
          title: existing.title,
          prState: existing.prState,
          merged: existing.merged,
          draft: existing.draft,
          checksState,
          headRef: existing.headRef,
          baseRef: existing.baseRef,
        },
        { login: 'github', source: 'github', note: 'checks updated' },
      );
      outcome.itemsTouched.push(item.id);
    }
  }
  return outcome;
}
