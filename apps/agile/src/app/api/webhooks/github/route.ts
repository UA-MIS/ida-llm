import type { NextRequest } from 'next/server';
import { config } from '@/lib/env';
import { ensureSchema } from '@/lib/bootstrap';
import { query, queryOne } from '@/lib/db/pool';
import { verifyWebhookSignature } from '@/lib/sync/webhook';
import {
  handleBranchDeleted,
  handleCheckState,
  handlePullRequest,
  handlePush,
} from '@/lib/sync/engine';

export const dynamic = 'force-dynamic';

/**
 * GitHub webhook receiver.
 *
 * AUTH SEAM: this is the ONE route not behind the team-membership gate, because
 * GitHub cannot authenticate as a team member. Its authentication is the HMAC
 * signature instead, verified before the body is parsed or any work is done.
 * The exemption is scoped to exactly this path — every other route still goes
 * through withApi()/requireSession().
 */
export async function POST(request: NextRequest) {
  // Read the body as raw text: the signature covers the exact bytes sent.
  const raw = await request.text();

  const verdict = verifyWebhookSignature(
    raw,
    request.headers.get('x-hub-signature-256'),
    config.webhookSecret,
  );

  if (!verdict.valid) {
    const status = verdict.reason === 'not-configured' ? 503 : 401;
    const message =
      verdict.reason === 'not-configured'
        ? 'Webhooks are not configured on this deployment (GITHUB_WEBHOOK_SECRET is unset).'
        : 'Invalid webhook signature.';
    // Deliberately terse: never tell an unauthenticated caller which check failed.
    return Response.json({ error: message }, { status });
  }

  try {
    await ensureSchema();
  } catch {
    return Response.json({ error: 'Database unavailable.' }, { status: 503 });
  }

  const event = request.headers.get('x-github-event') ?? 'unknown';
  const deliveryId = request.headers.get('x-github-delivery') ?? '';

  // At-most-once: GitHub retries deliveries, and replaying a push would
  // re-run progression rules.
  if (deliveryId) {
    const seen = await queryOne<{ delivery_id: string }>(
      'SELECT delivery_id FROM webhook_deliveries WHERE delivery_id = $1',
      [deliveryId],
    );
    if (seen) return Response.json({ ok: true, deduplicated: true });
    await query(
      'INSERT INTO webhook_deliveries (delivery_id, event) VALUES ($1,$2) ON CONFLICT DO NOTHING',
      [deliveryId, event],
    );
  }

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return Response.json({ error: 'Malformed JSON payload.' }, { status: 400 });
  }

  try {
    const result = await dispatch(event, payload);
    return Response.json({ ok: true, event, ...result });
  } catch (err) {
    console.error('[webhook] handler failed', err);
    // 500 so GitHub retries; the delivery-id row is what stops a double-apply
    // of anything that did succeed.
    return Response.json({ error: 'Handler failed.' }, { status: 500 });
  }
}

async function dispatch(event: string, payload: Record<string, unknown>) {
  const repo = (payload.repository ?? {}) as { full_name?: string };
  const repoFullName = repo.full_name ?? '';

  switch (event) {
    case 'ping':
      return { pong: true };

    case 'push': {
      const ref = String(payload.ref ?? '');
      if (!ref.startsWith('refs/heads/')) return { ignored: 'not a branch ref' };
      const branch = ref.slice('refs/heads/'.length);
      const commits = Array.isArray(payload.commits) ? payload.commits : [];
      const outcome = await handlePush({
        repoFullName,
        branch,
        commits: commits.map((c) => {
          const commit = c as Record<string, unknown>;
          const author = (commit.author ?? {}) as Record<string, unknown>;
          return {
            sha: String(commit.id ?? ''),
            message: String(commit.message ?? ''),
            authorLogin: (author.username as string) ?? null,
            authorName: String(author.name ?? ''),
            url: String(commit.url ?? ''),
            committedAt: String(commit.timestamp ?? new Date().toISOString()),
          };
        }),
      });
      return summarise(outcome);
    }

    case 'delete': {
      // GitHub sends `delete` for branches AND tags; only a branch concerns us.
      if (String(payload.ref_type ?? '') !== 'branch') {
        return { ignored: `not a branch (ref_type "${String(payload.ref_type ?? '')}")` };
      }
      // Documented as the bare name, but strip the prefix defensively so a
      // `refs/heads/` form can never silently fail to match an item.
      const branch = String(payload.ref ?? '').replace(/^refs\/heads\//, '');
      const outcome = await handleBranchDeleted(repoFullName, branch);
      return summarise(outcome);
    }

    case 'pull_request': {
      const pr = (payload.pull_request ?? {}) as Record<string, unknown>;
      const head = (pr.head ?? {}) as { ref?: string };
      const base = (pr.base ?? {}) as { ref?: string };
      const outcome = await handlePullRequest({
        repoFullName,
        number: Number(pr.number ?? 0),
        url: String(pr.html_url ?? ''),
        title: String(pr.title ?? ''),
        body: typeof pr.body === 'string' ? pr.body : '',
        state: String(pr.state ?? 'open'),
        merged: pr.merged === true || Boolean(pr.merged_at),
        draft: pr.draft === true,
        headRef: head.ref ?? '',
        baseRef: base.ref ?? '',
        action: String(payload.action ?? ''),
      });
      return summarise(outcome);
    }

    case 'check_suite':
    case 'check_run': {
      const node = (payload.check_suite ?? payload.check_run ?? {}) as Record<string, unknown>;
      const prs = Array.isArray(node.pull_requests) ? node.pull_requests : [];
      const numbers = prs
        .map((p) => Number((p as { number?: number }).number ?? 0))
        .filter((n) => n > 0);
      const conclusion = (node.conclusion as string) ?? null;
      const state =
        conclusion === 'success'
          ? 'success'
          : conclusion === null
            ? 'pending'
            : conclusion === 'neutral' || conclusion === 'skipped'
              ? 'success'
              : 'failure';
      const outcome = await handleCheckState(repoFullName, numbers, state);
      return summarise(outcome);
    }

    default:
      return { ignored: `unhandled event "${event}"` };
  }
}

function summarise(outcome: {
  itemsTouched: number[];
  transitions: Array<{ itemId: number; from: string; to: string }>;
  warnings: string[];
}) {
  return {
    items: [...new Set(outcome.itemsTouched)],
    transitions: outcome.transitions,
    warnings: outcome.warnings,
  };
}
