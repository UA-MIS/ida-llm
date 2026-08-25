'use client';

import { useState } from 'react';
import { api, ApiError } from '@/lib/apiClient';
import { useToast } from './Toast';
import type { ApiTokenRecord } from '@/lib/auth/tokens';

/**
 * Personal access tokens.
 *
 * The plaintext value is returned by the API exactly once, at creation, so it
 * is surfaced prominently here and never fetched again.
 */
export function Tokens({
  initialTokens,
  appUrl,
  docsPath,
}: {
  initialTokens: ApiTokenRecord[];
  appUrl: string;
  docsPath: string;
}) {
  const [tokens, setTokens] = useState(initialTokens);
  const [name, setName] = useState('');
  const [expiresInDays, setExpiresInDays] = useState<number | null>(90);
  const [fresh, setFresh] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function create() {
    if (!name.trim()) {
      toast.push({ tone: 'error', text: 'Give the token a name so you can recognise it later.' });
      return;
    }
    setBusy(true);
    try {
      const res = await api<{ token: string; record: ApiTokenRecord }>('/tokens', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), expiresInDays }),
      });
      setTokens((t) => [res.record, ...t]);
      setFresh(res.token);
      setName('');
    } catch (err) {
      toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: number) {
    if (!confirm('Revoke this token? Anything using it stops working immediately.')) return;
    try {
      await api(`/tokens/${id}`, { method: 'DELETE' });
      setTokens((t) => t.map((x) => (x.id === id ? { ...x, revokedAt: new Date().toISOString() } : x)));
      toast.push({ tone: 'ok', text: 'Token revoked.' });
    } catch (err) {
      toast.push({ tone: 'error', text: err instanceof ApiError ? err.message : String(err) });
    }
  }

  function copy(text: string) {
    void navigator.clipboard?.writeText(text).then(
      () => toast.push({ tone: 'ok', text: 'Token copied to the clipboard.' }),
      () => toast.push({ tone: 'error', text: 'Could not copy — select and copy manually.' }),
    );
  }

  return (
    <>
      <div className="page-head">
        <h1>Personal access tokens</h1>
      </div>

      <div className="detail-grid">
        <div className="stack">
          {fresh ? (
            <div className="panel" style={{ borderColor: 'var(--ok)' }}>
              <div className="section">
                <h3 style={{ color: 'var(--ok)' }}>Copy your new token now</h3>
                <p className="muted" style={{ marginTop: 0 }}>
                  This is the only time it will be shown. Only a hash is stored, so it cannot be
                  recovered — if you lose it, revoke it and create another.
                </p>
                <div className="copyable">
                  <code>{fresh}</code>
                  <button className="btn btn-sm" onClick={() => copy(fresh)}>Copy</button>
                </div>
                <button className="btn btn-sm btn-ghost" style={{ marginTop: 8 }} onClick={() => setFresh(null)}>
                  I&rsquo;ve saved it
                </button>
              </div>
            </div>
          ) : null}

          <div className="panel">
            <div className="section">
              <h3>Your tokens</h3>
              {tokens.length === 0 ? (
                <div className="empty">
                  <div className="empty-title">No tokens yet</div>
                  Create one to drive this board from a script or an agent.
                </div>
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr><th>Name</th><th>Prefix</th><th>Created</th><th>Last used</th><th>Status</th><th /></tr>
                    </thead>
                    <tbody>
                      {tokens.map((t) => {
                        return (
                          <tr key={t.id}>
                            <td>{t.name}</td>
                            <td className="mono muted">{t.tokenPrefix}…</td>
                            <td className="muted">{new Date(t.createdAt).toLocaleDateString()}</td>
                            <td className="muted">{t.lastUsedAt ? new Date(t.lastUsedAt).toLocaleDateString() : 'never'}</td>
                            <td>
                              {t.revokedAt ? <span className="tag" style={{ color: 'var(--danger)' }}>revoked</span>
                                : t.expired ? <span className="tag" style={{ color: 'var(--warn)' }}>expired</span>
                                : <span className="tag" style={{ color: 'var(--ok)' }}>active</span>}
                            </td>
                            <td>
                              {!t.revokedAt ? (
                                <button className="btn btn-sm btn-ghost btn-danger" onClick={() => void revoke(t.id)}>Revoke</button>
                              ) : null}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          <div className="panel">
            <div className="section">
              <h3>Using a token</h3>
              <p className="muted" style={{ marginTop: 0 }}>
                Send it as a bearer token. Anything you can do in this UI, the API can do — items,
                state transitions, sprints, PR links — and everything a token creates is attributed
                to you in the item history.
              </p>
              <div className="copyable">
                <code>
                  curl -H &quot;Authorization: Bearer $IDA_AGILE_TOKEN&quot; {appUrl}/api/v1/items
                </code>
              </div>
              <p className="hint">
                Full reference: <a href={docsPath}>{docsPath}</a> · OpenAPI:{' '}
                <a href="/api/v1/openapi.json">/api/v1/openapi.json</a>
              </p>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="section">
            <h3>New token</h3>
            <div className="field">
              <label htmlFor="tk-name">Name</label>
              <input id="tk-name" type="text" value={name} placeholder="claude-agent"
                     onChange={(e) => setName(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter') void create(); }} />
              <div className="hint">Something you&rsquo;ll recognise in this list later.</div>
            </div>
            <div className="field">
              <label htmlFor="tk-exp">Expires</label>
              <select id="tk-exp" value={expiresInDays ?? ''} onChange={(e) => setExpiresInDays(e.target.value === '' ? null : Number(e.target.value))}>
                <option value="30">In 30 days</option>
                <option value="90">In 90 days</option>
                <option value="365">In 1 year</option>
                <option value="">No expiry</option>
              </select>
            </div>
            <button className="btn btn-primary btn-block" onClick={() => void create()} disabled={busy}>
              {busy ? <span className="spinner" /> : null} Create token
            </button>
            <p className="hint">
              A token acts as you and can never outlive your membership of the team — it is revoked
              automatically if you leave.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
