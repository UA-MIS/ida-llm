'use client';

import { useCallback, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  BOARD_COLUMNS,
  canTransition,
  type Sprint,
  type WorkItem,
  type WorkItemState,
} from '@/lib/domain/workitem';
import type { TeamMember } from '@/lib/github/client';
import type { Readiness } from '@/lib/domain/dependencies';
import { evaluateStaleness } from '@/lib/domain/dependencies';
import { SprintBar, type CurrentSprintInfo } from './SprintBar';
import { api, ApiError } from '@/lib/apiClient';
import { useToast } from './Toast';
import {
  Assignee,
  CommitIcon,
  GitBranchIcon,
  PrChip,
  PriorityChip,
  STATE_COLOR,
  TypeChip,
} from './chips';
import { WorkItemDialog } from './WorkItemDialog';

interface DragState {
  itemId: number;
  from: WorkItemState;
}

export interface BoardItem extends WorkItem {
  readiness?: Readiness;
}

export function Board({
  initialItems,
  sprints,
  members,
  currentUser,
  autoBranch,
  currentSprint,
  now,
  staleness,
}: {
  initialItems: BoardItem[];
  sprints: Sprint[];
  members: TeamMember[];
  currentUser: string;
  autoBranch: boolean;
  currentSprint: CurrentSprintInfo;
  /** Server-supplied clock: reading it during render would be impure. */
  now: number;
  staleness: { maxAgeDays: number; maxBehind: number };
}) {
  const [items, setItems] = useState<BoardItem[]>(initialItems);
  const [current, setCurrent] = useState<CurrentSprintInfo>(currentSprint);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [hoverColumn, setHoverColumn] = useState<WorkItemState | null>(null);
  const [editing, setEditing] = useState<WorkItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [busyItem, setBusyItem] = useState<number | null>(null);
  const toast = useToast();

  // Everyone lands on the team's current sprint by default; changing this tab
  // is local browsing only.
  const [sprintFilter, setSprintFilter] = useState(
    currentSprint.sprintId !== null ? String(currentSprint.sprintId) : 'all',
  );
  const [waveFilter, setWaveFilter] = useState('all');
  const [assigneeFilter, setAssigneeFilter] = useState('all');
  const [search, setSearch] = useState('');

  const waves = useMemo(
    () => [...new Set(items.map((i) => i.wave).filter((w): w is string => Boolean(w)))].sort(),
    [items],
  );
  const filtersActive = assigneeFilter !== 'all' || search.trim() !== '' || waveFilter !== 'all';

  const visible = useMemo(
    () =>
      items.filter((i) => {
        if (sprintFilter === 'none' && i.sprintId !== null) return false;
        if (sprintFilter !== 'all' && sprintFilter !== 'none' && i.sprintId !== Number(sprintFilter)) return false;
        if (waveFilter !== 'all' && i.wave !== waveFilter) return false;
        if (assigneeFilter === 'mine' && i.assigneeLogin !== currentUser) return false;
        if (assigneeFilter === 'unassigned' && i.assigneeLogin !== null) return false;
        if (
          assigneeFilter !== 'all' &&
          assigneeFilter !== 'mine' &&
          assigneeFilter !== 'unassigned' &&
          i.assigneeLogin !== assigneeFilter
        ) return false;
        if (search.trim()) {
          const q = search.trim().toLowerCase();
          if (!`${i.id} ${i.title} ${i.description} ${i.tags.join(' ')}`.toLowerCase().includes(q)) {
            return false;
          }
        }
        return true;
      }),
    [items, sprintFilter, waveFilter, assigneeFilter, search, currentUser],
  );

  const byColumn = useMemo(() => {
    const map = new Map<WorkItemState, BoardItem[]>();
    for (const col of BOARD_COLUMNS) map.set(col, []);
    for (const item of visible) map.get(item.state)?.push(item);
    for (const list of map.values()) list.sort((a, b) => a.boardRank - b.boardRank || a.id - b.id);
    return map;
  }, [visible]);

  const upsert = useCallback((next: BoardItem) => {
    setItems((prev) => {
      const idx = prev.findIndex((p) => p.id === next.id);
      if (idx === -1) return [next, ...prev];
      const copy = [...prev];
      copy[idx] = next;
      return copy;
    });
  }, []);

  async function drop(toState: WorkItemState) {
    const active = drag;
    setDrag(null);
    setHoverColumn(null);
    if (!active) return;

    const item = items.find((i) => i.id === active.itemId);
    if (!item || item.state === toState) return;

    if (!canTransition(item.state, toState)) {
      toast.push({ tone: 'error', text: `#${item.id} can't move from ${item.state} to ${toState}.` });
      return;
    }

    const destination = (byColumn.get(toState) ?? []).map((i) => i.id);
    const orderedIds = [active.itemId, ...destination.filter((id) => id !== active.itemId)];

    // Optimistic, with a snapshot to roll back to if the server disagrees.
    const snapshot = items;
    setItems((prev) => prev.map((i) => (i.id === active.itemId ? { ...i, state: toState, boardRank: -1 } : i)));

    try {
      const { item: saved } = await api<{ item: BoardItem }>(`/items/${active.itemId}/move`, {
        method: 'POST',
        body: JSON.stringify({ toState, orderedIds }),
      });
      // The move response carries the item without readiness; keep the value we
      // already know so a blocked card does not briefly render as unblocked.
      upsert({ ...saved, readiness: items.find((i) => i.id === saved.id)?.readiness });

      // Moving into Active is the natural moment to offer a branch.
      if (autoBranch && toState === 'Active' && !saved.branchName) {
        toast.push({
          tone: 'info',
          text: `#${saved.id} is now Active. Create its branch?`,
          action: { label: 'Start work', onClick: () => void startWork(saved.id) },
        });
      }
    } catch (err) {
      setItems(snapshot);
      toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
    }
  }

  async function startWork(itemId: number) {
    setBusyItem(itemId);
    try {
      const res = await api<{
        item: BoardItem;
        branch: { status: string; name?: string; url?: string; message?: string };
        warnings: string[];
      }>(`/items/${itemId}/start-work`, { method: 'POST', body: JSON.stringify({}) });

      upsert(res.item);

      if (res.branch.status === 'created' || res.branch.status === 'existing') {
        toast.push({
          tone: 'ok',
          text:
            res.branch.status === 'created'
              ? `Branch ${res.branch.name} created.`
              : `Branch ${res.branch.name} already existed — linked it.`,
          action: res.branch.url ? { label: 'Open', href: res.branch.url } : undefined,
        });
      } else {
        // The state change still succeeded; only the branch failed.
        toast.push({ tone: 'error', text: res.branch.message ?? 'Could not create the branch.' });
      }
    } catch (err) {
      toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusyItem(null);
    }
  }

  function blockedOf(item: BoardItem): boolean {
    return item.readiness?.ready === false;
  }
  function blockedTitle(item: BoardItem): string {
    const blockers = item.readiness?.blockers ?? [];
    return blockers.length
      ? `Blocked by ${blockers.map((b) => `#${b.id} ${b.title}`).join(', ')}`
      : 'Blocked';
  }
  function staleOf(item: BoardItem): string | null {
    const behind = item.pullRequests.find((p) => p.behindBy !== null)?.behindBy ?? null;
    const s = evaluateStaleness(item.branchCreatedAt, behind, now, staleness);
    return s.stale ? s.reason : null;
  }

  return (
    <>
      {sprints.length > 0 ? (
        <SprintBar
          sprints={sprints}
          current={current}
          viewing={sprintFilter}
          onView={setSprintFilter}
          onCurrentChanged={setCurrent}
        />
      ) : null}

      <div className="page-head">
        <h1>Board</h1>
        <div className="toolbar">
          {waves.length > 0 ? (
            <select value={waveFilter} onChange={(e) => setWaveFilter(e.target.value)} aria-label="Filter by wave">
              <option value="all">All waves</option>
              {waves.map((w) => <option key={w} value={w}>{w}</option>)}
            </select>
          ) : null}
          <select value={assigneeFilter} onChange={(e) => setAssigneeFilter(e.target.value)} aria-label="Filter by assignee">
            <option value="all">Everyone</option>
            <option value="mine">My items</option>
            <option value="unassigned">Unassigned</option>
            {members.map((m) => <option key={m.login} value={m.login}>{m.login}</option>)}
          </select>
          <input type="search" value={search} placeholder="Search…" aria-label="Search work items"
                 onChange={(e) => setSearch(e.target.value)} />
          {filtersActive ? (
            <button className="btn btn-sm btn-ghost" onClick={() => { setSprintFilter('all'); setAssigneeFilter('all'); setSearch(''); }}>
              Clear
            </button>
          ) : null}
        </div>
        <span className="spacer" />
        <button className="btn btn-primary" onClick={() => setCreating(true)}>+ New item</button>
      </div>

      {sprints.length === 0 ? (
        <div className="panel" style={{ marginBottom: 'var(--s-4)' }}>
          <div className="empty">
            <div className="empty-title">No sprints yet</div>
            <p style={{ maxWidth: 560, margin: '0 auto var(--s-3)' }}>
              Create your first sprint on the <Link href="/sprints">Sprints</Link> page — or seed a
              whole semester of sprints, stories and their dependencies in one API call with{' '}
              <code>POST /api/v1/seed</code>.
            </p>
            <a className="btn btn-sm" href="/docs/api">Read the API guide</a>
          </div>
        </div>
      ) : null}

      <div className="board">
        {BOARD_COLUMNS.map((col) => {
          const list = byColumn.get(col) ?? [];
          const legal = drag ? canTransition(drag.from, col) : true;
          const isHover = hoverColumn === col && drag !== null && drag.from !== col;
          const points = list.reduce((sum, i) => sum + (i.storyPoints ?? 0), 0);

          return (
            <section
              key={col}
              className={`column${isHover && legal ? ' drop-target' : ''}${isHover && !legal ? ' drop-blocked' : ''}`}
              aria-label={`${col} column, ${list.length} items`}
              onDragOver={(e) => {
                if (!drag) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = legal ? 'move' : 'none';
                setHoverColumn(col);
              }}
              onDragLeave={() => setHoverColumn((c) => (c === col ? null : c))}
              onDrop={(e) => {
                e.preventDefault();
                if (legal) void drop(col);
                else {
                  toast.push({ tone: 'error', text: `Can't move from ${drag?.from} to ${col}.` });
                  setDrag(null);
                  setHoverColumn(null);
                }
              }}
            >
              <header className="column-head">
                <span className="column-dot" style={{ background: STATE_COLOR[col] }} aria-hidden="true" />
                {col}
                <span className="column-count">{list.length}{points > 0 ? ` · ${points}p` : ''}</span>
              </header>

              <div className="column-body">
                {isHover && legal ? <div className="drop-hint">Move to {col}</div> : null}

                {list.map((item) => (
                  <article
                    key={item.id}
                    className={`card${drag?.itemId === item.id ? ' dragging' : ''}${
                      blockedOf(item) ? ' is-blocked' : ''
                    }`}
                    draggable
                    tabIndex={0}
                    aria-label={`${item.itemType} ${item.id}: ${item.title}`}
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = 'move';
                      e.dataTransfer.setData('text/plain', String(item.id));
                      setDrag({ itemId: item.id, from: item.state });
                    }}
                    onDragEnd={() => { setDrag(null); setHoverColumn(null); }}
                    onDoubleClick={() => setEditing(item)}
                    onKeyDown={(e) => { if (e.key === 'Enter') setEditing(item); }}
                  >
                    <div className="card-top">
                      <TypeChip type={item.itemType} />
                      <Link href={`/items/${item.id}`} className="id-chip" onClick={(e) => e.stopPropagation()} draggable={false}>
                        #{item.id}
                      </Link>
                      <PriorityChip priority={item.priority} />
                      {item.storyPoints !== null ? <span className="points">{item.storyPoints}</span> : null}
                    </div>

                    {/* The title links to the full read view. Double-click still
                        opens the edit dialog, so the card keeps both affordances
                        instead of only exposing edit (AB#31). */}
                    <div className="card-title">
                      <Link
                        href={`/items/${item.id}`}
                        onClick={(e) => e.stopPropagation()}
                        draggable={false}
                      >
                        {item.title}
                      </Link>
                    </div>

                    {blockedOf(item) || item.wave || staleOf(item) ? (
                      <div className="card-foot" style={{ marginBottom: 'var(--s-2)' }}>
                        {blockedOf(item) ? (
                          <span className="badge badge-blocked" title={blockedTitle(item)}>
                            &#128274; Blocked
                          </span>
                        ) : null}
                        {item.readiness?.overridden ? (
                          <span className="badge badge-override" title="Started despite unmet dependencies">
                            override
                          </span>
                        ) : null}
                        {item.wave ? <span className="badge badge-wave">{item.wave}</span> : null}
                        {staleOf(item) ? (
                          <span className="badge badge-stale" title={staleOf(item)!}>
                            {staleOf(item)}
                          </span>
                        ) : null}
                      </div>
                    ) : null}

                    <div className="card-foot">
                      <Assignee login={item.assigneeLogin} avatarUrl={item.assigneeAvatarUrl} showName={false} />
                      {item.tags.slice(0, 2).map((t) => <span key={t} className="tag">{t}</span>)}
                      {item.tags.length > 2 ? <span className="tag">+{item.tags.length - 2}</span> : null}
                      <span className="spacer" />
                      {item.pullRequests.slice(0, 3).map((pr) => <PrChip key={pr.id} pr={pr} />)}
                    </div>

                    {(item.branchName || item.commitCount > 0 || (autoBranch && item.state === 'Active')) ? (
                      <div className="card-signals">
                        {item.branchName ? (
                          <span className="branch-chip" title={item.branchName}>
                            <GitBranchIcon /> {item.branchName}
                          </span>
                        ) : null}
                        {item.commitCount > 0 ? (
                          <span className="branch-chip" title={`${item.commitCount} commits`}>
                            <CommitIcon /> {item.commitCount}
                          </span>
                        ) : null}
                        {!item.branchName && autoBranch && item.state === 'Active' ? (
                          <button
                            className="btn btn-sm btn-ghost"
                            style={{ marginLeft: 'auto' }}
                            disabled={busyItem === item.id || blockedOf(item)}
                            title={blockedOf(item) ? blockedTitle(item) : 'Create the branch for this item'}
                            onClick={(e) => { e.stopPropagation(); void startWork(item.id); }}
                          >
                            {busyItem === item.id ? <span className="spinner" /> : <GitBranchIcon />}
                            Start work
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </article>
                ))}

                {list.length === 0 && !isHover ? (
                  <div className="empty-mini">
                    {filtersActive ? 'Nothing matches your filters' : col === 'New' ? 'Add the first item' : 'Nothing here'}
                  </div>
                ) : null}
              </div>
            </section>
          );
        })}
      </div>

      {creating ? (
        <WorkItemDialog sprints={sprints} members={members}
          onClose={() => setCreating(false)}
          onSaved={(item) => { upsert(item); setCreating(false); }} />
      ) : null}

      {editing ? (
        <WorkItemDialog item={editing} sprints={sprints} members={members}
          onClose={() => setEditing(null)}
          onSaved={(item) => { upsert(item); setEditing(null); }} />
      ) : null}
    </>
  );
}
