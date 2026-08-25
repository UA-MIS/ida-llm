import type {
  ActorSource,
  Attachment,
  CommitRef,
  ActivityEntry,
  Comment,
  PullRequestLink,
  Sprint,
  WorkItem,
  WorkItemState,
  WorkItemType,
} from './workitem';

/** pg returns DATE columns as JS Date in local time; format back to YYYY-MM-DD safely. */
export function toDateString(v: unknown): string {
  if (v instanceof Date) {
    const y = v.getFullYear();
    const m = String(v.getMonth() + 1).padStart(2, '0');
    const d = String(v.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }
  return String(v ?? '');
}

function toIso(v: unknown): string {
  return v instanceof Date ? v.toISOString() : String(v ?? '');
}

function toIsoOrNull(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  return toIso(v);
}

export interface WorkItemRow {
  id: number;
  title: string;
  description: string;
  item_type: string;
  state: string;
  assignee_login: string | null;
  assignee_avatar_url: string | null;
  story_points: number | null;
  priority: number;
  sprint_id: number | null;
  board_rank: number;
  created_by: string;
  created_at: Date;
  updated_at: Date;
  closed_at: Date | null;
  tags: string[] | null;
  pull_requests: unknown;
  commits: unknown;
  commit_count: number | string | null;
  branch_name: string | null;
  branch_repo: string | null;
  branch_url: string | null;
  last_activity_at: Date | string | null;
}

export function mapWorkItem(row: WorkItemRow): WorkItem {
  return {
    id: row.id,
    title: row.title,
    description: row.description,
    itemType: row.item_type as WorkItemType,
    state: row.state as WorkItemState,
    assigneeLogin: row.assignee_login,
    assigneeAvatarUrl: row.assignee_avatar_url,
    storyPoints: row.story_points,
    priority: row.priority,
    sprintId: row.sprint_id,
    boardRank: Number(row.board_rank),
    createdBy: row.created_by,
    createdAt: toIso(row.created_at),
    updatedAt: toIso(row.updated_at),
    closedAt: toIsoOrNull(row.closed_at),
    tags: (row.tags ?? []).filter((t): t is string => typeof t === 'string').sort(),
    pullRequests: Array.isArray(row.pull_requests)
      ? (row.pull_requests as PullRequestLinkRow[]).filter(Boolean).map(mapPullRequest)
      : [],
    commits: Array.isArray(row.commits)
      ? (row.commits as CommitRow[]).filter(Boolean).map(mapCommitRef)
      : [],
    commitCount: Number(row.commit_count ?? 0),
    branchName: row.branch_name,
    branchRepo: row.branch_repo,
    branchUrl: row.branch_url,
    lastActivityAt: toIso(row.last_activity_at ?? row.updated_at),
  };
}

export interface CommitRow {
  id: number;
  repo_full_name: string;
  sha: string;
  message: string;
  author_login: string | null;
  author_name: string;
  url: string;
  branch: string;
  committed_at: Date | string;
}

export function mapCommitRef(row: CommitRow): CommitRef {
  return {
    id: row.id,
    repoFullName: row.repo_full_name,
    sha: row.sha,
    message: row.message,
    authorLogin: row.author_login,
    authorName: row.author_name,
    url: row.url,
    branch: row.branch,
    committedAt: toIso(row.committed_at),
  };
}

export interface AttachmentRow {
  id: number;
  item_id: number;
  filename: string;
  content_type: string;
  size_bytes: number | string;
  uploaded_by: string;
  created_at: Date | string;
}

export function mapAttachment(row: AttachmentRow): Attachment {
  return {
    id: row.id,
    itemId: row.item_id,
    filename: row.filename,
    contentType: row.content_type,
    sizeBytes: Number(row.size_bytes ?? 0),
    uploadedBy: row.uploaded_by,
    createdAt: toIso(row.created_at),
  };
}

export interface PullRequestLinkRow {
  id: number;
  item_id: number;
  repo_full_name: string;
  pr_number: number;
  url: string;
  title: string;
  pr_state: string;
  merged: boolean;
  draft: boolean;
  checks_state: string | null;
  head_ref: string | null;
  base_ref: string | null;
  behind_by: number | null;
  linked_by: string;
  last_synced_at: Date | string | null;
}

export function mapPullRequest(row: PullRequestLinkRow): PullRequestLink {
  return {
    id: row.id,
    itemId: row.item_id,
    repoFullName: row.repo_full_name,
    prNumber: row.pr_number,
    url: row.url,
    title: row.title,
    prState: row.pr_state,
    merged: row.merged,
    draft: row.draft,
    checksState: row.checks_state,
    headRef: row.head_ref ?? '',
    baseRef: row.base_ref ?? '',
    behindBy: row.behind_by ?? null,
    linkedBy: row.linked_by,
    lastSyncedAt: toIsoOrNull(row.last_synced_at),
  };
}

export interface SprintRow {
  id: number;
  name: string;
  goal: string;
  starts_on: Date | string;
  ends_on: Date | string;
}

export function mapSprint(row: SprintRow): Sprint {
  return {
    id: row.id,
    name: row.name,
    goal: row.goal,
    startsOn: toDateString(row.starts_on),
    endsOn: toDateString(row.ends_on),
  };
}

export interface CommentRow {
  id: number;
  item_id: number;
  author_login: string;
  author_avatar_url: string | null;
  body: string;
  created_at: Date;
}

export function mapComment(row: CommentRow): Comment {
  return {
    id: row.id,
    itemId: row.item_id,
    authorLogin: row.author_login,
    authorAvatarUrl: row.author_avatar_url,
    body: row.body,
    createdAt: toIso(row.created_at),
  };
}

export interface ActivityRow {
  id: number;
  item_id: number;
  actor_login: string;
  source: string;
  field: string;
  old_value: string | null;
  new_value: string | null;
  note: string | null;
  created_at: Date;
}

export function mapActivity(row: ActivityRow): ActivityEntry {
  return {
    id: row.id,
    itemId: row.item_id,
    actorLogin: row.actor_login,
    source: (row.source ?? 'user') as ActorSource,
    field: row.field,
    oldValue: row.old_value,
    newValue: row.new_value,
    note: row.note ?? null,
    createdAt: toIso(row.created_at),
  };
}
