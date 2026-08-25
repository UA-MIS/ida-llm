'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  typeCreatesBranch,
  type ActivityEntry,
  type Attachment,
  type Comment,
  type Sprint,
  type WorkItem,
} from '@/lib/domain/workitem';
import type { TeamMember, AnnotatedPullRequest } from '@/lib/github/client';
import { api, ApiError } from '@/lib/apiClient';
import { useToast } from './Toast';
import { Assignee, CommitIcon, GitBranchIcon, PriorityChip, StateBadge, TypeChip } from './chips';
import { WorkItemDialog } from './WorkItemDialog';

export function ItemDetail({
  initialItem,
  descriptionHtml,
  comments: initialComments,
  activity,
  attachments: initialAttachments,
  sprints,
  members,
  openPrs,
  currentUser,
  autoBranch,
  attachmentsEnabled,
}: {
  initialItem: WorkItem;
  descriptionHtml: string;
  comments: Comment[];
  activity: ActivityEntry[];
  attachments: Attachment[];
  sprints: Sprint[];
  members: TeamMember[];
  openPrs: AnnotatedPullRequest[];
  currentUser: { login: string; avatarUrl: string };
  autoBranch: boolean;
  attachmentsEnabled: boolean;
}) {
  const router = useRouter();
  const toast = useToast();
  const [item, setItem] = useState(initialItem);
  const [comments, setComments] = useState(initialComments);
  const [attachments, setAttachments] = useState(initialAttachments);
  const [editing, setEditing] = useState(false);
  const [prRef, setPrRef] = useState('');
  const [commentBody, setCommentBody] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  /**
   * Story/Bug work ends in a diff; Spike/Task work does not (AB#25).
   *
   * `willBranch` decides whether the button *implies git* — it gets the branch
   * icon and stays available while an in-flight item still needs a ref.
   * `canStart` is the broader question, and covers the case branching alone
   * misses: a New Story on a board with AUTO_BRANCH=false is still startable,
   * it just starts without a branch, exactly as `{"branch": false}` does.
   */
  const willBranch = typeCreatesBranch(item.itemType) && autoBranch && !item.branchName;
  const canStart = willBranch || item.state === 'New';

  const sprintName = sprints.find((s) => s.id === item.sprintId)?.name ?? null;
  const linked = new Set(item.pullRequests.map((p) => `${p.repoFullName}#${p.prNumber}`));
  const suggestions = openPrs.filter((pr) => !linked.has(`${pr.repoFullName}#${pr.number}`));

  function fail(err: unknown) {
    toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
  }

  async function reload() {
    try {
      const res = await api<{ item: WorkItem; comments: Comment[]; attachments: Attachment[] }>(`/items/${item.id}`);
      setItem(res.item);
      setComments(res.comments);
      setAttachments(res.attachments);
    } catch (err) {
      fail(err);
    }
  }

  async function startWork() {
    setBusy('branch');
    try {
      const res = await api<{
        item: WorkItem;
        branch: { status: string; name?: string; url?: string; checkout?: string; message?: string };
      }>(`/items/${item.id}/start-work`, { method: 'POST', body: JSON.stringify({}) });
      setItem(res.item);
      if (res.branch.status === 'created' || res.branch.status === 'existing') {
        toast.push({
          tone: 'ok',
          text: res.branch.status === 'created' ? `Branch ${res.branch.name} created.` : `Linked existing branch ${res.branch.name}.`,
          action: res.branch.url ? { label: 'Open', href: res.branch.url } : undefined,
        });
      } else if (res.branch.status === 'skipped') {
        // The designed outcome for a Spike or a Task: the item really is
        // started. Reporting that as a branch failure is what made the old
        // flow feel like it owed you a branch.
        toast.push({ tone: 'ok', text: `#${item.id} is Active. ${res.branch.message ?? ''}`.trim() });
      } else {
        toast.push({ tone: 'error', text: res.branch.message ?? 'Could not create the branch.' });
      }
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function linkPr(reference: string) {
    if (!reference.trim()) return;
    setBusy('pr');
    try {
      await api(`/items/${item.id}/links`, { method: 'POST', body: JSON.stringify({ reference }) });
      setPrRef('');
      await reload();
      toast.push({ tone: 'ok', text: 'Pull request linked. A backlink comment was posted on the PR.' });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function unlinkPr(linkId: number) {
    setBusy('pr');
    try {
      await api(`/items/${item.id}/links?linkId=${linkId}`, { method: 'DELETE' });
      await reload();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function postComment() {
    const body = commentBody.trim();
    if (!body) return;
    setBusy('comment');
    try {
      const res = await api<{ comment: Comment }>(`/items/${item.id}/comments`, {
        method: 'POST',
        body: JSON.stringify({ body }),
      });
      setComments((c) => [...c, res.comment]);
      setCommentBody('');
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function upload(file: File) {
    setBusy('upload');
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api<{ attachment: Attachment }>(`/items/${item.id}/attachments`, {
        method: 'POST',
        body: form,
      });
      setAttachments((a) => [...a, res.attachment]);
      toast.push({ tone: 'ok', text: `${res.attachment.filename} attached.` });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (!confirm(`Delete work item #${item.id}? This cannot be undone.`)) return;
    try {
      await api(`/items/${item.id}`, { method: 'DELETE' });
      router.push('/board');
    } catch (err) {
      fail(err);
    }
  }

  function copy(text: string, label: string) {
    void navigator.clipboard?.writeText(text).then(
      () => toast.push({ tone: 'ok', text: `${label} copied.` }),
      () => toast.push({ tone: 'error', text: 'Could not copy to the clipboard.' }),
    );
  }

  return (
    <>
      <div className="page-head">
        <TypeChip type={item.itemType} />
        <h1 style={{ margin: 0 }}>
          <span className="muted mono" style={{ fontSize: 15 }}>#{item.id}</span> {item.title}
        </h1>
        <StateBadge state={item.state} />
        <span className="spacer" />
        {/*
          * "Start work" must not imply a branch for an item that will not get
          * one — a Spike, a Task, or any type on a board with branching turned
          * off. Those still start (Active + claimed); they just create nothing
          * in git, so they render without the branch icon (AB#25).
          */}
        {canStart ? (
          <button
            className="btn"
            onClick={() => void startWork()}
            disabled={busy === 'branch'}
            title={
              willBranch
                ? 'Activate and claim this item, and create its branch.'
                : `Activate and claim this ${item.itemType}. No branch is created.`
            }
          >
            {busy === 'branch' ? <span className="spinner" /> : willBranch ? <GitBranchIcon /> : null}{' '}
            Start work
          </button>
        ) : null}
        <button className="btn" onClick={() => setEditing(true)}>Edit</button>
        <button className="btn btn-danger" onClick={() => void remove()}>Delete</button>
      </div>

      <div className="detail-grid">
        <div className="stack">
          <div className="panel">
            <div className="section">
              <h3>Description</h3>
              {descriptionHtml ? (
                <div className="markdown" dangerouslySetInnerHTML={{ __html: descriptionHtml }} />
              ) : (
                <p className="muted">No description yet. <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>Add one</button></p>
              )}
            </div>
          </div>

          {item.branchName ? (
            <div className="panel">
              <div className="section">
                <h3><GitBranchIcon /> Branch</h3>
                <div className="copyable" style={{ marginBottom: 8 }}>
                  <code>{item.branchName}</code>
                  <button className="btn btn-sm btn-ghost" onClick={() => copy(item.branchName!, 'Branch name')}>Copy</button>
                  {item.branchUrl ? (
                    <a className="btn btn-sm btn-ghost" href={item.branchUrl} target="_blank" rel="noopener noreferrer">Open</a>
                  ) : null}
                </div>
                <div className="copyable">
                  <code>git fetch origin &amp;&amp; git switch {item.branchName}</code>
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={() => copy(`git fetch origin && git switch ${item.branchName}`, 'Command')}
                  >
                    Copy
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          <div className="panel">
            <div className="section">
              <h3>Pull requests</h3>

              {item.pullRequests.length === 0 ? (
                <p className="muted">No pull requests linked yet.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                  {item.pullRequests.map((pr) => (
                    <div key={pr.id} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span
                        aria-hidden="true"
                        title={pr.merged ? 'Merged' : pr.prState}
                        style={{ color: pr.merged ? 'var(--type-spike)' : pr.prState === 'closed' ? 'var(--danger)' : 'var(--ok)' }}
                      >
                        &#9679;
                      </span>
                      <a href={pr.url} target="_blank" rel="noopener noreferrer" style={{ fontWeight: 550 }}>
                        {pr.title || `${pr.repoFullName}#${pr.prNumber}`}
                      </a>
                      <span className="mono muted" style={{ fontSize: 12 }}>{pr.repoFullName}#{pr.prNumber}</span>
                      {pr.checksState ? <span className="tag" title="Latest commit status">checks: {pr.checksState}</span> : null}
                      {pr.behindBy ? <span className="tag" title="Commits behind the default branch">{pr.behindBy} behind</span> : null}
                      {pr.prState === 'closed' && !pr.merged ? <span className="tag" style={{ color: 'var(--danger)' }}>closed unmerged</span> : null}
                      <span className="spacer" />
                      <button className="btn btn-sm btn-ghost" onClick={() => void unlinkPr(pr.id)} disabled={busy === 'pr'}>Unlink</button>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ display: 'flex', gap: 6 }}>
                <input type="text" value={prRef} placeholder="Paste a PR URL, owner/repo#123, or 123"
                       onChange={(e) => setPrRef(e.target.value)}
                       onKeyDown={(e) => { if (e.key === 'Enter') void linkPr(prRef); }} />
                <button className="btn" onClick={() => void linkPr(prRef)} disabled={busy === 'pr' || !prRef.trim()}>Link</button>
              </div>

              {suggestions.length > 0 ? (
                <div style={{ marginTop: 12 }}>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Open pull requests</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {suggestions.slice(0, 8).map((pr) => {
                      const mentions = pr.suggestedItemIds.includes(item.id);
                      return (
                        <button key={`${pr.repoFullName}#${pr.number}`} className="btn btn-sm"
                          style={{ justifyContent: 'flex-start', borderColor: mentions ? 'var(--accent)' : undefined }}
                          onClick={() => void linkPr(pr.url)} disabled={busy === 'pr'} title={pr.title}>
                          <span className="mono">#{pr.number}</span>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pr.title}</span>
                          {mentions ? <span className="tag">AB#{item.id}</span> : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {item.commits.length > 0 ? (
            <div className="panel">
              <div className="section">
                <h3><CommitIcon /> Commits ({item.commitCount})</h3>
                {item.commits.map((c) => (
                  <div key={c.id} className="commit-row">
                    <a className="commit-sha" href={c.url} target="_blank" rel="noopener noreferrer">
                      {c.sha.slice(0, 7)}
                    </a>
                    <span className="commit-msg" title={c.message}>{c.message.split('\n')[0]}</span>
                    <span className="muted nowrap" style={{ fontSize: 11 }}>
                      {c.authorLogin ?? c.authorName} · {new Date(c.committedAt).toLocaleDateString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="panel">
            <div className="section">
              <h3>Discussion</h3>
              {comments.length === 0 ? <p className="muted">No comments yet.</p> : null}
              {comments.map((c) => (
                <div key={c.id} className="comment">
                  {c.authorAvatarUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img className="avatar" src={c.authorAvatarUrl} alt="" />
                  ) : null}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="comment-head">
                      <span className="comment-author">{c.authorLogin}</span>
                      <span className="comment-time">{new Date(c.createdAt).toLocaleString()}</span>
                    </div>
                    <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{c.body}</div>
                  </div>
                </div>
              ))}
              <div style={{ marginTop: 12 }}>
                <textarea style={{ minHeight: 72 }} value={commentBody}
                  placeholder={`Comment as ${currentUser.login}…`}
                  onChange={(e) => setCommentBody(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void postComment(); }} />
                <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button className="btn btn-primary" onClick={() => void postComment()} disabled={busy === 'comment' || !commentBody.trim()}>Comment</button>
                  <span className="muted" style={{ fontSize: 12 }}>Ctrl/&#8984; + Enter</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="stack">
          <div className="panel">
            <div className="section">
              <h3>Details</h3>
              <div className="meta-row"><span className="meta-label">State</span><StateBadge state={item.state} /></div>
              <div className="meta-row"><span className="meta-label">Assignee</span><Assignee login={item.assigneeLogin} avatarUrl={item.assigneeAvatarUrl} /></div>
              <div className="meta-row">
                <span className="meta-label">Sprint</span>
                {sprintName ? <Link href={`/backlog?sprint=${item.sprintId}`}>{sprintName}</Link> : <span className="muted">Backlog</span>}
              </div>
              <div className="meta-row"><span className="meta-label">Points</span><span>{item.storyPoints ?? <span className="muted">—</span>}</span></div>
              <div className="meta-row"><span className="meta-label">Priority</span><PriorityChip priority={item.priority} /></div>
              <div className="meta-row">
                <span className="meta-label">Tags</span>
                <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {item.tags.length ? item.tags.map((t) => <span key={t} className="tag">{t}</span>) : <span className="muted">None</span>}
                </span>
              </div>
              <div className="meta-row">
                <span className="meta-label">Created</span>
                <span className="muted">{new Date(item.createdAt).toLocaleDateString()} by {item.createdBy || 'unknown'}</span>
              </div>
              {item.closedAt ? (
                <div className="meta-row"><span className="meta-label">Closed</span><span className="muted">{new Date(item.closedAt).toLocaleDateString()}</span></div>
              ) : null}
            </div>
          </div>

          {attachmentsEnabled ? (
            <div className="panel">
              <div className="section">
                <h3>Attachments</h3>
                {attachments.length === 0 ? <p className="muted">No files attached.</p> : null}
                {attachments.map((a) => (
                  <div key={a.id} className="commit-row">
                    <a href={`/api/v1/items/${item.id}/attachments/${a.id}`} className="commit-msg" title={a.filename}>{a.filename}</a>
                    <span className="muted nowrap" style={{ fontSize: 11 }}>{(a.sizeBytes / 1024).toFixed(0)} KB</span>
                  </div>
                ))}
                <label className="btn btn-sm" style={{ marginTop: 8, display: 'inline-flex' }}>
                  {busy === 'upload' ? <span className="spinner" /> : null} Attach a file
                  <input type="file" style={{ display: 'none' }}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ''; }} />
                </label>
              </div>
            </div>
          ) : null}

          <div className="panel">
            <div className="section">
              <h3>History</h3>
              {activity.length === 0 ? <p className="muted">No activity recorded.</p> : null}
              {activity.map((a) => (
                <div key={a.id} className="activity-item">
                  {a.source !== 'user' ? (
                    <span className={`src-badge src-${a.source}`}>{a.source}</span>
                  ) : null}
                  <span style={{ flex: 1 }}>
                    <strong>{a.actorLogin}</strong>{' '}
                    {a.field === 'created' ? <>created this item</>
                      : a.field === 'pull_request' ? <>linked <strong>{a.newValue}</strong></>
                      : a.field === 'branch' ? <>created branch <strong>{a.newValue}</strong></>
                      : (
                        <>
                          changed <strong>{a.field}</strong>
                          {a.oldValue ? <> from &ldquo;{a.oldValue}&rdquo;</> : null}
                          {a.newValue ? <> to &ldquo;{a.newValue}&rdquo;</> : null}
                        </>
                      )}
                    {a.note ? <div className="muted" style={{ fontSize: 11 }}>{a.note}</div> : null}
                  </span>
                  <span className="muted nowrap">{new Date(a.createdAt).toLocaleDateString()}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {editing ? (
        <WorkItemDialog item={item} sprints={sprints} members={members}
          onClose={() => setEditing(false)}
          onSaved={(next) => {
            setItem(next);
            setEditing(false);
            if (next.description !== item.description) router.refresh();
          }} />
      ) : null}
    </>
  );
}
