import { withApi } from '@/lib/api/route';
import { apiError, ok, readJson, validationError } from '@/lib/api/respond';
import { lookupIdempotent, saveIdempotent } from '@/lib/api/idempotency';
import { principalToActor } from '@/lib/auth/principal';
import { createWorkItemSchema, type WorkItemState } from '@/lib/domain/workitem';
import { createWorkItem, listWorkItems } from '@/lib/domain/queries';
import { readinessMap } from '@/lib/domain/deps-queries';
import { z } from 'zod';

export const dynamic = 'force-dynamic';

/**
 * GET /api/v1/items — list and filter work items.
 * Query: state, type, assignee (or "me"), sprintId ("none"|"all"|<id>), tag, q,
 *        includeRemoved, limit, offset.
 */
export const GET = withApi(async ({ request, principal }) => {
  const sp = new URL(request.url).searchParams;
  const sprintParam = sp.get('sprintId');
  const assignee = sp.get('assignee');

  const items = await listWorkItems({
    state: (sp.get('state') as WorkItemState) || undefined,
    itemType: sp.get('type') || undefined,
    assignee: assignee === 'me' ? principal.login : assignee || undefined,
    tag: sp.get('tag') || undefined,
    wave: sp.get('wave') || undefined,
    search: sp.get('q') || undefined,
    sprintId:
      sprintParam === null || sprintParam === '' || sprintParam === 'all'
        ? undefined
        : sprintParam === 'none'
          ? null
          : Number(sprintParam),
    includeRemoved: sp.get('includeRemoved') === 'true',
    limit: sp.get('limit') ? Number(sp.get('limit')) : undefined,
    offset: sp.get('offset') ? Number(sp.get('offset')) : undefined,
  });

  // Readiness is resolved in one query for the whole board, not per item.
  const readiness = await readinessMap();
  return ok({
    items: items.map((i) => ({
      ...i,
      readiness: readiness.get(i.id) ?? { ready: true, blockers: [], overridden: false },
    })),
    count: items.length,
  });
});

/**
 * POST /api/v1/items — create one item, or many in a single call.
 *
 * Accepts either a single work item object, or `{ "items": [ ... ] }` for bulk
 * creation (an agent seeding a plan wants one round trip, not twenty).
 * Honours an `Idempotency-Key` header so a retried call cannot duplicate.
 */
const bulkSchema = z.object({ items: z.array(createWorkItemSchema).min(1).max(100) });

export const POST = withApi(async ({ request, principal }) => {
  const parsedBody = await readJson(request);
  if (!parsedBody.ok) return parsedBody.response;
  const body = parsedBody.value;

  const idemKey = request.headers.get('idempotency-key')?.trim();
  if (idemKey) {
    const found = await lookupIdempotent(idemKey, principal.login, body);
    if (found.kind === 'conflict') {
      return apiError(
        'idempotency_conflict',
        'This Idempotency-Key was already used with a different request body.',
        409,
      );
    }
    if (found.kind === 'replay') {
      return new Response(found.replay.body, {
        status: found.replay.status,
        headers: { 'content-type': 'application/json', 'idempotent-replay': 'true' },
      });
    }
  }

  const isBulk = typeof body === 'object' && body !== null && Array.isArray((body as { items?: unknown }).items);
  const actor = principalToActor(principal);

  let responseBody: unknown;
  let status: number;

  if (isBulk) {
    const parsed = bulkSchema.safeParse(body);
    if (!parsed.success) return validationError(parsed.error);
    const created = [];
    for (const input of parsed.data.items) {
      created.push(await createWorkItem(input, actor));
    }
    responseBody = { items: created, count: created.length };
    status = 201;
  } else {
    const parsed = createWorkItemSchema.safeParse(body);
    if (!parsed.success) return validationError(parsed.error);
    responseBody = { item: await createWorkItem(parsed.data, actor) };
    status = 201;
  }

  if (idemKey) await saveIdempotent(idemKey, principal.login, body, status, responseBody);
  return ok(responseBody, status);
});
