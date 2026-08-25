'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { Sprint } from '@/lib/domain/workitem';
import type { SprintStats } from '@/lib/domain/queries';
import { api } from '@/lib/apiClient';

interface Props {
  initialSprints: Sprint[];
  initialStats: SprintStats[];
  /** Today's date (YYYY-MM-DD), computed on the server. Reading the clock
   *  during render would be impure and could mismatch on hydration. */
  today: string;
}

const blank = { name: '', goal: '', startsOn: '', endsOn: '' };

export function Sprints({ initialSprints, initialStats, today }: Props) {
  const [sprints, setSprints] = useState(initialSprints);
  const [stats, setStats] = useState(initialStats);
  const [draft, setDraft] = useState(blank);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const statFor = (id: number) =>
    stats.find((s) => s.sprintId === id) ?? { sprintId: id, total: 0, done: 0, points: 0, donePoints: 0 };

  async function refresh() {
    try {
      const body = await api<{ sprints: Sprint[]; stats: SprintStats[] }>('/sprints');
      setSprints(body.sprints);
      setStats(body.stats);
    } catch {
      // Leave the current view in place; the next action will surface the error.
    }
  }

  async function submit() {
    if (!draft.name.trim() || !draft.startsOn || !draft.endsOn) {
      setError('Name, start date and end date are all required.');
      return;
    }
    if (draft.endsOn < draft.startsOn) {
      setError('The end date cannot be before the start date.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api(editingId ? `/sprints/${editingId}` : '/sprints', {
        method: editingId ? 'PATCH' : 'POST',
        body: JSON.stringify(draft),
      });
      setDraft(blank);
      setEditingId(null);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    if (!confirm('Delete this sprint? Its work items are kept and moved back to the backlog.')) return;
    setBusy(true);
    try {
      await api(`/sprints/${id}`, { method: 'DELETE' });
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Sprints</h1>
      </div>

      <div className="detail-grid">
        <div className="sprint-grid">
          {sprints.length === 0 ? (
            <div className="panel empty">No sprints yet. Create one to start planning.</div>
          ) : null}

          {sprints.map((s) => {
            const st = statFor(s.id);
            const pct = st.points > 0 ? Math.round((st.donePoints / st.points) * 100) : 0;
            const days = sprintDays(s.startsOn, s.endsOn);
            const phase = sprintPhase(s, today);
            const isCurrent = phase === 'in progress';
            return (
              <div key={s.id} className={`sprint-card${isCurrent ? ' current' : ''}`}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <strong>{s.name}</strong>
                  {isCurrent ? (
                    <span className="tag" style={{ color: 'var(--accent)', borderColor: 'var(--accent)' }}>
                      current
                    </span>
                  ) : null}
                  <span className="spacer" />
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={() => {
                      setEditingId(s.id);
                      setDraft({ name: s.name, goal: s.goal, startsOn: s.startsOn, endsOn: s.endsOn });
                    }}
                  >
                    Edit
                  </button>
                  <button className="btn btn-sm btn-ghost btn-danger" onClick={() => void remove(s.id)} disabled={busy}>
                    Delete
                  </button>
                </div>

                <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                  {s.startsOn} → {s.endsOn} · {days} day{days === 1 ? '' : 's'} · {phase}
                </div>

                {s.goal ? <p style={{ margin: '8px 0 0', fontSize: 13 }}>{s.goal}</p> : null}

                <div className="meter" title={`${pct}% of points complete`}>
                  <div className="meter-fill" style={{ width: `${pct}%` }} />
                </div>

                <div className="stat-row">
                  <span><b>{st.total}</b>items</span>
                  <span><b>{st.done}</b>done</span>
                  <span><b>{st.points}</b>points</span>
                  <span><b>{st.points - st.donePoints}</b>remaining</span>
                </div>

                <div style={{ marginTop: 10 }}>
                  <Link className="btn btn-sm" href={`/backlog?sprint=${s.id}`}>View items</Link>
                </div>
              </div>
            );
          })}
        </div>

        <div className="panel">
          <div className="section">
            <h3>{editingId ? 'Edit sprint' : 'New sprint'}</h3>

            {error ? <div className="alert alert-error" role="alert">{error}</div> : null}

            <div className="field">
              <label htmlFor="sp-name">Name</label>
              <input id="sp-name" type="text" value={draft.name} placeholder="Sprint 1"
                     onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="sp-start">Starts</label>
              <input id="sp-start" type="date" value={draft.startsOn}
                     onChange={(e) => setDraft({ ...draft, startsOn: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="sp-end">Ends</label>
              <input id="sp-end" type="date" value={draft.endsOn}
                     onChange={(e) => setDraft({ ...draft, endsOn: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="sp-goal">Goal</label>
              <textarea id="sp-goal" style={{ minHeight: 64 }} value={draft.goal}
                        placeholder="What should be true at the end of this sprint?"
                        onChange={(e) => setDraft({ ...draft, goal: e.target.value })} />
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-primary" onClick={() => void submit()} disabled={busy}>
                {busy ? 'Saving…' : editingId ? 'Save' : 'Create sprint'}
              </button>
              {editingId ? (
                <button className="btn" onClick={() => { setEditingId(null); setDraft(blank); setError(null); }}>
                  Cancel
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function sprintDays(start: string, end: string): number {
  const a = Date.parse(`${start}T00:00:00Z`);
  const b = Date.parse(`${end}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return 0;
  return Math.round((b - a) / 86_400_000) + 1;
}

function sprintPhase(s: Sprint, today: string): string {
  if (today < s.startsOn) return 'upcoming';
  if (today > s.endsOn) return 'finished';
  return 'in progress';
}
