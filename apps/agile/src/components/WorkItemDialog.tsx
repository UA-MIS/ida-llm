'use client';

import { useEffect, useRef, useState } from 'react';
import {
  PRIORITIES,
  WORK_ITEM_TYPES,
  allowedTransitions,
  type Sprint,
  type WorkItem,
  type WorkItemState,
  type WorkItemType,
} from '@/lib/domain/workitem';
import type { TeamMember } from '@/lib/github/client';
import { api } from '@/lib/apiClient';

export interface WorkItemDraft {
  title: string;
  description: string;
  itemType: WorkItemType;
  state: WorkItemState;
  assigneeLogin: string | null;
  assigneeAvatarUrl: string | null;
  storyPoints: number | null;
  priority: number;
  sprintId: number | null;
  tags: string[];
}

function toDraft(item?: WorkItem | null): WorkItemDraft {
  return {
    title: item?.title ?? '',
    description: item?.description ?? '',
    itemType: item?.itemType ?? 'Story',
    state: item?.state ?? 'New',
    assigneeLogin: item?.assigneeLogin ?? null,
    assigneeAvatarUrl: item?.assigneeAvatarUrl ?? null,
    storyPoints: item?.storyPoints ?? null,
    priority: item?.priority ?? 2,
    sprintId: item?.sprintId ?? null,
    tags: item?.tags ?? [],
  };
}

/**
 * Create/edit form. When `item` is given the state dropdown is restricted to
 * legal transitions, so the UI cannot ask the server for a move it will reject.
 */
export function WorkItemDialog({
  item,
  sprints,
  members,
  onClose,
  onSaved,
}: {
  item?: WorkItem | null;
  sprints: Sprint[];
  members: TeamMember[];
  onClose: () => void;
  onSaved: (item: WorkItem) => void;
}) {
  const [draft, setDraft] = useState<WorkItemDraft>(() => toDraft(item));
  const [tagInput, setTagInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const stateOptions: WorkItemState[] = item
    ? [item.state, ...allowedTransitions(item.state)]
    : ['New', 'Active'];

  function set<K extends keyof WorkItemDraft>(key: K, value: WorkItemDraft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  function addTag() {
    const t = tagInput.trim();
    if (!t) return;
    if (!draft.tags.includes(t)) set('tags', [...draft.tags, t]);
    setTagInput('');
  }

  async function save() {
    if (!draft.title.trim()) {
      setError('A title is required.');
      titleRef.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = await api<{ item: WorkItem }>(item ? `/items/${item.id}` : '/items', {
        method: item ? 'PATCH' : 'POST',
        body: JSON.stringify(draft),
      });
      if (body.item) onSaved(body.item);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={item ? 'Edit work item' : 'New work item'}>
        <div className="dialog-head">
          <h2>{item ? `Edit #${item.id}` : 'New work item'}</h2>
          <span className="spacer" />
          <button className="btn btn-sm btn-ghost" onClick={onClose} aria-label="Close">
            &#10005;
          </button>
        </div>

        <div className="dialog-body">
          {error ? (
            <div className="alert alert-error" role="alert">
              {error}
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="wi-title">Title</label>
            <input
              id="wi-title"
              ref={titleRef}
              type="text"
              value={draft.title}
              maxLength={300}
              placeholder="What needs to happen?"
              onChange={(e) => set('title', e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void save();
              }}
            />
          </div>

          <div className="row">
            <div className="field">
              <label htmlFor="wi-type">Type</label>
              <select id="wi-type" value={draft.itemType} onChange={(e) => set('itemType', e.target.value as WorkItemType)}>
                {WORK_ITEM_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="wi-state">State</label>
              <select id="wi-state" value={draft.state} onChange={(e) => set('state', e.target.value as WorkItemState)}>
                {stateOptions.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="wi-pri">Priority</label>
              <select id="wi-pri" value={draft.priority} onChange={(e) => set('priority', Number(e.target.value))}>
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>P{p}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="row">
            <div className="field">
              <label htmlFor="wi-assignee">Assignee</label>
              <select
                id="wi-assignee"
                value={draft.assigneeLogin ?? ''}
                onChange={(e) => {
                  const login = e.target.value || null;
                  const m = members.find((x) => x.login === login);
                  setDraft((d) => ({ ...d, assigneeLogin: login, assigneeAvatarUrl: m?.avatarUrl ?? null }));
                }}
              >
                <option value="">Unassigned</option>
                {members.map((m) => (
                  <option key={m.login} value={m.login}>{m.login}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="wi-points">Story points</label>
              <input
                id="wi-points"
                type="number"
                min={0}
                max={1000}
                value={draft.storyPoints ?? ''}
                placeholder="—"
                onChange={(e) => set('storyPoints', e.target.value === '' ? null : Number(e.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="wi-sprint">Sprint</label>
              <select
                id="wi-sprint"
                value={draft.sprintId ?? ''}
                onChange={(e) => set('sprintId', e.target.value === '' ? null : Number(e.target.value))}
              >
                <option value="">Backlog (no sprint)</option>
                {sprints.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="field">
            <label htmlFor="wi-desc">Description (markdown)</label>
            <textarea
              id="wi-desc"
              value={draft.description}
              maxLength={20000}
              placeholder="Context, acceptance criteria, links…"
              onChange={(e) => set('description', e.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="wi-tags">Tags</label>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
              <input
                id="wi-tags"
                type="text"
                value={tagInput}
                placeholder="Add a tag and press Enter"
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addTag();
                  }
                }}
              />
              <button type="button" className="btn btn-sm" onClick={addTag}>Add</button>
            </div>
            <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
              {draft.tags.map((t) => (
                <button
                  key={t}
                  type="button"
                  className="tag"
                  style={{ cursor: 'pointer' }}
                  title="Remove tag"
                  onClick={() => set('tags', draft.tags.filter((x) => x !== t))}
                >
                  {t} &#10005;
                </button>
              ))}
              {draft.tags.length === 0 ? <span className="muted" style={{ fontSize: 12 }}>No tags</span> : null}
            </div>
          </div>
        </div>

        <div className="dialog-foot">
          <button className="btn" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={() => void save()} disabled={saving}>
            {saving ? 'Saving…' : item ? 'Save changes' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}
