'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import type { Sprint, WorkItem } from '@/lib/domain/workitem';
import type { Readiness } from '@/lib/domain/dependencies';
import { api, ApiError } from '@/lib/apiClient';
import { useToast } from './Toast';
import { PriorityChip, TypeChip } from './chips';

export interface ReadyItem extends WorkItem {
  readiness?: Readiness;
}

export interface BlockedSummary {
  id: number;
  title: string;
  blockers: Array<{ id: number; title: string; state: string }>;
}

/**
 * The self-serve pickup queue: unassigned work whose dependencies are all
 * satisfied. This is the screen someone opens when they finish a task and want
 * the next legitimate thing to take.
 */
export function Ready({
  initialReady,
  blocked,
  sprints,
  currentUser,
}: {
  initialReady: ReadyItem[];
  blocked: BlockedSummary[];
  sprints: Sprint[];
  currentUser: string;
}) {
  const [items, setItems] = useState(initialReady);
  const [wave, setWave] = useState('all');
  const [busy, setBusy] = useState<number | null>(null);
  const toast = useToast();

  const waves = useMemo(
    () => [...new Set(items.map((i) => i.wave).filter((w): w is string => Boolean(w)))].sort(),
    [items],
  );
  const visible = items.filter((i) => wave === 'all' || i.wave === wave);
  const sprintName = (id: number | null) => sprints.find((s) => s.id === id)?.name ?? 'Backlog';

  async function claim(item: ReadyItem) {
    setBusy(item.id);
    try {
      await api(`/items/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ assigneeLogin: currentUser }),
      });
      setItems((prev) => prev.filter((i) => i.id !== item.id));
      toast.push({
        tone: 'ok',
        text: `#${item.id} assigned to you.`,
        action: { label: 'Open', href: `/items/${item.id}` },
      });
    } catch (err) {
      toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Ready to pick up</h1>
        {waves.length > 0 ? (
          <select value={wave} onChange={(e) => setWave(e.target.value)} aria-label="Filter by wave"
                  style={{ width: 'auto' }}>
            <option value="all">All waves</option>
            {waves.map((w) => <option key={w} value={w}>{w}</option>)}
          </select>
        ) : null}
        <span className="spacer" />
        <span className="muted">
          {visible.length} unblocked · {blocked.length} blocked
        </span>
      </div>

      {visible.length === 0 ? (
        <div className="panel">
          <div className="empty">
            <div className="empty-title">Nothing is waiting to be picked up</div>
            {blocked.length > 0
              ? 'Every unassigned item is currently blocked by something unfinished — see below.'
              : 'All unassigned work has been taken, or the board is empty.'}
          </div>
        </div>
      ) : (
        <div className="ready-grid">
          {visible.map((item) => (
            <div key={item.id} className="sprint-card">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <TypeChip type={item.itemType} />
                <Link href={`/items/${item.id}`} className="id-chip">#{item.id}</Link>
                <PriorityChip priority={item.priority} />
                {item.storyPoints !== null ? <span className="points">{item.storyPoints}</span> : null}
              </div>

              <Link href={`/items/${item.id}`} style={{ fontWeight: 600, textDecoration: 'none' }}>
                {item.title}
              </Link>

              <div className="card-foot" style={{ marginTop: 8 }}>
                <span className="badge badge-ready">ready</span>
                {item.wave ? <span className="badge badge-wave">{item.wave}</span> : null}
                <span className="tag">{sprintName(item.sprintId)}</span>
              </div>

              <button
                className="btn btn-primary btn-block"
                style={{ marginTop: 12 }}
                disabled={busy === item.id}
                onClick={() => void claim(item)}
              >
                {busy === item.id ? <span className="spinner" /> : null} Assign to me
              </button>
            </div>
          ))}
        </div>
      )}

      {blocked.length > 0 ? (
        <div className="panel" style={{ marginTop: 'var(--s-5)' }}>
          <div className="section">
            <h3>Blocked ({blocked.length})</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              These are unassigned but cannot be started yet. They appear above as soon as their
              last blocker is resolved.
            </p>
            {blocked.map((b) => (
              <div key={b.id} className="activity-item">
                <span style={{ flex: 1 }}>
                  <Link href={`/items/${b.id}`} style={{ fontWeight: 550 }}>
                    #{b.id} {b.title}
                  </Link>
                  <div className="blocker-list">
                    {b.blockers.map((x) => (
                      <Link key={x.id} href={`/items/${x.id}`}>
                        &#128274; blocked by #{x.id} {x.title} ({x.state})
                      </Link>
                    ))}
                  </div>
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}
