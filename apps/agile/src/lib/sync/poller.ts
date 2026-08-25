import { config } from '@/lib/env';
import { backgroundCredential } from '@/lib/github/credential';
import { query, queryOne } from '@/lib/db/pool';
import { listBranchCommits, fetchPullRequest, compareWithDefault } from '@/lib/github/client';
import { getWorkItem, linkPullRequest, listWorkItems } from '@/lib/domain/queries';
import { handlePullRequest, handlePush, type SyncOutcome } from './engine';
import type { WorkItem } from '@/lib/domain/workitem';

/**
 * Reconciliation without webhooks.
 *
 * Webhooks are the fast path. This is the fallback, in two tiers:
 *
 *  1. **On-view** (zero config) — when a member opens an item, its branch and
 *     PRs are refreshed using that member's own GitHub token, throttled per
 *     resource so a page refresh does not hammer the API.
 *  2. **Background loop** (needs GITHUB_POLL_TOKEN) — a timer sweeps recently
 *     active items unattended.
 *
 * A deployment where nobody configured the webhook therefore still converges;
 * it just converges when someone looks, rather than instantly.
 */

/** Throttle gate backed by Postgres, so it holds across replicas and restarts. */
async function shouldPoll(resource: string, minIntervalSeconds: number): Promise<boolean> {
  const row = await queryOne<{ last_polled_at: Date | null }>(
    'SELECT last_polled_at FROM poll_state WHERE instance_key = $1 AND resource = $2',
    [config.instanceKey, resource],
  );
  if (row?.last_polled_at && Date.now() - row.last_polled_at.getTime() < minIntervalSeconds * 1000) {
    return false;
  }
  await query(
    `INSERT INTO poll_state (instance_key, resource, last_polled_at)
     VALUES ($1,$2, now())
     ON CONFLICT (instance_key, resource) DO UPDATE SET last_polled_at = now()`,
    [config.instanceKey, resource],
  );
  return true;
}

const emptyOutcome = (): SyncOutcome => ({ itemsTouched: [], transitions: [], warnings: [] });

/**
 * Refreshes one item from GitHub: new commits on its branch, and the current
 * state of every linked PR. Safe to call on every page view — it self-throttles
 * and every write underneath is idempotent.
 */
export async function reconcileItem(
  item: WorkItem,
  githubToken: string | null,
  opts: { force?: boolean } = {},
): Promise<SyncOutcome> {
  const outcome = emptyOutcome();
  if (!githubToken) return outcome;

  const resource = `item:${item.id}`;
  if (!opts.force && !(await shouldPoll(resource, config.onViewRefreshSeconds))) return outcome;

  // 1. Commits on the item's branch.
  if (item.branchRepo && item.branchName && config.isKnownRepo(item.branchRepo)) {
    try {
      const commits = await listBranchCommits(item.branchRepo, item.branchName, githubToken);
      if (commits.length) {
        const pushOutcome = await handlePush({
          repoFullName: item.branchRepo,
          branch: item.branchName,
          commits: commits.map((c) => ({
            sha: c.sha,
            message: c.message,
            authorLogin: c.authorLogin,
            authorName: c.authorName,
            url: c.url,
            committedAt: c.committedAt,
          })),
        });
        merge(outcome, pushOutcome);
      }
    } catch (err) {
      outcome.warnings.push(`Could not read commits: ${(err as Error).message}`);
    }
  }

  // 2. Current state of each linked PR.
  const fresh = (await getWorkItem(item.id)) ?? item;
  for (const link of fresh.pullRequests) {
    try {
      const pr = await fetchPullRequest(link.repoFullName, link.prNumber, githubToken);
      if (!pr) continue;
      merge(
        outcome,
        await handlePullRequest(
          {
            repoFullName: pr.repoFullName,
            number: pr.number,
            url: pr.url,
            title: pr.title,
            body: pr.body,
            state: pr.state,
            merged: pr.merged,
            draft: pr.draft,
            headRef: pr.headRef,
            baseRef: pr.baseRef,
            checksState: pr.checksState,
            action: 'synchronize',
          },
          { token: githubToken, source: 'app' },
        ),
      );

      // Cheap "is this branch behind?" signal for the card.
      if (pr.headRef && !pr.merged && pr.state === 'open') {
        const cmp = await compareWithDefault(pr.repoFullName, pr.headRef, githubToken);
        if (cmp) {
          await linkPullRequest(
            fresh.id,
            {
              repoFullName: pr.repoFullName,
              prNumber: pr.number,
              url: pr.url,
              title: pr.title,
              prState: pr.state,
              merged: pr.merged,
              draft: pr.draft,
              checksState: pr.checksState,
              headRef: pr.headRef,
              baseRef: pr.baseRef,
              behindBy: cmp.behindBy,
            },
            { login: 'github', source: 'github', note: 'branch comparison refreshed' },
          );
        }
      }
    } catch (err) {
      outcome.warnings.push(`Could not refresh PR #${link.prNumber}: ${(err as Error).message}`);
    }
  }

  return outcome;
}

function merge(into: SyncOutcome, from: SyncOutcome): void {
  into.itemsTouched.push(...from.itemsTouched);
  into.transitions.push(...from.transitions);
  into.warnings.push(...from.warnings);
}

/** One unattended sweep over in-flight items. Requires GITHUB_POLL_TOKEN. */
export async function pollOnce(): Promise<SyncOutcome> {
  const outcome = emptyOutcome();
  if (!config.backgroundPollEnabled) return outcome;

  // Whatever credential the board has: the App installation token when the
  // platform App is configured, otherwise the legacy static token.
  const token = await backgroundCredential();
  if (!token) return outcome;
  const candidates = [
    ...(await listWorkItems({ state: 'Active', limit: 50 })),
    ...(await listWorkItems({ state: 'New', limit: 50 })),
  ].filter((i) => i.branchName || i.pullRequests.length);

  for (const item of candidates) {
    try {
      merge(outcome, await reconcileItem(item, token, { force: false }));
    } catch (err) {
      outcome.warnings.push(`Poll failed for #${item.id}: ${(err as Error).message}`);
    }
  }
  return outcome;
}

let timer: ReturnType<typeof setInterval> | null = null;

export function startBackgroundPoller(): void {
  if (timer || !config.backgroundPollEnabled) return;
  const intervalMs = Math.max(60, config.pollIntervalSeconds) * 1000;
  timer = setInterval(() => {
    pollOnce()
      .then((o) => {
        if (o.transitions.length) {
          console.log(`[poll] applied ${o.transitions.length} transition(s)`);
        }
      })
      .catch((err) => console.warn('[poll] sweep failed', err));
  }, intervalMs);
  // Never hold the process open for a timer.
  if (typeof timer.unref === 'function') timer.unref();
  console.log(`[poll] background reconciliation every ${config.pollIntervalSeconds}s`);
}

export function stopBackgroundPoller(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}
