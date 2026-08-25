import { config } from '@/lib/env';
import { canTransition, type WorkItem, type WorkItemState } from '@/lib/domain/workitem';

/**
 * The ADO-style rules that let git activity drive the board.
 *
 * These are pure decisions — no I/O — so every rule is directly testable and
 * the caller stays in control of persistence. `Closed` is deliberately NOT
 * automated: merging resolves an item, a human accepts it. That keeps a review
 * beat in the process, which is exactly ADO's model.
 */
export type ProgressionTrigger =
  | { kind: 'commit'; branch: string; count: number }
  | { kind: 'pr-opened'; prNumber: number; repo: string }
  | { kind: 'pr-merged'; prNumber: number; repo: string }
  | { kind: 'pr-closed-unmerged'; prNumber: number; repo: string };

export interface ProgressionDecision {
  /** Null means "no state change" — which is a normal, common outcome. */
  toState: WorkItemState | null;
  /** Recorded in history so a human can always see why an item moved. */
  note: string;
  /** Surfaced on the item as a badge rather than a state change. */
  warning?: string;
}

export function decideProgression(
  item: Pick<WorkItem, 'state'>,
  trigger: ProgressionTrigger,
): ProgressionDecision {
  switch (trigger.kind) {
    case 'commit': {
      if (!config.autoProgressOnCommit) return { toState: null, note: '' };
      const note = `moved by GitHub (${trigger.count === 1 ? 'first commit' : `${trigger.count} commits`} pushed to ${trigger.branch})`;
      // Only wakes a New item; work already in flight is left alone.
      if (item.state === 'New' && canTransition('New', 'Active')) {
        return { toState: 'Active', note };
      }
      return { toState: null, note: '' };
    }

    case 'pr-opened': {
      if (!config.autoProgressOnPrOpen) return { toState: null, note: '' };
      const note = `moved by GitHub (PR #${trigger.prNumber} opened)`;
      if (item.state === 'New') return { toState: 'Active', note };
      // A resolved item that gets a new PR is being worked on again.
      if (item.state === 'Resolved' && canTransition('Resolved', 'Active')) {
        return { toState: 'Active', note };
      }
      return { toState: null, note: '' };
    }

    case 'pr-merged': {
      if (!config.autoProgressOnPrMerge) return { toState: null, note: '' };
      const note = `moved by GitHub (PR #${trigger.prNumber} merged)`;
      if (item.state === 'Active') return { toState: 'Resolved', note };
      if (item.state === 'New') {
        // A merge on a New item still ends at Resolved. New -> Resolved is not
        // a legal single transition, so the caller walks the path returned by
        // progressionPath(), which steps through Active.
        return { toState: 'Resolved', note: `${note} — advanced through Active` };
      }
      return { toState: null, note: '' };
    }

    case 'pr-closed-unmerged':
      // Deliberately no state change: abandoning a PR is not progress, and
      // silently moving the item would hide that from the team.
      return {
        toState: null,
        note: '',
        warning: `PR #${trigger.prNumber} was closed without merging`,
      };
  }
}

/**
 * Merging can imply two hops (New -> Active -> Resolved). Returns the legal
 * path so the caller can apply it one transition at a time.
 */
export function progressionPath(from: WorkItemState, to: WorkItemState): WorkItemState[] {
  if (from === to) return [];
  if (canTransition(from, to)) return [to];
  // One intermediate hop is enough for every rule above.
  for (const mid of ['Active', 'Resolved'] as WorkItemState[]) {
    if (canTransition(from, mid) && canTransition(mid, to)) return [mid, to];
  }
  return [];
}
