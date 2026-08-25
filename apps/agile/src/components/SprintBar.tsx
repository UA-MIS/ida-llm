'use client';

import { useState } from 'react';
import type { Sprint } from '@/lib/domain/workitem';
import { api, ApiError } from '@/lib/apiClient';
import { useToast } from './Toast';

export interface CurrentSprintInfo {
  sprintId: number | null;
  setBy: string | null;
  setAt: string | null;
}

/**
 * Sprint selector.
 *
 * Two distinct actions, deliberately not the same click:
 *  - **Selecting a tab** is local browsing. It changes only your view.
 *  - **"Set as current"** is SHARED: it changes where every visitor lands by
 *    default. It is a separate, explicitly-labelled control so a casual click
 *    cannot reassign the team's default.
 */
export function SprintBar({
  sprints,
  current,
  viewing,
  onView,
  onCurrentChanged,
}: {
  sprints: Sprint[];
  current: CurrentSprintInfo;
  viewing: string;
  onView: (value: string) => void;
  onCurrentChanged: (next: CurrentSprintInfo) => void;
}) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const viewingSprintId = /^\d+$/.test(viewing) ? Number(viewing) : null;
  const viewingSprint = sprints.find((s) => s.id === viewingSprintId) ?? null;
  const isViewingCurrent = viewingSprintId !== null && viewingSprintId === current.sprintId;

  async function setCurrent(sprintId: number) {
    const sprint = sprints.find((s) => s.id === sprintId);
    if (
      !confirm(
        `Make "${sprint?.name}" the current sprint for the whole team?\n\n` +
          'Everyone visiting the board will land on this sprint by default.',
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      const next = await api<CurrentSprintInfo>('/sprints/current', {
        method: 'PUT',
        body: JSON.stringify({ sprintId }),
      });
      onCurrentChanged(next);
      toast.push({ tone: 'ok', text: `"${sprint?.name}" is now the team's current sprint.` });
    } catch (err) {
      toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="sprint-bar" role="tablist" aria-label="Sprints">
        <button
          role="tab"
          aria-selected={viewing === 'all'}
          className="sprint-tab"
          onClick={() => onView('all')}
        >
          All work
          <span className="sprint-meta">every sprint</span>
        </button>

        {sprints.map((s) => (
          <button
            key={s.id}
            role="tab"
            aria-selected={viewing === String(s.id)}
            className={`sprint-tab${s.id === current.sprintId ? ' is-current' : ''}`}
            onClick={() => onView(String(s.id))}
            title={s.goal || undefined}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {s.name}
              {s.id === current.sprintId ? <span className="current-pill">current</span> : null}
            </span>
            <span className="sprint-meta">
              {s.startsOn} → {s.endsOn}
              {typeof s.itemCount === 'number' ? ` · ${s.itemCount} item${s.itemCount === 1 ? '' : 's'}` : ''}
            </span>
          </button>
        ))}

        <button
          role="tab"
          aria-selected={viewing === 'none'}
          className="sprint-tab"
          onClick={() => onView('none')}
        >
          Backlog
          <span className="sprint-meta">no sprint</span>
        </button>
      </div>

      {viewingSprint && !isViewingCurrent ? (
        <div className="alert alert-warn" style={{ marginBottom: 'var(--s-4)' }}>
          <span style={{ flex: 1 }}>
            You are browsing <strong>{viewingSprint.name}</strong>. The team&rsquo;s current sprint
            is{' '}
            <strong>
              {sprints.find((s) => s.id === current.sprintId)?.name ?? 'not set'}
            </strong>
            .
          </span>
          <button className="btn btn-sm" disabled={busy} onClick={() => void setCurrent(viewingSprint.id)}>
            Set as current sprint
          </button>
        </div>
      ) : null}

      {isViewingCurrent && current.setBy ? (
        <p className="muted" style={{ fontSize: 12, marginTop: -8, marginBottom: 'var(--s-3)' }}>
          Current sprint set by <strong>{current.setBy}</strong>
          {current.setAt ? ` on ${new Date(current.setAt).toLocaleDateString()}` : ''}.
        </p>
      ) : null}
    </div>
  );
}
