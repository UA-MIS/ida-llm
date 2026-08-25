'use client';

import { useState } from 'react';
import Link from 'next/link';
import { api, ApiError } from '@/lib/apiClient';
import { useToast } from './Toast';
import type { BoardPage, PageRevision } from '@/lib/domain/pages';
import type { BoardSummary } from '@/lib/domain/summary';

/**
 * The homepage: a living README.
 *
 * Two halves, deliberately different in kind — a narrative the team writes and
 * edits, and a state strip generated from the board that nobody maintains.
 */
export function Home({
  page: initialPage,
  html: initialHtml,
  summary,
  boardTitle,
}: {
  page: BoardPage;
  html: string;
  summary: BoardSummary;
  boardTitle: string;
}) {
  const [page, setPage] = useState(initialPage);
  const [html, setHtml] = useState(initialHtml);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(page.body);
  const [busy, setBusy] = useState(false);
  const [revisions, setRevisions] = useState<PageRevision[] | null>(null);
  const toast = useToast();

  const s = summary;
  const sprint = s.currentSprint.sprint;
  const pct = s.points.total > 0 ? Math.round((s.points.done / s.points.total) * 100) : 0;

  async function save() {
    setBusy(true);
    try {
      const res = await api<{ page: BoardPage }>('/pages/home', {
        method: 'PUT',
        body: JSON.stringify({ body: draft }),
      });
      setPage(res.page);
      // The markdown is rendered (and sanitised) on the server, so re-fetch the
      // rendered HTML rather than rendering untrusted markdown in the browser.
      const rendered = await fetch('/api/v1/pages/home/rendered').then((r) =>
        r.ok ? r.json() : null,
      );
      setHtml(rendered?.html ?? html);
      setEditing(false);
      setRevisions(null);
      toast.push({ tone: 'ok', text: 'Homepage updated.' });
    } catch (err) {
      toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  async function loadRevisions() {
    if (revisions) return setRevisions(null);
    try {
      const res = await api<{ revisions: PageRevision[] }>('/pages/home/revisions');
      setRevisions(res.revisions);
    } catch (err) {
      toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
    }
  }

  return (
    <>
      <div className="home-hero">
        <h1>{boardTitle}</h1>
        <span className="spacer" />
        <Link className="btn btn-primary" href="/board">Open the board →</Link>
        <Link className="btn" href="/ready">Ready ({s.readyCount})</Link>
      </div>

      {page.isTemplate && !editing ? (
        <div className="template-banner">
          <span style={{ flex: 1 }}>
            This is starter text. Replace it with what your project actually is — it&rsquo;s the
            first thing anyone sees.
          </span>
          <button className="btn btn-sm btn-primary" onClick={() => { setDraft(page.body); setEditing(true); }}>
            Edit this page
          </button>
        </div>
      ) : null}

      <div className="home-grid">
        <div className="panel">
          <div className="section">
            <h3>
              About this project
              <span className="spacer" />
              {!editing ? (
                <>
                  <button className="btn btn-sm btn-ghost" onClick={() => void loadRevisions()}>
                    {revisions ? 'Hide history' : 'History'}
                  </button>
                  <button className="btn btn-sm" onClick={() => { setDraft(page.body); setEditing(true); }}>
                    Edit
                  </button>
                </>
              ) : null}
            </h3>

            {editing ? (
              <>
                <div className="editor-toolbar">
                  <button className="btn btn-sm btn-primary" onClick={() => void save()} disabled={busy}>
                    {busy ? <span className="spinner" /> : null} Save
                  </button>
                  <button className="btn btn-sm" onClick={() => setEditing(false)} disabled={busy}>
                    Cancel
                  </button>
                  <span className="muted" style={{ fontSize: 12 }}>
                    Markdown. Saving keeps the previous version in history.
                  </span>
                </div>
                <textarea
                  className="md-editor"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  aria-label="Homepage markdown"
                />
              </>
            ) : (
              <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
            )}

            {!editing && page.updatedAt ? (
              <p className="muted" style={{ fontSize: 12, marginBottom: 0, marginTop: 'var(--s-4)' }}>
                Last edited by <strong>{page.updatedBy || 'unknown'}</strong> on{' '}
                {new Date(page.updatedAt).toLocaleDateString()}.
              </p>
            ) : null}

            {revisions ? (
              <div style={{ marginTop: 'var(--s-4)' }}>
                <h3>Edit history</h3>
                {revisions.length === 0 ? (
                  <p className="muted">No earlier versions yet.</p>
                ) : (
                  revisions.map((r) => (
                    <div key={r.id} className="rev-item">
                      <span style={{ flex: 1 }}>
                        Replaced text from <strong>{r.editedBy || 'unknown'}</strong>
                        <span className="muted"> ({r.body.length.toLocaleString()} chars)</span>
                      </span>
                      <span className="muted nowrap">{new Date(r.editedAt).toLocaleString()}</span>
                    </div>
                  ))
                )}
              </div>
            ) : null}
          </div>
        </div>

        <div className="stack">
          <div className="panel">
            <div className="section">
              <h3>Where things stand</h3>

              {sprint ? (
                <div className="sprint-hero">
                  <h3 style={{ margin: 0 }}>Current sprint</h3>
                  <div className="name">{sprint.name}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {sprint.startsOn} → {sprint.endsOn}
                    {s.currentSprint.daysRemaining !== null
                      ? ` · ${s.currentSprint.daysRemaining} day${s.currentSprint.daysRemaining === 1 ? '' : 's'} left`
                      : ''}
                  </div>
                  {sprint.goal ? <p style={{ margin: '8px 0 0', fontSize: 13 }}>{sprint.goal}</p> : null}
                  <div className="meter" title={`${pct}% of points complete`}>
                    <div className="meter-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {s.points.done} of {s.points.total} points done
                  </div>
                </div>
              ) : (
                <div className="alert">
                  No current sprint set.{' '}
                  <Link href="/sprints">Create one</Link> to give the team a default view.
                </div>
              )}

              <div className="stat-strip">
                <div className="stat"><b>{s.states.New}</b><span>New</span></div>
                <div className="stat stat-accent"><b>{s.states.Active}</b><span>Active</span></div>
                <div className="stat"><b>{s.states.Resolved}</b><span>Resolved</span></div>
                <div className="stat stat-ok"><b>{s.states.Closed}</b><span>Closed</span></div>
              </div>

              <div className="stat-strip cols-3" style={{ marginTop: 'var(--s-2)' }}>
                <div className="stat stat-ok"><b>{s.readyCount}</b><span>ready to pick up</span></div>
                <div className="stat stat-danger"><b>{s.blockedCount}</b><span>blocked</span></div>
                <div className="stat"><b>{s.mergedPrCount}</b><span>PRs merged</span></div>
              </div>
            </div>
          </div>

          {s.recentMergedPrs.length > 0 ? (
            <div className="panel">
              <div className="section">
                <h3>Recently merged</h3>
                {s.recentMergedPrs.map((pr) => (
                  <div key={`${pr.repoFullName}#${pr.prNumber}`} className="commit-row">
                    <a className="commit-sha" href={pr.url} target="_blank" rel="noopener noreferrer">
                      #{pr.prNumber}
                    </a>
                    <span className="commit-msg" title={pr.title}>{pr.title}</span>
                    <Link href={`/items/${pr.itemId}`} className="muted nowrap" style={{ fontSize: 11 }}>
                      &rarr; #{pr.itemId}
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {s.recentlyResolved.length > 0 ? (
            <div className="panel">
              <div className="section">
                <h3>Recently finished</h3>
                {s.recentlyResolved.map((r) => (
                  <div key={r.id} className="commit-row">
                    <Link href={`/items/${r.id}`} className="commit-sha">#{r.id}</Link>
                    <span className="commit-msg" title={r.title}>{r.title}</span>
                    <span className="muted nowrap" style={{ fontSize: 11 }}>{r.state}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
