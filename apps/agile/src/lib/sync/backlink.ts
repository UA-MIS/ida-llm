import { config } from '@/lib/env';
import { upsertPrBacklinkComment, setCommitStatus } from '@/lib/github/client';
import { setBacklinkCommentId } from '@/lib/domain/queries';
import type { WorkItem } from '@/lib/domain/workitem';

/**
 * Keeps ONE authoritative comment on a pull request pointing back at the work
 * item, so the linkage is discoverable from GitHub and not only from the board.
 *
 * The comment is found-and-edited rather than re-posted, so a busy PR does not
 * accumulate a stream of bot comments.
 *
 * Every failure here is swallowed by design: a backlink is a courtesy, and it
 * must never fail the link operation that triggered it.
 */
export function renderBacklinkBody(item: WorkItem, boardUrl: string): string {
  const url = `${boardUrl}/items/${item.id}`;
  const assignee = item.assigneeLogin ? `@${item.assigneeLogin}` : '_unassigned_';
  const points = item.storyPoints === null ? '—' : String(item.storyPoints);
  return [
    `### 🗂️ Work item [#${item.id} — ${item.title}](${url})`,
    '',
    `| | |`,
    `|---|---|`,
    `| **Type** | ${item.itemType} |`,
    `| **State** | ${item.state} |`,
    `| **Assignee** | ${assignee} |`,
    `| **Points** | ${points} |`,
    '',
    `Tracked on the [${config.boardTitle}](${boardUrl}) board. This comment updates itself as the item changes.`,
  ].join('\n');
}

export async function syncBacklinkComment(
  item: WorkItem,
  repoFullName: string,
  prNumber: number,
  githubToken: string | null,
): Promise<{ ok: boolean; reason?: string }> {
  if (!config.prBacklinkComments) return { ok: false, reason: 'disabled' };
  if (!githubToken) {
    // A webhook-driven event has no user in context. Documented in the README:
    // commenting then requires a GitHub App or bot PAT. Degrade quietly.
    return { ok: false, reason: 'no-credential' };
  }

  try {
    const result = await upsertPrBacklinkComment(
      repoFullName,
      prNumber,
      renderBacklinkBody(item, config.appUrl),
      githubToken,
    );
    if (result.id) {
      await setBacklinkCommentId(item.id, repoFullName, prNumber, result.id);
    }
    return { ok: true };
  } catch (err) {
    console.warn('[backlink] could not sync PR comment', (err as Error).message);
    return { ok: false, reason: (err as Error).message };
  }
}

/** Optional commit status so "is this attached to a story?" shows in PR checks. */
export async function syncCommitStatus(
  item: WorkItem | null,
  repoFullName: string,
  headSha: string,
  githubToken: string | null,
): Promise<boolean> {
  if (!config.prCommitStatus || !githubToken || !headSha) return false;
  try {
    return await setCommitStatus(
      repoFullName,
      headSha,
      item
        ? {
            state: 'success',
            description: `Linked to #${item.id} — ${item.title} (${item.state})`,
            targetUrl: `${config.appUrl}/items/${item.id}`,
          }
        : {
            state: 'pending',
            description: 'No work item linked to this pull request',
            targetUrl: config.appUrl,
          },
      githubToken,
    );
  } catch {
    return false;
  }
}
