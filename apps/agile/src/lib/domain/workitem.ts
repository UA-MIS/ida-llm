import { z } from 'zod';

/** ADO "Agile" process states. Removed is a terminal side-state, off the board. */
export const WORK_ITEM_STATES = ['New', 'Active', 'Resolved', 'Closed', 'Removed'] as const;
export type WorkItemState = (typeof WORK_ITEM_STATES)[number];

/** Columns rendered on the kanban board, in order. Removed is intentionally excluded. */
export const BOARD_COLUMNS: readonly WorkItemState[] = ['New', 'Active', 'Resolved', 'Closed'];

export const WORK_ITEM_TYPES = ['Story', 'Task', 'Bug', 'Spike'] as const;
export type WorkItemType = (typeof WORK_ITEM_TYPES)[number];

/**
 * Types whose work lives in git, and which therefore get a branch when started.
 *
 * A Spike is pure research and a Task is often coordination or paperwork —
 * neither produces a commit, so cutting a branch for one creates a ref nobody
 * will ever push to, and a card that advertises a branch that will be deleted
 * unused (AB#25 started a research spike and got `spike/25-...`). Story and Bug
 * are the types that end in a diff, so they keep the existing behaviour.
 */
export const BRANCHING_ITEM_TYPES: readonly WorkItemType[] = ['Story', 'Bug'];

/** Whether this type gets a branch by default when "Start work" is pressed. */
export function typeCreatesBranch(itemType: WorkItemType): boolean {
  return BRANCHING_ITEM_TYPES.includes(itemType);
}

/**
 * The branch decision for one "Start work" call.
 *
 * The type-based default is the rule; `explicit` is the caller's override, so a
 * spike that genuinely needs a scratch branch can ask for one (`{branch:true}`)
 * and a story that does not can decline (`{branch:false}`). Undefined — the
 * shape every current UI caller sends — means "use the default for this type".
 */
export function shouldCreateBranch(itemType: WorkItemType, explicit?: boolean): boolean {
  if (typeof explicit === 'boolean') return explicit;
  return typeCreatesBranch(itemType);
}

/** 1 = highest. Mirrors ADO's 1..4 priority field. */
export const PRIORITIES = [1, 2, 3, 4] as const;

/**
 * Allowed state transitions.
 *
 * Modelled on ADO's Agile process: work flows forward New -> Active -> Resolved
 * -> Closed, can be sent back one step for rework, can be reactivated from
 * Closed, and can be Removed from any non-closed state.
 */
const TRANSITIONS: Record<WorkItemState, readonly WorkItemState[]> = {
  New: ['Active', 'Removed'],
  Active: ['Resolved', 'New', 'Removed'],
  Resolved: ['Closed', 'Active'],
  Closed: ['Active'],
  Removed: ['New'],
};

export function allowedTransitions(from: WorkItemState): readonly WorkItemState[] {
  return TRANSITIONS[from];
}

/** A no-op transition (same state) is always allowed — it changes nothing. */
export function canTransition(from: WorkItemState, to: WorkItemState): boolean {
  if (from === to) return true;
  return TRANSITIONS[from].includes(to);
}

export class InvalidTransitionError extends Error {
  constructor(
    readonly from: WorkItemState,
    readonly to: WorkItemState,
  ) {
    super(
      `Cannot move a work item from "${from}" to "${to}". Allowed from "${from}": ${
        TRANSITIONS[from].join(', ') || 'none'
      }.`,
    );
    this.name = 'InvalidTransitionError';
  }
}

export function assertTransition(from: WorkItemState, to: WorkItemState): void {
  if (!canTransition(from, to)) throw new InvalidTransitionError(from, to);
}

/** States that count as "finished" for burndown/capacity maths. */
export function isDone(state: WorkItemState): boolean {
  return state === 'Closed' || state === 'Removed';
}

// ---------------------------------------------------------------------------
// Validation schemas (shared by API routes and forms)
// ---------------------------------------------------------------------------

const stateSchema = z.enum(WORK_ITEM_STATES);
const typeSchema = z.enum(WORK_ITEM_TYPES);

const tagSchema = z
  .string()
  .trim()
  .min(1)
  .max(40)
  .regex(/^[\w][\w .+/-]*$/, 'Tags may only contain letters, numbers and . _ + / -');

/**
 * Field rules WITHOUT defaults.
 *
 * Create and update validate a field identically but must disagree about what a
 * MISSING key means, so the rules are declared once here and each schema below
 * layers its own missing-key policy on top.
 */
const workItemFields = {
  title: z.string().trim().min(1, 'Title is required').max(300),
  description: z.string().max(20_000),
  itemType: typeSchema,
  state: stateSchema,
  assigneeLogin: z.string().trim().max(100).nullable(),
  assigneeAvatarUrl: z.string().url().max(500).nullable(),
  storyPoints: z.number().int().min(0).max(1000).nullable(),
  priority: z.number().int().min(1).max(4),
  sprintId: z.number().int().positive().nullable(),
  tags: z.array(tagSchema).max(20),
  /** Optional; only meaningful when the board follows more than one repo. */
  repoFullName: z.string().regex(/^[\w.-]+\/[\w.-]+$/).nullable(),
  /** Free-form band, e.g. "Wave 1". Kept as text so teams pick their own scheme. */
  wave: z.string().trim().max(40).nullable(),
};

/** Create: a missing key takes the field's default. Only `title` is required. */
export const createWorkItemSchema = z.object({
  ...workItemFields,
  description: workItemFields.description.default(''),
  itemType: workItemFields.itemType.default('Story'),
  state: workItemFields.state.default('New'),
  assigneeLogin: workItemFields.assigneeLogin.default(null),
  assigneeAvatarUrl: workItemFields.assigneeAvatarUrl.default(null),
  storyPoints: workItemFields.storyPoints.default(null),
  priority: workItemFields.priority.default(2),
  sprintId: workItemFields.sprintId.default(null),
  tags: workItemFields.tags.default([]),
  repoFullName: workItemFields.repoFullName.default(null),
  wave: workItemFields.wave.default(null),
});

/**
 * Update: JSON merge-patch semantics.
 *
 *   key present with a value  -> update that field
 *   key present as null       -> deliberate clear, e.g. {"sprintId": null} sends
 *                                an item back to the backlog
 *   key ABSENT                -> leave the stored value untouched
 *
 * Deliberately built from the UN-DEFAULTED fields. `createWorkItemSchema.partial()`
 * reads as equivalent and is not: `.partial()` wraps each field in ZodOptional but
 * does NOT strip its ZodDefault, so parsing `{"assigneeLogin":"x"}` returned every
 * OTHER key filled in with its default. `updateWorkItem` skips only `undefined`
 * values, so those defaults were written to the row — a partial PATCH silently
 * blanked description, wave, repoFullName, storyPoints and sprintId, and the
 * injected `state: 'New'` made assigning a Resolved/Closed item fail as an illegal
 * transition (AB#28). Keep this derived from `workItemFields`, never from
 * `createWorkItemSchema`.
 *
 * STRICT on purpose. A key that is not a writable field is a client bug, and the
 * endpoint used to answer it with 200 having changed nothing: `PATCH
 * {"branchName": null}` — a reasonable guess at how to clear a dead branch link
 * — was accepted, silently dropped, and reported success. "The API said 200 and
 * you believed it" is the same failure family as AB#28, so an unrecognised key
 * now fails as 422 `validation_failed` and names itself. Merge-patch semantics
 * for the WRITABLE set above are unchanged: absent still means untouched and an
 * explicit null still clears.
 */
export const updateWorkItemSchema = z.strictObject(workItemFields).partial();

/**
 * Body of POST /api/v1/items/{id}/start-work. Strict for the same reason as
 * the PATCH schema: a misspelled `{"branches": false}` must not read as the
 * default rather than as an error.
 */
export const startWorkSchema = z.strictObject({
  /** Skip the New -> Active transition. Defaults to activating. */
  activate: z.boolean().optional(),
  /** Create (true) or skip (false) the branch, overriding the type default. */
  branch: z.boolean().optional(),
  /** Branch in a non-primary repo the board follows. */
  repo: z.string().regex(/^[\w.-]+\/[\w.-]+$/).optional(),
});

export type StartWorkInput = z.infer<typeof startWorkSchema>;

/** What a caller may pass — optional fields get their defaults on parse. */
export type CreateWorkItemInput = z.input<typeof createWorkItemSchema>;
/** Fully-defaulted shape after validation. */
export type ParsedWorkItem = z.output<typeof createWorkItemSchema>;
export type UpdateWorkItemInput = z.infer<typeof updateWorkItemSchema>;

export const sprintSchema = z
  .object({
    name: z.string().trim().min(1).max(120),
    goal: z.string().max(2000).default(''),
    startsOn: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Expected YYYY-MM-DD'),
    endsOn: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Expected YYYY-MM-DD'),
    position: z.number().int().min(0).default(0),
  })
  .refine((s) => s.endsOn >= s.startsOn, {
    message: 'Sprint end date must not be before its start date',
    path: ['endsOn'],
  });

export type SprintInput = z.input<typeof sprintSchema>;
export type ParsedSprint = z.output<typeof sprintSchema>;

/**
 * Reads the backlog's `?sprint=` filter into a `listWorkItems` sprintId filter.
 *
 *   absent / "all" -> undefined (every sprint)
 *   "none"         -> null      (items with no sprint)
 *   "12"           -> 12        (that sprint)
 *
 * Anything else — a stale bookmark, a hand-edited URL — falls back to "all"
 * rather than reaching the query layer. `Number('abc')` is NaN, and NaN is still
 * `typeof 'number'`, so an unguarded value used to be passed straight into the
 * SQL filter and error the entire backlog page with a 500 (AB#30).
 */
export function parseSprintFilter(raw: string | undefined): number | null | undefined {
  if (!raw || raw === 'all') return undefined;
  if (raw === 'none') return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : undefined;
}

/** Who or what performed a change. */
export type ActorSource = 'user' | 'api' | 'github' | 'system';

export interface Actor {
  login: string;
  source: ActorSource;
  /** Free text explaining an automated change, e.g. "PR #12 merged". */
  note?: string;
}

/** Call sites may pass a bare login for the common "a human in the UI" case. */
export type ActorLike = Actor | string;

export function toActor(actor: ActorLike): Actor {
  return typeof actor === 'string' ? { login: actor, source: 'user' } : actor;
}

export interface WorkItem {
  id: number;
  title: string;
  description: string;
  itemType: WorkItemType;
  state: WorkItemState;
  assigneeLogin: string | null;
  assigneeAvatarUrl: string | null;
  storyPoints: number | null;
  priority: number;
  sprintId: number | null;
  boardRank: number;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  closedAt: string | null;
  tags: string[];
  pullRequests: PullRequestLink[];
  commits: CommitRef[];
  commitCount: number;
  branchName: string | null;
  branchRepo: string | null;
  branchUrl: string | null;
  branchCreatedAt: string | null;
  lastActivityAt: string;
  /** Repo this item belongs to. Null when the board follows a single repo. */
  repoFullName: string | null;
  /** Human-readable ordering band, shown on every card and filterable. */
  wave: string | null;
  /** Merged PR count — the trunk-based progress signal. Commits are activity. */
  mergedPrCount: number;
  depOverrideBy: string | null;
  depOverrideReason: string | null;
}

export interface CommitRef {
  id: number;
  repoFullName: string;
  sha: string;
  message: string;
  authorLogin: string | null;
  authorName: string;
  url: string;
  branch: string;
  committedAt: string;
}

export interface Attachment {
  id: number;
  itemId: number;
  filename: string;
  contentType: string;
  sizeBytes: number;
  uploadedBy: string;
  createdAt: string;
}

export interface PullRequestLink {
  id: number;
  itemId: number;
  repoFullName: string;
  prNumber: number;
  url: string;
  title: string;
  prState: string;
  merged: boolean;
  draft: boolean;
  checksState: string | null;
  headRef: string;
  baseRef: string;
  behindBy: number | null;
  linkedBy: string;
  lastSyncedAt: string | null;
}

export interface Sprint {
  id: number;
  name: string;
  goal: string;
  startsOn: string;
  endsOn: string;
  position: number;
  /** Filled in by list queries so the selector can show counts without N calls. */
  itemCount?: number;
}

export interface Comment {
  id: number;
  itemId: number;
  authorLogin: string;
  authorAvatarUrl: string | null;
  body: string;
  createdAt: string;
}

export interface ActivityEntry {
  id: number;
  itemId: number;
  actorLogin: string;
  source: ActorSource;
  field: string;
  oldValue: string | null;
  newValue: string | null;
  note: string | null;
  createdAt: string;
}

// ---------------------------------------------------------------------------
// Branch naming
// ---------------------------------------------------------------------------

/** Git-safe slug: lowercase, hyphenated, no leading/trailing punctuation. */
export function slugify(title: string, maxLength = 48): string {
  const slug = (title ?? '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^\w\s-]/g, ' ')
    .trim()
    .replace(/[\s_]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
  if (slug.length <= maxLength) return slug || 'work-item';
  // Cut on a word boundary so the branch name stays readable.
  const cut = slug.slice(0, maxLength);
  const lastDash = cut.lastIndexOf('-');
  return (lastDash > maxLength / 2 ? cut.slice(0, lastDash) : cut).replace(/-$/, '') || 'work-item';
}

/**
 * Renders a branch name from a configurable pattern.
 * Placeholders: {type} {id} {slug} {title} {assignee}
 */
export function renderBranchName(
  pattern: string,
  item: { id: number; itemType: WorkItemType; title: string; assigneeLogin?: string | null },
): string {
  const replacements: Record<string, string> = {
    type: item.itemType.toLowerCase(),
    id: String(item.id),
    slug: slugify(item.title),
    title: slugify(item.title),
    assignee: slugify(item.assigneeLogin ?? 'unassigned', 24),
  };

  const raw = pattern.replace(/\{(\w+)\}/g, (whole, key: string) =>
    key in replacements ? (replacements[key] as string) : whole,
  );

  return sanitizeBranchName(raw);
}

/**
 * Enforces git's ref naming rules (git-check-ref-format) so a hostile or merely
 * awkward title can never produce an invalid or dangerous ref.
 */
export function sanitizeBranchName(raw: string): string {
  let name = (raw ?? '')
    .replace(/[\x00-\x20~^:?*[\\\]]/g, '-') // chars git forbids outright
    .replace(/\.\.+/g, '.')                  // no ".."
    .replace(/@\{/g, '-')                    // no "@{"
    .replace(/\/+/g, '/')                    // collapse slashes
    .replace(/-+/g, '-')
    .replace(/^[-/.]+|[-/.]+$/g, '');        // no leading/trailing / - .

  // No path component may start with a dot or end in ".lock".
  name = name
    .split('/')
    .map((part) => part.replace(/^\.+/, '').replace(/\.lock$/i, ''))
    .filter(Boolean)
    .join('/');

  if (name.length > 200) name = name.slice(0, 200).replace(/[-/.]+$/, '');
  return name || 'work-item';
}
