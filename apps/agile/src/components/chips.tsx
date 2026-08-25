import type { PullRequestLink, WorkItemState, WorkItemType } from '@/lib/domain/workitem';

const TYPE_COLOR: Record<WorkItemType, string> = {
  Story: 'var(--type-story)',
  Task: 'var(--type-task)',
  Bug: 'var(--type-bug)',
  Spike: 'var(--type-spike)',
};

export const STATE_COLOR: Record<WorkItemState, string> = {
  New: 'var(--state-new)',
  Active: 'var(--state-active)',
  Resolved: 'var(--state-resolved)',
  Closed: 'var(--state-closed)',
  Removed: 'var(--text-faint)',
};

const PRIORITY_COLOR = ['', 'var(--pri-1)', 'var(--pri-2)', 'var(--pri-3)', 'var(--pri-4)'];

export function TypeChip({ type }: { type: WorkItemType }) {
  return (
    <span className="type-chip" style={{ color: TYPE_COLOR[type] }}>
      <span className="type-bar" style={{ background: TYPE_COLOR[type] }} aria-hidden="true" />
      {type}
    </span>
  );
}

export function StateBadge({ state }: { state: WorkItemState }) {
  return (
    <span className="state-badge" style={{ color: STATE_COLOR[state] }}>
      <span className="column-dot" style={{ background: STATE_COLOR[state] }} aria-hidden="true" />
      {state}
    </span>
  );
}

export function PriorityChip({ priority }: { priority: number }) {
  return (
    <span className="pri" style={{ color: PRIORITY_COLOR[priority] ?? 'var(--text-faint)' }} title={`Priority ${priority}`}>
      P{priority}
    </span>
  );
}

export function Assignee({
  login,
  avatarUrl,
  showName = true,
}: {
  login: string | null;
  avatarUrl?: string | null;
  showName?: boolean;
}) {
  // On a dense board card an "unassigned" placeholder is pure noise, so the
  // slot simply stays empty there; the detail view still says it explicitly.
  if (!login) return showName ? <span className="muted">Unassigned</span> : null;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} title={login}>
      {avatarUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="avatar-sm" src={avatarUrl} alt="" />
      ) : null}
      {showName ? <span>{login}</span> : null}
    </span>
  );
}

export function ChecksDot({ state }: { state: string }) {
  const color =
    state === 'success'
      ? 'var(--ok)'
      : state === 'failure' || state === 'error'
        ? 'var(--danger)'
        : 'var(--warn)';
  return (
    <span style={{ color }} title={`Checks: ${state}`} aria-hidden="true">
      &#9679;
    </span>
  );
}

export function PrChip({ pr }: { pr: PullRequestLink }) {
  const cls = pr.merged ? 'pr-merged' : pr.prState === 'closed' ? 'pr-closed' : 'pr-open';
  const label = pr.merged ? 'merged' : pr.draft ? 'draft' : pr.prState;
  return (
    <a
      className="pr-chip"
      href={pr.url}
      target="_blank"
      rel="noopener noreferrer"
      title={`${pr.repoFullName}#${pr.prNumber} — ${pr.title} (${label})${
        pr.behindBy ? ` · ${pr.behindBy} behind` : ''
      }`}
      onClick={(e) => e.stopPropagation()}
      draggable={false}
    >
      <span className={cls} aria-hidden="true">
        &#9679;
      </span>
      #{pr.prNumber}
      {pr.checksState ? <ChecksDot state={pr.checksState} /> : null}
    </a>
  );
}

export function GitBranchIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M11.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm-2.25.75a2.25 2.25 0 1 1 3 2.122V6A2.5 2.5 0 0 1 10 8.5H6a1 1 0 0 0-1 1v1.128a2.251 2.251 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.5 0v1.836A2.492 2.492 0 0 1 6 7h4a1 1 0 0 0 1-1v-.628A2.25 2.25 0 0 1 9.5 3.25ZM4.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM3.5 3.25a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z" />
    </svg>
  );
}

export function CommitIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z" />
    </svg>
  );
}
