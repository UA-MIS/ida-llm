import { config } from '@/lib/env';
import {
  attributionNote,
  missingCredentialMessage,
  type GitHubCredential,
} from './credential';
import { createBranch, GitHubError } from './client';
import { renderBranchName, type WorkItem } from '@/lib/domain/workitem';
import { setItemBranch } from '@/lib/domain/queries';
import type { Actor } from '@/lib/domain/workitem';

export type StartWorkOutcome =
  | { status: 'created'; branch: string; url: string; item: WorkItem }
  | { status: 'existing'; branch: string; url: string; item: WorkItem }
  | { status: 'disabled'; message: string }
  | { status: 'failed'; message: string };

/**
 * Creates (or adopts) the branch for a work item.
 *
 * Two properties matter to callers:
 *  - **Idempotent** — if the item already has a branch, or the ref already
 *    exists on GitHub, it is adopted rather than recreated.
 *  - **Never fatal** — every failure is returned as `failed` with a specific
 *    message. Callers must let the state transition succeed regardless; a
 *    GitHub hiccup must never block the board.
 */
export async function startWork(
  item: WorkItem,
  actor: Actor,
  credential: GitHubCredential,
  repoOverride?: string,
): Promise<StartWorkOutcome> {
  if (!config.autoBranch) {
    return { status: 'disabled', message: 'Automatic branch creation is disabled (AUTO_BRANCH=false).' };
  }
  if (!credential.token) {
    return { status: 'failed', message: missingCredentialMessage('Creating a branch') };
  }

  const repo = repoOverride ?? item.branchRepo ?? config.primaryRepo;
  if (!config.isKnownRepo(repo)) {
    return { status: 'failed', message: `Repository ${repo} is not configured for this board.` };
  }

  // An item that already has a branch keeps it.
  const branchName = item.branchName ?? renderBranchName(config.branchPattern, item);

  try {
    const result = await createBranch(repo, branchName, credential.token);
    // When the app credential acted, history says so rather than implying the
    // user pushed the ref themselves.
    const saved = await setItemBranch(
      item.id,
      { repoFullName: repo, name: result.branch, url: result.url },
      { ...actor, note: [actor.note, attributionNote(credential.source)].filter(Boolean).join(' — ') || undefined },
    );
    return {
      status: result.existed ? 'existing' : 'created',
      branch: result.branch,
      url: result.url,
      item: saved ?? item,
    };
  } catch (err) {
    if (err instanceof GitHubError) {
      const hint =
        err.status === 403 || err.status === 404
          ? ` You may not have push access to ${repo}.`
          : '';
      return { status: 'failed', message: `${err.message}${hint}` };
    }
    return { status: 'failed', message: `Could not create the branch: ${(err as Error).message}` };
  }
}

/** The command a developer pastes to get onto the branch. */
export function checkoutCommand(branch: string): string {
  return `git fetch origin && git switch ${branch}`;
}
